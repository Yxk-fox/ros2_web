#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源监控历史采样服务（T-5.2-03）

职责：
  - 后台线程每 30s 采集一次系统资源（复用 SystemMonitor.get_structured_metrics）
  - 写入本地 SQLite（data/metrics.db，单表宽表，WAL 模式 + 每次操作独立连接）
  - 滚动清理保留 7 天；文件超 100MB 自动裁剪最旧一半数据
  - 守护结构：supervisor 线程监控 worker 线程，worker 崩溃后延迟自动重启，
    任何异常均不外溢到主进程（验收②）
  - 采样失败静默跳过本次（不影响主服务）

查询（供 API 层调用）：
  query_history(metric, range) → 降采样后的 (ts, value) 点列，
  四档范围：1h（原始粒度）/ 6h（5min 桶）/ 24h（15min 桶）/ 7d（1h 桶）
"""

import os
import sqlite3
import threading
import time
from contextlib import closing

from logger import logger
from services.system_monitor import SystemMonitor

# ---------- 配置常量 ----------
SAMPLE_INTERVAL = 30                      # 采样间隔（秒）
RETENTION_SECONDS = 7 * 86400             # 滚动清理：保留 7 天
MAX_DB_SIZE_BYTES = 100 * 1024 * 1024     # 文件超 100MB 自动裁剪
WORKER_RESTART_DELAY = 5                  # worker 崩溃后重启延迟（秒）
CLEANUP_EVERY_N_SAMPLES = 20              # 每 N 次采样做一轮滚动清理（约 10 分钟）

# 数据库路径：backend/../data/metrics.db（deploy.py 已确保 data 目录存在）
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "metrics.db"
)

# 查询指标名 → 表列名（白名单，防 SQL 注入）
METRIC_COLUMNS = {
    "cpu": "cpu_percent",
    "mem": "mem_percent",
    "mem_used": "mem_used_mb",
    "swap": "swap_percent",
    "load": "load_1m",
    "gpu_util": "gpu_util_avg",
    "gpu_mem": "gpu_mem_used_mb",
    "gpu_temp": "gpu_temp_max",
    "container_count": "container_count",
    "container_cpu": "container_cpu_sum",
    "container_mem": "container_mem_used_mb",
}

# 范围档位：range → (查询跨度秒, 聚合桶大小秒)
RANGE_CONFIG = {
    "1h": (3600, 30),          # 原始粒度，约 120 点
    "6h": (6 * 3600, 300),     # 5min 桶，72 点
    "24h": (24 * 3600, 900),   # 15min 桶，96 点
    "7d": (7 * 86400, 3600),   # 1h 桶，168 点
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts INTEGER NOT NULL PRIMARY KEY,
    cpu_percent REAL,
    mem_percent REAL,
    mem_used_mb INTEGER,
    mem_total_mb INTEGER,
    swap_percent REAL,
    load_1m REAL,
    gpu_count INTEGER,
    gpu_util_avg REAL,
    gpu_mem_used_mb INTEGER,
    gpu_mem_total_mb INTEGER,
    gpu_temp_max REAL,
    container_count INTEGER,
    container_cpu_sum REAL,
    container_mem_used_mb REAL
)
"""

_start_lock = threading.Lock()
_started = False
_stop_event = threading.Event()

# T-5.2-05：待发送告警队列（sample_once 写入，worker_loop flush 推送）
_pending_alerts = []


