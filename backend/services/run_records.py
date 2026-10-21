#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脚本运行记录服务（T-5.2-04）

职责：
  - 记录脚本执行 / 容器启停事件到本地 SQLite（data/run_records.db）
  - 提供聚合查询接口供 /api/scripts/run-report 使用
  - 滚动清理保留 30 天；文件超 50MB 自动裁剪

设计要点：
  - 同步写入（调用方在操作完成时 record_run），无需后台线程
  - 每次操作独立连接（WAL 模式），规避跨线程锁问题
  - 写入失败仅记日志，不影响主业务流程（静默降级）
"""

import os
import json
import sqlite3
import time
from contextlib import closing

from logger import logger

# ---------- 配置常量 ----------
RETENTION_SECONDS = 30 * 86400           # 保留 30 天
MAX_DB_SIZE_BYTES = 50 * 1024 * 1024     # 文件超 50MB 自动裁剪

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "run_records.db"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    username TEXT,
    script_name TEXT,
    container_name TEXT,
    version TEXT,
    success INTEGER DEFAULT 1,
    duration INTEGER,
    error TEXT,
    extra TEXT
)
"""

# 范围档位：range → 查询跨度秒
RANGE_CONFIG = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}


def _connect(db_path=None):
    """打开独立连接（WAL 模式），调用方负责关闭。"""
    conn = sqlite3.connect(db_path or DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db(db_path=None):
    """初始化表结构（幂等）"""
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(_SCHEMA)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_ts ON run_records(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_action ON run_records(action)")


def record_run(action, username="", script_name="", container_name="",
               version="", success=True, duration=None, error="", extra=None,
               db_path=None):
    """记录一条运行事件（供 API 层在脚本执行/容器启停后调用）

    :param action:  start / stop / stop_all / batch_start
    :param success: 是否成功
    :param duration: 运行时长秒（可选）
    :param extra:   dict 扩展字段，JSON 序列化存储
    :return: True 写入成功，False 写入失败（仅记日志，不抛异常）
    """
    try:
        _init_db(db_path)
        ts = int(time.time())
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(
                """INSERT INTO run_records
                   (ts, action, username, script_name, container_name, version,
                    success, duration, error, extra)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, action, username, script_name, container_name, version,
                    1 if success else 0, duration, error,
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                ),
            )
        return True
    except Exception as e:
        logger.warning(f"[run_records] 记录失败（不影响主流程）: {e}")
        return False


def query_report(range_str="7d", db_path=None):
    """聚合查询运行报告

    :return: dict 包含 summary / by_script / by_user / by_version / timeline
    """
    span = RANGE_CONFIG.get(range_str)
    if span is None:
        raise ValueError(f"未知范围: {range_str}（可选: {', '.join(RANGE_CONFIG)}）")

    _init_db(db_path)
    since = int(time.time()) - span
    with closing(_connect(db_path)) as conn:
        # 汇总
        summary_row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN success=1 THEN 1 ELSE 0 END), "
            "COUNT(DISTINCT container_name), COUNT(DISTINCT username) "
            "FROM run_records WHERE ts >= ?",
            (since,),
        ).fetchone()
        total = summary_row[0] or 0
        success_count = summary_row[1] or 0
        container_count = summary_row[2] or 0
        user_count = summary_row[3] or 0

        # 按脚本分组
        by_script = [
            {"script_name": r[0] or "", "count": r[1],
             "success": r[2] or 0, "fail": r[3] or 0}
            for r in conn.execute(
                "SELECT script_name, COUNT(*), "
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) "
                "FROM run_records WHERE ts >= ? AND script_name != '' "
                "GROUP BY script_name ORDER BY COUNT(*) DESC",
                (since,),
            ).fetchall()
        ]

        # 按用户分组
        by_user = [
            {"username": r[0] or "", "count": r[1], "success": r[2] or 0, "fail": r[3] or 0}
            for r in conn.execute(
                "SELECT username, COUNT(*), "
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) "
                "FROM run_records WHERE ts >= ? AND username != '' "
                "GROUP BY username ORDER BY COUNT(*) DESC",
                (since,),
            ).fetchall()
        ]

        # 按版本分组
        by_version = [
            {"version": r[0] or "(默认)", "count": r[1], "success": r[2] or 0, "fail": r[3] or 0}
            for r in conn.execute(
                "SELECT COALESCE(version, '') AS v, COUNT(*), "
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) "
                "FROM run_records WHERE ts >= ? "
                "GROUP BY v ORDER BY COUNT(*) DESC",
                (since,),
            ).fetchall()
        ]

        # 时间线（按天聚合，range <= 24h 按小时）
        if span <= 86400:
            bucket = 3600
            tl_label = "hourly"
        else:
            bucket = 86400
            tl_label = "daily"
        timeline = [
            {"ts": r[0], "count": r[1], "success": r[2] or 0, "fail": r[3] or 0}
            for r in conn.execute(
                f"SELECT (ts / {bucket}) * {bucket} AS b, COUNT(*), "
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) "
                "FROM run_records WHERE ts >= ? GROUP BY b ORDER BY b",
                (since,),
            ).fetchall()
        ]

        # 最近 20 条明细
        recent = [
            {
                "id": r[0], "ts": r[1], "action": r[2], "username": r[3] or "",
                "script_name": r[4] or "", "container_name": r[5] or "",
                "version": r[6] or "", "success": bool(r[7]),
                "duration": r[8], "error": r[9] or "",
            }
            for r in conn.execute(
                "SELECT id, ts, action, username, script_name, container_name, "
                "version, success, duration, error "
                "FROM run_records WHERE ts >= ? ORDER BY ts DESC LIMIT 20",
                (since,),
            ).fetchall()
        ]

    return {
        "range": range_str,
        "summary": {
            "total": total,
            "success": success_count,
            "fail": total - success_count,
            "success_rate": round(success_count / total * 100, 1) if total else 0,
            "container_count": container_count,
            "user_count": user_count,
        },
        "by_script": by_script,
        "by_user": by_user,
        "by_version": by_version,
        "timeline": {"granularity": tl_label, "points": timeline},
        "recent": recent,
    }


def cleanup(db_path=None, max_bytes=None):
    """滚动清理：删除 30 天前数据；文件超限时裁剪最旧一半"""
    path = db_path or DB_PATH
    limit = max_bytes if max_bytes is not None else MAX_DB_SIZE_BYTES
    try:
        _init_db(path)
        with closing(_connect(path)) as conn, conn:
            conn.execute("DELETE FROM run_records WHERE ts < ?",
                         (int(time.time()) - RETENTION_SECONDS,))
        if os.path.exists(path) and os.path.getsize(path) > limit:
            with closing(_connect(path)) as conn:
                row = conn.execute("SELECT MIN(ts), MAX(ts) FROM run_records").fetchone()
                if row and row[0] is not None:
                    midpoint = (row[0] + row[1]) // 2
                    conn.execute("DELETE FROM run_records WHERE ts < ?", (midpoint,))
                    conn.commit()
                    conn.execute("VACUUM")
                    logger.info(f"[run_records] 数据库超限，已裁剪 {midpoint} 之前数据")
        return True
    except Exception as e:
        logger.warning(f"[run_records] 清理失败（跳过本次）: {e}")
        return False
