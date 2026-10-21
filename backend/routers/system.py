#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统状态监控 / 系统工具"""

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

# ---------- 系统状态与监控 ----------
@router.get("/api/system/ping")
def system_ping():
    """健康探测端点（无鉴权、无限流）

    供 deploy.py 部署后健康检查 / 外部监控探活使用，
    仅返回进程存活信号与轻量运行信息，不做任何 IO 操作。
    """
    return {
        "success": True,
        "status": "ok",
        "timestamp": time.time(),
        "uptime": time.time() - psutil.Process().create_time(),
    }

@router.get("/api/system/status")
def system_status(current_user: dict = Depends(get_current_user)):
    """获取系统状态（ROS2/Docker/目录）

    ★ 性能优化：同步 def —— FastAPI 放入线程池执行，docker ping 不再阻塞事件循环
    """
    docker_ok = False
    try:
        import docker
        client = docker.from_env()
        client.ping()
        docker_ok = True
    except Exception:
        docker_ok = False
    return {
        "success": True,
        "ros2_available": os.path.exists(SETUP_BASH),
        "docker_available": docker_ok,
        "install_dir_exists": os.path.exists(INSTALL_DIR),
        "ros2_ws": ROS2_WS,
        "install_dir": INSTALL_DIR,
    }

@router.post("/api/system/restart")
async def restart_service(current_user: dict = Depends(require_admin)):
    """重启 Web 服务（仅管理员）"""
    db.add_audit_log(current_user["username"], "restart_service", "重启 Web 服务")
    try:
        import threading
        def _restart():
            time.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        threading.Thread(target=_restart, daemon=True).start()
        return {"success": True, "message": "服务正在重启..."}
    except Exception as e:
        raise HTTPException(500, f"重启失败: {e}")

@router.post("/api/system/settings")
async def save_system_settings(data: Dict[str, Any], current_user: dict = Depends(require_admin)):
    """保存系统设置（仅管理员）"""
    key = data.get("key")
    value = data.get("value")
    if not key:
        raise HTTPException(400, "缺少 key 参数")
    db.set_config(key, value)
    db.add_audit_log(current_user["username"], "save_settings", f"保存设置: {key}")
    return {"success": True, "message": "配置保存成功"}

@router.get("/api/system/settings")
async def get_system_settings(current_user: dict = Depends(get_current_user)):
    """获取系统设置"""
    return {"success": True, "settings": {}}

@router.get("/api/system/monitor")
def system_monitor(current_user: dict = Depends(require_permission('docker'))):
    """获取系统监控数据（CPU/内存/GPU/进程）

    ★ 性能优化：同步 def —— nvidia-smi/psutil 等阻塞调用放入线程池（前端每3s轮询）
    """
    try:
        sys_text, proc_data, gpu_proc_data = SystemMonitor.get_system_status()
        cpu_total = 0.0
        mem_percent = 0.0
        swap_percent = 0.0
        load_avg = [0,0,0]
        for line in sys_text.split('\n'):
            if "CPU 整体使用率" in line:
                cpu_total = float(re.search(r'(\d+\.?\d*)%', line).group(1))
            if "内存:" in line:
                mem_percent = float(re.search(r'(\d+\.?\d*)%', line).group(1))
            if "Swap:" in line:
                swap_percent = float(re.search(r'(\d+\.?\d*)%', line).group(1))
            if "平均负载" in line:
                nums = re.findall(r'(\d+\.?\d*)', line)
                if len(nums)>=3:
                    load_avg = [float(n) for n in nums[:3]]
        mem_info = psutil.virtual_memory()
        swap_info = psutil.swap_memory()
        cpu_per_core = psutil.cpu_percent(percpu=True)
        gpu_info = []
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                gpu_lines = result.stdout.strip().split("\n")
                for line in gpu_lines:
                    if not line.strip():
                        continue
                    parts = [x.strip() for x in line.split(", ")]
                    if len(parts) >= 10:
                        idx, name, driver, gpu_util, mem_total, mem_used, mem_free, temp, power_draw, power_limit = parts[:10]
                        gpu_info.append({
                            "index": idx,
                            "name": name,
                            "utilization": gpu_util,
                            "mem_used": mem_used,
                            "mem_total": mem_total,
                            "temperature": temp,
                            "power": power_draw
                        })
            else:
                logger.warning("nvidia-smi 查询失败或未安装")
        except Exception as e:
            logger.warning(f"获取 GPU 信息异常: {e}")
        processes = []
        for pid, user, cpu_pct, mem_pct, cmd in proc_data:
            processes.append({"pid": pid, "user": user, "cpu": cpu_pct, "mem": mem_pct, "command": cmd})
        return {
            "success": True,
            "cpu": {
                "total": cpu_total,
                "cores": len(cpu_per_core),
                "load_avg": load_avg,
                "per_core": cpu_per_core
            },
            "memory": {
                "percent": mem_percent,
                "used_mb": mem_info.used // 1024**2,
                "total_mb": mem_info.total // 1024**2
            },
            "swap": {
                "percent": swap_percent,
                "used_mb": swap_info.used // 1024**2,
                "total_mb": swap_info.total // 1024**2
            },
            "gpu": gpu_info,
            "processes": processes
        }
    except Exception as e:
        logger.error(f"系统监控获取失败: {e}", exc_info=True)
        return {"success": False, "error": f"监控获取失败: {str(e)}"}