def _connect(db_path=None):
    """打开独立连接（WAL 模式），调用方负责关闭。

    每次操作新建连接、用完即关，彻底规避跨线程共享连接的锁问题（风险应对项）。
    """
    conn = sqlite3.connect(db_path or DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db(db_path=None):
    """初始化表结构（幂等）"""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(_SCHEMA)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")


def sample_once(db_path=None):
    """采集一次系统指标并落库（守护线程与单测共用）

    返回 True 表示落库成功；采集/写库失败仅记日志并返回 False（静默降级）。
    """
    try:
        m = SystemMonitor.get_structured_metrics()
        gpus = m.get("gpus") or []
        containers = m.get("containers") or {}

        ts = int(time.time())
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(
                """INSERT OR REPLACE INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts,
                    m.get("cpu_percent"),
                    m.get("mem_percent"),
                    m.get("mem_used_mb"),
                    m.get("mem_total_mb"),
                    m.get("swap_percent"),
                    m.get("load_1m"),
                    len(gpus) if gpus else 0,
                    round(sum(g["util_percent"] for g in gpus) / len(gpus), 2) if gpus else None,
                    sum(g["mem_used_mb"] for g in gpus) if gpus else None,
                    sum(g["mem_total_mb"] for g in gpus) if gpus else None,
                    max(g["temp_c"] for g in gpus) if gpus else None,
                    containers.get("count"),
                    containers.get("cpu_percent_sum"),
                    containers.get("mem_used_mb_sum"),
                ),
            )
        # T-5.2-05：告警检查（去抖 + 冷却），触发后推入待发送队列
        try:
            from services.alert_service import check_alerts
            _pending_alerts.extend(check_alerts(m))
        except Exception as ae:
            logger.debug(f"[metrics_history] 告警检查失败（静默跳过）: {ae}")
        return True
    except Exception as e:
        logger.warning(f"[metrics_history] 采样失败（跳过本次）: {e}")
        return False


def cleanup(db_path=None, max_bytes=None):
    """滚动清理 + 超限裁剪

    1. 删除 7 天前的采样行（有索引，代价低）；
    2. 若文件超过 max_bytes（默认 100MB）：删除最旧一半数据后 VACUUM 回收空间。
    """
    path = db_path or DB_PATH
    limit = max_bytes if max_bytes is not None else MAX_DB_SIZE_BYTES
    try:
        with closing(_connect(path)) as conn, conn:
            conn.execute("DELETE FROM metrics WHERE ts < ?", (int(time.time()) - RETENTION_SECONDS,))
        # 超限裁剪：删最旧一半后 VACUUM 回收磁盘（VACUUM 不可在事务内，需先 commit）
        if os.path.exists(path) and os.path.getsize(path) > limit:
            with closing(_connect(path)) as conn:
                row = conn.execute("SELECT MIN(ts), MAX(ts) FROM metrics").fetchone()
                if row and row[0] is not None:
                    midpoint = (row[0] + row[1]) // 2
                    conn.execute("DELETE FROM metrics WHERE ts < ?", (midpoint,))
                    conn.commit()
                    conn.execute("VACUUM")
                    logger.info(f"[metrics_history] 数据库超 {limit // 1024 // 1024}MB，已裁剪 {midpoint} 之前数据")
        return True
    except Exception as e:
        logger.warning(f"[metrics_history] 清理失败（跳过本次）: {e}")
        return False


def query_history(metric, range_str="1h", db_path=None):
    """查询历史曲线（降采样聚合）

    参数：
      metric    METRIC_COLUMNS 中的指标名（非法值抛 ValueError）
      range_str 1h/6h/24h/7d（非法值抛 ValueError）
    返回：
      [{"ts": <bucket 起始秒>, "value": <均值>}, ...] 按时间升序
    """
    column = METRIC_COLUMNS.get(metric)
    if column is None:
        raise ValueError(f"未知指标: {metric}（可选: {', '.join(METRIC_COLUMNS)}）")
    cfg = RANGE_CONFIG.get(range_str)
    if cfg is None:
        raise ValueError(f"未知范围: {range_str}（可选: {', '.join(RANGE_CONFIG)}）")
    span, bucket = cfg

    since = int(time.time()) - span
    with closing(_connect(db_path)) as conn:
        # 列名来自模块级白名单，非用户输入直接拼接，无注入风险
        rows = conn.execute(
            f"SELECT (ts / ?) * ? AS b, AVG({column}) FROM metrics "
            f"WHERE ts >= ? AND {column} IS NOT NULL GROUP BY b ORDER BY b",
            (bucket, bucket, since),
        ).fetchall()
    return [{"ts": r[0], "value": round(r[1], 2) if r[1] is not None else None} for r in rows]


# ---------- 守护线程（supervisor + worker 双层） ----------

def _worker_loop():
    """采样循环：单次失败静默跳过，仅致命错误（如 SQLite 持续不可用）抛出由 supervisor 兜底"""
    counter = 0
    while not _stop_event.is_set():
        sample_once()
        counter += 1
        if counter % CLEANUP_EVERY_N_SAMPLES == 0:
            cleanup()
        # T-5.2-05：flush 待发送告警到 WebSocket + 审计日志
        _flush_alerts()
        # 分段等待，保证 stop_event 能及时打断
        for _ in range(SAMPLE_INTERVAL):
            if _stop_event.wait(timeout=1):
                return


def _flush_alerts():
    """推送待发送告警到 WebSocket 客户端 + 审计日志（worker 线程调用）"""
    global _pending_alerts
    if not _pending_alerts:
        return
    alerts = _pending_alerts[:]
    _pending_alerts = []
    try:
        import asyncio
        import json
        from core.constants import ws_clients

        async def _push():
            msg = json.dumps({"type": "alert", "alerts": alerts, "timestamp": int(time.time())})
            for client in ws_clients[:]:
                try:
                    await client.send_text(msg)
                except Exception:
                    if client in ws_clients:
                        ws_clients.remove(client)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 主事件循环运行中（理论不应在 worker 线程触发），用线程安全方式
                asyncio.run_coroutine_threadsafe(_push(), loop)
            else:
                raise RuntimeError("no running loop")
        except RuntimeError:
            asyncio.run(_push())

        # 审计日志 + 日志
        try:
            from database import db
            for a in alerts:
                db.add_audit_log("system", "alert", a["message"])
        except Exception as de:
            logger.debug(f"[metrics_history] 审计日志写入失败（静默）: {de}")
        for a in alerts:
            logger.warning(f"[alert] {a['message']}")
    except Exception as e:
        logger.warning(f"[metrics_history] 告警推送失败（静默跳过）: {e}")


def _supervisor_loop():
    """守护采样线程：worker 异常退出后延迟重启（验收②），自身永不抛异常"""
    while not _stop_event.is_set():
        worker = threading.Thread(target=_worker_loop, name="metrics-worker", daemon=True)
        worker.start()
        worker.join()  # 正常 return（stop）或异常退出均在此醒来
        if _stop_event.is_set():
            return
        logger.warning(
            f"[metrics_history] 采样线程异常退出，{WORKER_RESTART_DELAY}s 后自动重启"
        )
        _stop_event.wait(timeout=WORKER_RESTART_DELAY)


def start_metrics_history():
    """启动采样守护（幂等，供 app.py startup 事件调用）"""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _init_db()
        _stop_event.clear()
        t = threading.Thread(target=_supervisor_loop, name="metrics-supervisor", daemon=True)
        t.start()
        logger.info(
            f"[metrics_history] 采样守护已启动（间隔 {SAMPLE_INTERVAL}s，"
            f"保留 {RETENTION_SECONDS // 86400} 天，库文件 {DB_PATH}）"
        )
    except Exception as e:
        logger.error(f"[metrics_history] 启动失败（不影响主服务）: {e}")


def stop_metrics_history():
    """停止采样守护（供单测/优雅退出使用）"""
    global _started
    _stop_event.set()
    with _start_lock:
        _started = False
