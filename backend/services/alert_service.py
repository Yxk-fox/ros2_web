#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源告警服务（T-5.2-05）

职责：
  - 在采样守护每次采样后检查指标是否超阈值
  - 去抖：连续 N 次超阈值才触发告警（防瞬时抖动）
  - 冷却：同一指标告警后冷却期内不重复触发
  - 触发后返回告警消息，由调用方通过 WebSocket 推送 + 审计日志记录

设计要点：
  - 线程安全（采样守护线程调用，需加锁）
  - 无状态持久化（重启后冷却清零，符合预期：重启视为恢复）
  - 阈值配置来自 config.json → CONFIG["alerts"]
"""

import threading
import time

from logger import logger
from core.constants import CONFIG

# ---------- 配置加载 ----------
_alerts_cfg = CONFIG.get("alerts", {})
ALERTS_ENABLED = _alerts_cfg.get("enabled", True)
DEBOUNCE_COUNT = _alerts_cfg.get("debounce_count", 2)
COOLDOWN_SECONDS = _alerts_cfg.get("cooldown_seconds", 300)
ALERT_RULES = _alerts_cfg.get("rules", {})

# 指标列名 → 友好显示名
_METRIC_LABELS = {
    "cpu_percent": "CPU 使用率",
    "mem_percent": "内存使用率",
    "swap_percent": "Swap 使用率",
    "gpu_util_avg": "GPU 利用率",
    "gpu_temp_max": "GPU 温度",
    "load_1m": "系统负载(1m)",
}

# 指标列名 → 单位
_METRIC_UNITS = {
    "cpu_percent": "%",
    "mem_percent": "%",
    "swap_percent": "%",
    "gpu_util_avg": "%",
    "gpu_temp_max": "°C",
    "load_1m": "",
}


class AlertChecker:
    """告警检查器（线程安全，单例模式使用）"""

    def __init__(self):
        self._lock = threading.Lock()
        # 去抖计数器：metric → 连续超阈值次数
        self._debounce = {}
        # 冷却时间戳：metric → 上次告警的 unix 时间
        self._cooldowns = {}

    def check(self, metrics):
        """检查结构化指标，返回待触发的告警列表

        :param metrics: SystemMonitor.get_structured_metrics() 返回的 dict
        :return: list[dict]  每项 {metric, level, value, threshold, message}
        """
        if not ALERTS_ENABLED:
            return []

        alerts = []
        with self._lock:
            now = time.time()
            for metric, thresholds in ALERT_RULES.items():
                value = self._extract_metric(metrics, metric)
                if value is None:
                    continue

                level = None
                if "critical" in thresholds and value >= thresholds["critical"]:
                    level = "critical"
                elif "warning" in thresholds and value >= thresholds["warning"]:
                    level = "warning"

                if level is None:
                    # 指标恢复正常，重置去抖计数
                    self._debounce.pop(metric, None)
                    continue

                # 去抖：连续超阈值才计数
                self._debounce[metric] = self._debounce.get(metric, 0) + 1
                if self._debounce[metric] < DEBOUNCE_COUNT:
                    continue

                # 冷却检查
                last_alert_ts = self._cooldowns.get(metric, 0)
                if now - last_alert_ts < COOLDOWN_SECONDS:
                    self._debounce[metric] = 0  # 冷却中重置去抖，需重新积累
                    continue

                # 触发告警
                self._cooldowns[metric] = now
                self._debounce[metric] = 0  # 重置去抖，下一轮重新计数

                label = _METRIC_LABELS.get(metric, metric)
                unit = _METRIC_UNITS.get(metric, "")
                threshold_val = thresholds.get(level, 0)
                alerts.append({
                    "metric": metric,
                    "label": label,
                    "level": level,
                    "value": round(value, 1),
                    "threshold": threshold_val,
                    "unit": unit,
                    "message": f"[{level.upper()}] {label} {value}{unit} ≥ 阈值 {threshold_val}{unit}",
                    "timestamp": int(now),
                })
        return alerts

    def reset(self):
        """重置所有状态（供测试使用）"""
        with self._lock:
            self._debounce.clear()
            self._cooldowns.clear()

    @staticmethod
    def _extract_metric(metrics, metric_name):
        """从结构化指标中提取指定字段值"""
        # CPU / 内存 / 负载等直接字段
        if metric_name in metrics:
            v = metrics[metric_name]
            return float(v) if v is not None else None
        # GPU 聚合字段
        if metric_name == "gpu_util_avg":
            gpus = metrics.get("gpus") or []
            if not gpus:
                return None
            return sum(g["util_percent"] for g in gpus) / len(gpus)
        if metric_name == "gpu_temp_max":
            gpus = metrics.get("gpus") or []
            if not gpus:
                return None
            return max(g["temp_c"] for g in gpus)
        return None


# 模块级单例
_checker = AlertChecker()


def check_alerts(metrics):
    """检查指标并返回告警列表（供采样守护调用）"""
    return _checker.check(metrics)


def reset_alert_state():
    """重置告警状态（供测试使用）"""
    _checker.reset()
