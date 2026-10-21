#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GPU 监控 / 系统自检 / 资源泄漏监控"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 API 路由模块
包含所有后端 REST API 和 WebSocket 路由

后续可按业务领域进一步拆分为：
- auth.py      认证相关
- admin.py     管理员后台
- system.py    系统管理
- docker.py    Docker 容器
- ros2.py      ROS2 功能
- scripts.py   脚本管理
- install.py   安装目录
- traffic.py   红绿灯模拟
- tickets.py   工单系统
- batch.py     批量生成
- fault.py     故障注入
- files.py     文件管理
- visualization.py 可视化
- websocket.py WebSocket
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 API 路由模块
包含所有后端 REST API 和 WebSocket 路由

后续可按业务领域进一步拆分为：
- auth.py      认证相关
- admin.py     管理员后台
- system.py    系统管理
- docker.py    Docker 容器
- ros2.py      ROS2 功能
- scripts.py   脚本管理
- install.py   安装目录
- traffic.py   红绿灯模拟
- tickets.py   工单系统
- batch.py     批量生成
- fault.py     故障注入
- files.py     文件管理
- visualization.py 可视化
- websocket.py WebSocket
"""

import os
import sys
import json
import time
import uuid
import re
import glob
import shutil
import subprocess
import shlex
import threading
import asyncio
import tempfile
import hashlib
import hmac
import secrets
import zipfile
import tarfile
import pwd
import socket
import psutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from collections import OrderedDict

import docker
import jwt
from dotenv import load_dotenv
from fastapi import (
    APIRouter, WebSocket, WebSocketDisconnect, HTTPException,
    Depends, Request, status, Body, UploadFile, File, Form, Query
)
from fastapi.responses import JSONResponse, FileResponse, Response, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from supabase import create_client, Client

from logger import logger
from core.config import save_config
from core.constants import (
    CONFIG, PORT, HOST, ROS2_DEFAULT, INSTALL_DIR, SETUP_BASH, LAUNCH_DIR,
    DOCKER_PREFIX, USE_SUDO, WHITELIST_FILE, DEFAULT_WHITELIST,
    CORS_ALLOWED_ORIGINS, VISUALIZATION_CONFIG, DEFAULT_VISUALIZATION_METHOD,
    VISUALIZATION_METHODS, PLUGIN_EXECUTION_ENABLED, ALL_PANELS,
    DB_TYPE, DB_PATH, AUDIT_DB_PATH, AUDIT_ENABLED, AUDIT_LOG_FILE,
    ws_clients, traffic_sender, timer_traffic_sender, manual_timer_traffic_sender,
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, BCRYPT_ROUNDS,
    RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD,
    INPUT_FILTER_ENABLED, INPUT_FILTER_WHITELIST, ROS2_WS,
    DEFAULT_RESET_PASSWORD,
)
from core.security import (
    hash_password, verify_password, create_jwt_token, decode_jwt_token,
    sanitize_command, limiter
)
from core.utils import (
    run_ros2_cmd, run_ros2_cmd_in_container, load_whitelist, parse_size,
    get_used_ports, find_free_port, build_dir_tree, extract_and_flatten,
    _safe_copy2, _normalize_rviz_config, _resolve_rviz_config, _maximize_rviz,
    error_response, generate_username_from_email, broadcast_log, generate_files,
    extract_versioned_install, _prune_backups
)
from core.workspace import (
    validate_user_path, get_user_workspace_paths, create_user_workspace,
    list_user_versions, resolve_versioned_install, is_valid_version_name,
    sanitize_version_name, get_admin_install_dir, VERSION_RESERVED_NAMES,
    list_version_backups, queue_version_size_computation, invalidate_version_size_cache,
    is_version_backup_entry
)
from core.cache import SimpleCache, _memory_cache
from database import db
from deps import get_current_user, require_admin, require_permission, security
from models import LoginRequest, RegisterRequest
from services.system_monitor import SystemMonitor
from services.docker_manager import DockerManager
from services.script_generator import ROS2ScriptGenerator
from services.system_utils import SystemUtils
from services.traffic_light import TrafficLightSender, TimerTrafficLightSender, ManualTimerTrafficLightSender

# ---------- 初始化全局服务实例 ----------
script_generator = None
system_monitor = None

router = APIRouter()

# ---------- GPU 详细监控 ----------
@router.get("/api/system/monitor/gpu-detail")
async def gpu_detail(current_user: dict = Depends(require_permission('docker'))):
    """获取 GPU 详细监控信息（PCIe/显存/进程）"""
    try:
        gpu_info = []
        pcie_cmd = ["nvidia-smi", "--query-gpu=index,pcie.link.gen.current,pcie.link.width.current,pcie.link.gen.max,pcie.link.width.max", "--format=csv,noheader"]
        pcie_result = subprocess.run(pcie_cmd, capture_output=True, text=True, timeout=2)
        pcie_map = {}
        if pcie_result.returncode == 0:
            for line in pcie_result.stdout.strip().split("\n"):
                if line.strip():
                    parts = [x.strip() for x in line.split(", ")]
                    if len(parts) >= 5:
                        pcie_map[parts[0]] = {"current_gen": parts[1], "current_width": parts[2], "max_gen": parts[3], "max_width": parts[4]}
        pmon_cmd = ["nvidia-smi", "pmon", "-c", "1", "-s", "um"]
        pmon_result = subprocess.run(pmon_cmd, capture_output=True, text=True, timeout=3)
        pmon_data = []
        if pmon_result.returncode == 0:
            for line in pmon_result.stdout.strip().split("\n")[2:]:
                if line.strip() and not line.startswith("#"):
                    parts = line.split()
                    if len(parts) >= 5:
                        pmon_data.append({"gpu": parts[0], "pid": parts[1], "type": parts[2], "sm": parts[3], "mem": parts[4]})
        gpu_cmd = ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,clocks.sm,clocks.mem", "--format=csv,noheader,nounits"]
        gpu_result = subprocess.run(gpu_cmd, capture_output=True, text=True, timeout=2)
        if gpu_result.returncode == 0:
            for line in gpu_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [x.strip() for x in line.split(", ")]
                if len(parts) >= 11:
                    idx = parts[0]
                    mem_total = int(parts[3]) if parts[3].isdigit() else 0
                    mem_used = int(parts[4]) if parts[4].isdigit() else 0
                    mem_bw_pct = round((mem_used / mem_total * 100), 1) if mem_total > 0 else 0
                    gpu_info.append({
                        "index": idx,
                        "name": parts[1],
                        "utilization": parts[2],
                        "mem_total": mem_total,
                        "mem_used": mem_used,
                        "mem_free": parts[5],
                        "mem_bw_percent": mem_bw_pct,
                        "temperature": parts[6],
                        "power_draw": parts[7],
                        "power_limit": parts[8],
                        "sm_clock": parts[9],
                        "mem_clock": parts[10],
                        "pcie": pcie_map.get(idx, {}),
                        "processes": [p for p in pmon_data if p["gpu"] == idx]
                    })
        proc_cmd = ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory,gpu_uuid", "--format=csv,noheader"]
        proc_result = subprocess.run(proc_cmd, capture_output=True, text=True, timeout=2)
        gpu_procs = []
        if proc_result.returncode == 0:
            uuid_cmd = ["nvidia-smi", "--query-gpu=uuid,index", "--format=csv,noheader"]
            uuid_result = subprocess.run(uuid_cmd, capture_output=True, text=True, timeout=2)
            uuid_to_index = {}
            for line in uuid_result.stdout.strip().split("\n"):
                if line.strip():
                    p = line.split(", ")
                    if len(p) == 2:
                        uuid_to_index[p[0].strip()] = p[1].strip()
            for line in proc_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                p = line.split(", ")
                if len(p) >= 3:
                    gpu_procs.append({"gpu_index": uuid_to_index.get(p[2].strip() if len(p) >= 4 else "", "?"), "pid": p[0], "name": p[1], "used_memory": p[2] if len(p) == 3 else p[2] if len(p) >= 3 else ""})
        return {"success": True, "gpu": gpu_info, "gpu_processes": gpu_procs, "pmon": pmon_data}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 系统自检 ----------
@router.get("/api/system/check")
async def system_check(current_user: dict = Depends(require_admin)):
    """系统自检（目录/服务/配置完整性）"""
    checks = []
    config_dir = ROS2_DEFAULT.get("config_dir", os.path.expanduser("~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config"))
    checks.append({"name": "ROS2 Install 目录", "path": INSTALL_DIR, "ok": os.path.exists(INSTALL_DIR), "fixable": False})
    checks.append({"name": "Setup.bash", "path": SETUP_BASH, "ok": os.path.exists(SETUP_BASH), "fixable": False})
    checks.append({"name": "配置目录", "path": config_dir, "ok": os.path.isdir(config_dir), "fixable": False})
    checks.append({"name": "Launch 目录", "path": LAUNCH_DIR, "ok": os.path.isdir(LAUNCH_DIR), "fixable": False})
    scripts_dir = ROS2_DEFAULT.get("scripts_dir", "")
    checks.append({"name": "脚本目录", "path": scripts_dir, "ok": os.path.isdir(scripts_dir), "fixable": True, "fix_action": "mkdir"})
    logs_dir = ROS2_DEFAULT.get("logs_dir", "")
    checks.append({"name": "日志目录", "path": logs_dir, "ok": os.path.isdir(logs_dir), "fixable": True, "fix_action": "mkdir"})
    yaml_files = []
    if os.path.isdir(config_dir):
        yaml_files = glob.glob(os.path.join(config_dir, "*.yaml")) + glob.glob(os.path.join(config_dir, "*.yml"))
    checks.append({"name": "YAML 配置文件", "count": len(yaml_files), "ok": len(yaml_files) > 0, "fixable": False})
    docker_ok = False
    try:
        client = docker.from_env()
        client.ping()
        docker_ok = True
    except:
        pass
    checks.append({"name": "Docker 服务", "ok": docker_ok, "fixable": False})
    whitelist = load_whitelist()
    checks.append({"name": "白名单配置", "ok": len(whitelist) > 0, "detail": whitelist, "fixable": False})
    all_ok = all(c["ok"] for c in checks)
    return {"success": True, "all_ok": all_ok, "checks": checks}

@router.post("/api/system/check/fix")
async def system_check_fix(data: Dict[str, str], current_user: dict = Depends(require_admin)):
    """修复自检发现的问题（创建缺失目录）"""
    item = data.get("item", "")
    if item in ("脚本目录", "日志目录"):
        if item == "脚本目录":
            target = ROS2_DEFAULT.get("scripts_dir", "")
        else:
            target = ROS2_DEFAULT.get("logs_dir", "")
        if target:
            os.makedirs(target, exist_ok=True)
            db.add_audit_log(current_user["username"], "system_check_fix", item)
            return {"success": True, "message": f"已创建目录: {target}"}
    return {"success": False, "message": "无法修复该项"}

# ---------- 资源泄漏监控 ----------
@router.get("/api/system/resource-leaks")
async def resource_leaks(current_user: dict = Depends(require_admin)):
    """检查资源泄漏（线程/内存/文件描述符）"""
    try:
        import threading
        active_threads = threading.active_count()
        thread_names = [t.name for t in threading.enumerate()]
        ws_count = len(ws_clients)
        process = psutil.Process()
        mem_info = process.memory_info()
        open_files = process.open_files()
        return {
            "success": True,
            "active_threads": active_threads,
            "thread_names": thread_names[:50],
            "websocket_clients": ws_count,
            "memory_rss_mb": round(mem_info.rss / 1024 / 1024, 2),
            "memory_vms_mb": round(mem_info.vms / 1024 / 1024, 2),
            "open_files_count": len(open_files),
            "cpu_percent": process.cpu_percent(interval=0.1)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

