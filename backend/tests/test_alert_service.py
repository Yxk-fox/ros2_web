#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源告警服务单元测试（T-5.2-05）

覆盖：阈值判断（warning/critical）、去抖、冷却、恢复重置、GPU 聚合、禁用开关。
"""

import pytest

import services.alert_service as alert_service
from services.alert_service import AlertChecker


def make_metrics(cpu=10, mem=10, swap=0, load=0.5, gpu_util=10, gpu_temp=40):
    """构造结构化指标（对齐 SystemMonitor.get_structured_metrics 输出）"""
    return {
        "cpu_percent": cpu,
        "mem_percent": mem,
        "swap_percent": swap,
        "load_1m": load,
        "gpus": [{"util_percent": gpu_util, "temp_c": gpu_temp}],
    }


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    """覆盖 alert_service 模块级配置，避免依赖真实 config.json"""
    monkeypatch.setattr(alert_service, "ALERTS_ENABLED", True)
    monkeypatch.setattr(alert_service, "DEBOUNCE_COUNT", 2)
    monkeypatch.setattr(alert_service, "COOLDOWN_SECONDS", 300)
    monkeypatch.setattr(alert_service, "ALERT_RULES", {
        "cpu_percent": {"warning": 80, "critical": 95},
        "mem_percent": {"warning": 80, "critical": 95},
        "swap_percent": {"warning": 50, "critical": 80},
        "gpu_util_avg": {"warning": 90, "critical": 99},
        "gpu_temp_max": {"warning": 80, "critical": 90},
        "load_1m": {"warning": 8, "critical": 16},
    })


class TestAlertChecker:
    def test_no_alert_when_normal(self):
        checker = AlertChecker()
        assert checker.check(make_metrics(cpu=50, mem=50)) == []

    def test_warning_threshold(self):
        checker = AlertChecker()
        # 第 1 次超阈值，去抖未达 2 次
        assert checker.check(make_metrics(cpu=85)) == []
        # 第 2 次超阈值，触发 warning
        a = checker.check(make_metrics(cpu=85))
        assert len(a) == 1
        assert a[0]["level"] == "warning"
        assert a[0]["metric"] == "cpu_percent"
        assert a[0]["value"] == 85
        assert a[0]["threshold"] == 80

    def test_critical_threshold(self):
        checker = AlertChecker()
        checker.check(make_metrics(cpu=99))
        a = checker.check(make_metrics(cpu=99))
        assert len(a) == 1
        assert a[0]["level"] == "critical"
        assert a[0]["threshold"] == 95

    def test_debounce_reset_on_recovery(self):
        checker = AlertChecker()
        # 第 1 次超阈值
        assert checker.check(make_metrics(cpu=85)) == []
        # 恢复正常，重置去抖
        assert checker.check(make_metrics(cpu=50)) == []
        # 再次第 1 次超阈值，去抖未达
        assert checker.check(make_metrics(cpu=85)) == []

    def test_cooldown_blocks_repeat(self):
        checker = AlertChecker()
        # 触发告警（去抖满 2 次）
        assert checker.check(make_metrics(cpu=85)) == []
        a1 = checker.check(make_metrics(cpu=85))
        assert len(a1) == 1
        # 冷却期内：重新积累去抖后仍被冷却拦截
        assert checker.check(make_metrics(cpu=85)) == []
        a2 = checker.check(make_metrics(cpu=85))
        assert a2 == []  # 冷却中，去抖重置后未触发

    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(alert_service, "ALERTS_ENABLED", False)
        checker = AlertChecker()
        assert checker.check(make_metrics(cpu=99)) == []
        assert checker.check(make_metrics(cpu=99)) == []

    def test_gpu_aggregation(self):
        checker = AlertChecker()
        m = {"gpus": [
            {"util_percent": 95, "temp_c": 85},
            {"util_percent": 95, "temp_c": 85},
        ]}
        # 第 1 次去抖
        assert checker.check(m) == []
        a = checker.check(m)
        # gpu_util_avg=95 >= warning 90；gpu_temp_max=85 >= warning 80
        metrics = [x["metric"] for x in a]
        assert "gpu_util_avg" in metrics
        assert "gpu_temp_max" in metrics

    def test_multiple_metrics_in_one_check(self):
        checker = AlertChecker()
        m = make_metrics(cpu=90, mem=90, swap=60)
        assert checker.check(m) == []
        a = checker.check(m)
        # cpu / mem / swap 同时超阈值
        metrics = sorted(x["metric"] for x in a)
        assert metrics == ["cpu_percent", "mem_percent", "swap_percent"]

    def test_missing_metric_skipped(self):
        checker = AlertChecker()
        # 无 gpus 字段，gpu_* 应跳过；cpu 正常应无告警
        m = {"cpu_percent": 10, "mem_percent": 10}
        assert checker.check(m) == []
        assert checker.check(m) == []