@router.get("/api/system/metrics/history")
def metrics_history(
    metric: str = "cpu",
    range_: str = Query("1h", alias="range"),
    current_user: dict = Depends(require_permission('docker')),
):
    """查询资源监控历史曲线（T-5.2-03，v5.2）

    参数：
      metric  指标名：cpu/mem/mem_used/swap/load/gpu_util/gpu_mem/gpu_temp/
              container_count/container_cpu/container_mem
      range   范围档位：1h/6h/24h/7d（对应 30s 原始粒度与 5min/15min/1h 聚合桶）

    ★ 同步 def —— SQLite 查询放入线程池
    """
    from services.metrics_history import (
        query_history as query_metrics_history, METRIC_COLUMNS, RANGE_CONFIG
    )
    try:
        points = query_metrics_history(metric, range_)
        return {
            "success": True,
            "metric": metric,
            "range": range_,
            "points": points,
            "available_metrics": sorted(METRIC_COLUMNS.keys()),
            "available_ranges": sorted(RANGE_CONFIG.keys()),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"历史曲线查询失败: {e}", exc_info=True)
        return {"success": False, "error": f"历史曲线查询失败: {str(e)}"}

# ---------- 系统工具 ----------
@router.post("/api/system/apt-source")
async def change_source(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """切换 apt 软件源"""
    source = data.get("source")
    source_map = {
        "aliyun": "mirrors.aliyun.com",
        "tsinghua": "mirrors.tuna.tsinghua.edu.cn",
        "ustc": "mirrors.ustc.edu.cn",
        "163": "mirrors.163.com",
        "huawei": "mirrors.huaweicloud.com"
    }
    url = source_map.get(source)
    if not url:
        raise HTTPException(400, "无效源")
    ok, msg = SystemUtils.change_software_source(url)
    db.add_audit_log(current_user["username"], "change_source", f"切换到 {source}")
    return {"success": ok, "message": msg}

@router.post("/api/system/install")
async def install_pkg(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """安装 apt 软件包"""
    pkg = data.get("package")
    if not pkg:
        raise HTTPException(400, "缺少包名")
    ok, msg = SystemUtils.install_package(pkg)
    db.add_audit_log(current_user["username"], "install_pkg", pkg)
    return {"success": ok, "message": msg}

@router.post("/api/system/uninstall")
async def uninstall_pkg(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """卸载 apt 软件包"""
    pkg = data.get("package")
    if not pkg:
        raise HTTPException(400, "缺少包名")
    ok, msg = SystemUtils.uninstall_package(pkg)
    db.add_audit_log(current_user["username"], "uninstall_pkg", pkg)
    return {"success": ok, "message": msg}

@router.post("/api/system/certificates")
async def switch_cert(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """切换证书和云环境配置

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间操作。
    v3.7：普通用户若无 Docker/bk 证书目录，自动从管理员空间拷贝。
    """
    env = data.get("env")
    target_user = data.get("target_user")
    admin_bk = os.path.expanduser("~/robotruck_ros2/Docker/bk")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    user_bk = workspace_paths["backup_dir"]
    # 普通用户：优先从自己的 bk 取证书，若不存在则从管理员空间拷贝
    src_dir = os.path.join(user_bk, f"{env}证书")
    if not os.path.isdir(src_dir):
        # 用户 bk 中没有该证书目录，从管理员空间拷贝整个 bk
        if os.path.isdir(admin_bk) and admin_bk != user_bk:
            os.makedirs(user_bk, exist_ok=True)
            for item in os.listdir(admin_bk):
                src_item = os.path.join(admin_bk, item)
                dst_item = os.path.join(user_bk, item)
                if os.path.isdir(src_item):
                    if not os.path.exists(dst_item):
                        shutil.copytree(src_item, dst_item)
                else:
                    if not os.path.exists(dst_item):
                        shutil.copy2(src_item, dst_item)
            logger.info(f"已从管理员空间拷贝 bk 到用户空间: {user_bk}")
        src_dir = os.path.join(admin_bk, f"{env}证书")
    dst_dir = os.path.join(workspace_paths["host_install"], "simulation_launches", "share", "simulation_launches", "config")
    if not os.path.isdir(src_dir):
        return {"success": False, "message": f"源目录不存在: {src_dir}"}
    os.makedirs(dst_dir, exist_ok=True)
    ok, msg = SystemUtils.copy_certificates(src_dir, dst_dir)
    if ok:
        target_ip = CONFIG["cloud_env"]["ip_map"].get(env, "")
        if target_ip:
            SystemUtils.switch_cloud_config(dst_dir, target_ip)
        CONFIG["cloud_env"]["current_env"] = env
        CONFIG["cloud_env"]["current_ip"] = target_ip
        save_config(CONFIG)
    db.add_audit_log(current_user["username"], "switch_cert",
                     f"切换到 {env} 证书 target={workspace_paths.get('target_user') or 'self'}")
    return {"success": ok, "message": msg, "target_user": workspace_paths.get("target_user")}

@router.post("/api/system/sync")
async def sync_folder(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """处理 sync_folder 相关逻辑。支持单个或多个文件夹同步（逗号分隔）

    v3.6：管理员可通过 body 中的 ``target_user`` 切换到目标用户工作空间。
    """
    sync_type = data.get("type")
    if not sync_type:
        raise HTTPException(400, "缺少 type 参数")
    types = sync_type.split(',')
    try:
        # ★★★ bug4修复：普通用户从自己的bk同步，control_launch从管理员bk同步 ★★★
        # v3.6: 管理员可指定 target_user 切换到目标用户空间
        target_user = data.get("target_user")
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        user_install = workspace_paths["host_install"]
        user_bk = workspace_paths["backup_dir"]
        admin_bk = os.path.expanduser("~/robotruck_ros2/Docker/bk")

        results = []
        for t in types:
            t = t.strip()
            if t == "mock_truck":
                # 普通用户从自己的bk同步；管理员从管理员bk同步
                src = os.path.join(user_bk, "mock_truck")
                dst = os.path.join(user_install, "mock_truck", "share", "mock_truck")
            elif t == "simulation_launches":
                # 普通用户从自己的bk同步；管理员从管理员bk同步
                src = os.path.join(user_bk, "simulation_launches")
                dst = os.path.join(user_install, "simulation_launches", "share", "simulation_launches")
            elif t == "control_launch":
                # control_launch.py 始终从管理员bk同步
                src = os.path.join(admin_bk, "pp_controller", "launch", "control_launch.py")
                dst = os.path.join(user_install, "pp_controller", "share", "pp_controller", "launch", "control_launch.py")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                ok, msg = SystemUtils.sync_file(src, dst)
                results.append({"type": t, "success": ok, "message": msg})
                if ok:
                    db.add_audit_log(current_user["username"], "sync_folder", f"{t} target={workspace_paths.get('target_user') or 'self'}")
                continue
            else:
                raise HTTPException(400, f"未知同步类型: {t}")
            ok, msg = SystemUtils.sync_folder(src, dst)
            results.append({"type": t, "success": ok, "message": msg})
            if ok and t == "simulation_launches":
                config_dir = os.path.join(dst, "config")
                actual_ip = SystemUtils.get_cloud_ip_from_yaml(config_dir)
                if actual_ip:
                    CONFIG["cloud_env"]["current_ip"] = actual_ip
                    matched_env = None
                    for env_name, env_ip in CONFIG["cloud_env"]["ip_map"].items():
                        if env_ip == actual_ip:
                            matched_env = env_name
                            break
                    if matched_env:
                        CONFIG["cloud_env"]["current_env"] = matched_env
                    save_config(CONFIG)
            if ok:
                db.add_audit_log(current_user["username"], "sync_folder", f"{t} target={workspace_paths.get('target_user') or 'self'}")

        all_ok = all(r["success"] for r in results)
        messages = [r["message"] for r in results]
        return {"success": all_ok, "message": "\n".join(messages), "target_user": workspace_paths.get("target_user")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"sync_folder 失败: {e}", exc_info=True)
        return {"success": False, "error": f"同步失败: {str(e)}"}

@router.post("/api/system/cloud-config")
async def switch_cloud_ip(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """切换云平台 IP 地址

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间操作。
    v3.7：普通用户若无 Docker 目录结构，自动从管理员空间拷贝。
    """
    new_ip = data.get("ip")
    if not new_ip:
        raise HTTPException(400, "缺少IP")
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    # 普通用户：确保 Docker 目录结构存在（bags/logs/bk），不存在则从管理员空间拷贝
    user_docker_dir = os.path.join(workspace_paths["host_ws"], "Docker")
    admin_docker_dir = os.path.expanduser("~/robotruck_ros2/Docker")
    if user_docker_dir != admin_docker_dir:
        for subdir in ["bags", "logs", "bk"]:
            user_subdir = os.path.join(user_docker_dir, subdir)
            if not os.path.isdir(user_subdir):
                admin_subdir = os.path.join(admin_docker_dir, subdir)
                if os.path.isdir(admin_subdir):
                    shutil.copytree(admin_subdir, user_subdir)
                    logger.info(f"已从管理员空间拷贝 {subdir} 到用户空间: {user_subdir}")
    config_dir = os.path.join(workspace_paths["host_install"], "simulation_launches", "share", "simulation_launches", "config")
    if not os.path.isdir(config_dir):
        os.makedirs(config_dir, exist_ok=True)
    ok, msg = SystemUtils.switch_cloud_config(config_dir, new_ip)
    if ok:
        CONFIG["cloud_env"]["current_ip"] = new_ip
        for env, ip in CONFIG["cloud_env"]["ip_map"].items():
            if ip == new_ip:
                CONFIG["cloud_env"]["current_env"] = env
                break
        save_config(CONFIG)
    db.add_audit_log(current_user["username"], "switch_cloud_ip",
                     f"ip={new_ip} target={workspace_paths.get('target_user') or 'self'}")
    return {"success": ok, "message": msg, "target_user": workspace_paths.get("target_user")}

@router.post("/api/system/clean")
async def clean_dir(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """清空指定目录（bags/logs）

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间操作。
    """
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    dir_type = data.get("type")
    if dir_type == "bags":
        path = workspace_paths["bag_storage"]
    elif dir_type == "logs":
        path = workspace_paths["logs_dir"]
    else:
        raise HTTPException(400, "未知目录类型")
    validate_user_path(path, current_user)
    ok, msg = SystemUtils.clean_directory(path)
    db.add_audit_log(current_user["username"], "clean_dir",
                     f"{dir_type} target={workspace_paths.get('target_user') or 'self'}")
    return {"success": ok, "message": msg, "target_user": workspace_paths.get("target_user")}

@router.post("/api/system/open-folder")
async def open_folder(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """获取目录路径

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间。
    """
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    folder_type = data.get("type")
    if folder_type == "bags":
        path = workspace_paths["bag_storage"]
    elif folder_type == "logs":
        path = workspace_paths["logs_dir"]
    else:
        raise HTTPException(400, "未知类型")
    validate_user_path(path, current_user)
    if not os.path.isdir(path):
        raise HTTPException(404, f"目录不存在: {path}")
    return {"success": True, "path": path}


