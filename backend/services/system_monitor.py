#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统监控服务
"""

import os
import time
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

