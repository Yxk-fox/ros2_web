#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统监控服务
"""

import os
import time
import subprocess
import psutil

from logger import logger


class SystemMonitor:
    """系统监控类，采集 CPU/内存/GPU/进程等资源信息"""
    @staticmethod
    def get_system_status():
        """获取系统状态（CPU/内存/GPU/进程）"""
        cpu_percent = psutil.cpu_percent(interval=0.3)
        per_cpu = psutil.cpu_percent(percpu=True, interval=0.3)
        load_avg = psutil.getloadavg()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        lines = []
        lines.append(f"CPU 整体使用率: {cpu_percent}%")
        lines.append(f"平均负载: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}")
        lines.append(f"内存: {mem.percent}% (已用 {mem.used//1024**2}MB / 总计 {mem.total//1024**2}MB)")
        lines.append(f"Swap: {swap.percent}% (已用 {swap.used//1024**2}MB / 总计 {swap.total//1024**2}MB)")
        lines.append("每核心使用率:")
        for i in range(0, len(per_cpu), 4):
            line = ""
            for j in range(4):
                if i + j < len(per_cpu):
                    line += f"Core {i+j:2d}: {per_cpu[i+j]:5.1f}%   "
            lines.append(line.rstrip())
        lines.append("")
        gpu_proc_data = []
        try:
            gpu_info_cmd = [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ]
            result = subprocess.run(gpu_info_cmd, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                gpu_lines = result.stdout.strip().split("\n")
                for line in gpu_lines:
                    if not line.strip():
                        continue
                    parts = [x.strip() for x in line.split(", ")]
                    if len(parts) >= 10:
                        idx, name, driver, gpu_util, mem_total, mem_used, mem_free, temp, power_draw, power_limit = parts[:10]
                        lines.append(f"\nGPU {idx}: {name} (驱动 {driver})")
                        lines.append(f"  利用率: {gpu_util}%  |  显存: {mem_used}MiB / {mem_total}MiB ({int(mem_used)/int(mem_total)*100:.1f}%)")
                        lines.append(f"  温度: {temp}°C  |  功耗: {power_draw}W / {power_limit}W")
            else:
                lines.append("\n⚠️ 无法获取 GPU 信息（未安装 NVIDIA 驱动或 nvidia-smi）")
        except Exception as e:
            lines.append(f"\n❌ GPU 信息读取错误: {e}")
        try:
            proc_cmd = ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory,gpu_uuid", "--format=csv,noheader"]
            proc_result = subprocess.run(proc_cmd, capture_output=True, text=True, timeout=2)
            if proc_result.returncode == 0:
                uuid_cmd = ["nvidia-smi", "--query-gpu=uuid,index", "--format=csv,noheader"]
                uuid_result = subprocess.run(uuid_cmd, capture_output=True, text=True, timeout=2)
                uuid_to_index = {}
                for line in uuid_result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.split(", ")
                        if len(parts) == 2:
                            uuid_to_index[parts[0].strip()] = parts[1].strip()
                for line in proc_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split(", ")
                    if len(parts) >= 4:
                        pid, proc_name, used_mem, gpu_uuid = parts
                        gpu_idx = uuid_to_index.get(gpu_uuid, "?")
                        gpu_proc_data.append((gpu_idx, pid, proc_name, used_mem))
            else:
                lines.append("\n⚠️ 无法获取 GPU 进程信息")
        except Exception as e:
            lines.append(f"\n❌ GPU 进程读取错误: {e}")
        sys_text = "\n".join(lines)
        processes = []
        for proc in psutil.process_iter(['pid', 'username', 'cpu_percent', 'memory_percent', 'name', 'cmdline']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda x: x.get('cpu_percent', 0.0), reverse=True)
        top_procs = processes[:20]
        proc_data = []
        for p in top_procs:
            pid = p.get('pid', '')
            user = p.get('username', '')[:10]
            cpu = f"{p.get('cpu_percent', 0.0):.1f}"
            mem = f"{p.get('memory_percent', 0.0):.1f}"
            cmd_str = p.get('name', '')
            if p.get('cmdline'):
                cmd_str = ' '.join(p.get('cmdline'))[:100]
            proc_data.append((pid, user, cpu, mem, cmd_str))
        return sys_text, proc_data, gpu_proc_data

    @staticmethod
    def get_structured_metrics():
        """结构化资源指标采集（T-5.2-03，供 metrics_history 周期采样落库）

        与 get_system_status()（面向面板的格式化文本）不同，本方法返回纯数值结构，
        任一子项采集失败仅静默降级（None/空列表），不抛异常、不影响其他字段。

        返回结构::

            {
                "cpu_percent": float,           # 整体 CPU 使用率（%）
                "mem_percent": float,           # 内存使用率（%）
                "mem_used_mb": int,
                "mem_total_mb": int,
                "swap_percent": float,          # Swap 使用率（%），无 swap 为 None
                "load_1m": float,               # 1 分钟平均负载
                "gpus": [                       # 无 NVIDIA 环境为 []
                    {"index": int, "util_percent": float, "mem_used_mb": int,
                     "mem_total_mb": int, "temp_c": float}
                ],
                "containers": {                 # docker 不可用时为 None
                    "count": int,               # 运行中容器数
                    "cpu_percent_sum": float,   # 各容器 CPU% 之和（单容器以单核计，可超 100）
                    "mem_used_mb_sum": float,   # 各容器内存用量之和（MB）
                },
            }
        """
        # ----- CPU / 内存 / 负载（psutil，interval=None 复用上次调用以来的均值，非阻塞） -----
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        try:
            load_1m = psutil.getloadavg()[0]
        except Exception:
            load_1m = None

        # ----- GPU（nvidia-smi 单次查询，仅取历史曲线所需子集） -----
        gpus = []
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = [x.strip() for x in line.split(",")]
                    if len(parts) < 5:
                        continue
                    try:
                        gpus.append({
                            "index": int(parts[0]),
                            "util_percent": float(parts[1]),
                            "mem_used_mb": int(float(parts[2])),
                            "mem_total_mb": int(float(parts[3])),
                            "temp_c": float(parts[4]),
                        })
                    except ValueError:
                        continue
        except Exception:
            gpus = []  # 无 NVIDIA 驱动 / nvidia-smi 不存在 → 静默降级

        # ----- 容器资源聚合（docker stats --no-stream 一次取全部，约 1~2s） -----
        containers = None
        try:
            cmd = ["docker", "stats", "--no-stream", "--format",
                   "{{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                count = 0
                cpu_sum = 0.0
                mem_sum_mb = 0.0
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    count += 1
                    # CPUPerc 形如 "12.34%"
                    cpu_str = parts[1].strip().rstrip("%")
                    try:
                        cpu_sum += float(cpu_str)
                    except ValueError:
                        pass
                    # MemUsage 形如 "123.4MiB / 4GiB"，取已用值
                    used_str = parts[2].strip().split("/")[0].strip()
                    mem_sum_mb += _parse_size_to_mb(used_str)
                containers = {
                    "count": count,
                    "cpu_percent_sum": round(cpu_sum, 2),
                    "mem_used_mb_sum": round(mem_sum_mb, 1),
                }
        except Exception:
            containers = None  # docker 不可用 / 超时 → 静默降级

        return {
            "cpu_percent": round(cpu_percent, 2),
            "mem_percent": round(mem.percent, 2),
            "mem_used_mb": int(mem.used // 1024 ** 2),
            "mem_total_mb": int(mem.total // 1024 ** 2),
            "swap_percent": round(swap.percent, 2) if swap.total > 0 else None,
            "load_1m": round(load_1m, 2) if load_1m is not None else None,
            "gpus": gpus,
            "containers": containers,
        }


def _parse_size_to_mb(size_str):
    """解析 docker stats 的内存用量字符串（如 '123.4MiB'/'1.5GiB'/'976kB'）为 MB"""
    size_str = size_str.strip()
    units = {"B": 1 / 1024 ** 2, "KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0,
             "kB": 1 / 1024, "MB": 1.0, "GB": 1024.0, "TiB": 1024.0 ** 2}
    for unit in sorted(units, key=len, reverse=True):
        if size_str.endswith(unit):
            try:
                return float(size_str[:-len(unit)].strip()) * units[unit]
            except ValueError:
                return 0.0
    try:
        return float(size_str) / 1024 ** 2  # 纯字节数兜底
    except ValueError:
        return 0.0

