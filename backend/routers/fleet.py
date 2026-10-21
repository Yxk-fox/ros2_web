#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量生成车辆 / Truck 配置 / 白名单"""

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

# ---------- 批量生成车辆 ----------
@router.post("/api/batch/generate")
async def batch_generate(data: Dict[str, str], current_user: dict = Depends(require_permission('tools'))):
    """批量生成车辆配置文件"""
    identifier = data.get("identifier")
    if not identifier:
        raise HTTPException(400, "缺少标识")
    logs: List[str] = []
    def log_cb(msg):
        """日志回调函数"""
        logs.append(msg)
    try:
        # ★★★ bug4修复：普通用户从自己的bk读取模板，合并复制到自己的install（不删除其他文件） ★★★
        workspace_paths = get_user_workspace_paths(current_user)
        user_bk = workspace_paths["backup_dir"]
        admin_bk = os.path.expanduser("~/robotruck_ros2/Docker/bk")
        if current_user.get("role") == "admin":
            # 管理员：从bk读取模板，生成到bk（保持原逻辑）
            root_dir = admin_bk
            sim_dir_override = None
            mock_dir_override = None
        else:
            # 普通用户：从自己的bk读取模板，合并复制到自己的install对应share目录
            # ★★★ bug4修复：使用 dirs_exist_ok=True 合并复制，不删除目标目录中已有的文件 ★★★
            user_install = workspace_paths["host_install"]
            sim_share_dir = os.path.join(user_install, "simulation_launches", "share", "simulation_launches")
            mock_share_dir = os.path.join(user_install, "mock_truck", "share", "mock_truck")
            pp_install_dir = os.path.join(user_install, "pp_controller")

            def _ignore_pycache(dir, files):
                return {'__pycache__', '.git', '.pyc', '.pyo', '.egg-info'}

            # 合并复制bk下的simulation_launches（保留目标中已有的cmake/hook/environment/package.*等文件）
            sim_src = os.path.join(user_bk, "simulation_launches")
            if os.path.isdir(sim_src):
                os.makedirs(sim_share_dir, exist_ok=True)
                shutil.copytree(sim_src, sim_share_dir, dirs_exist_ok=True, ignore=_ignore_pycache)
            else:
                log_cb(f"⚠️ bk 中不存在 simulation_launches 目录: {sim_src}\n")

            # 合并复制bk下的mock_truck
            mock_src = os.path.join(user_bk, "mock_truck")
            if os.path.isdir(mock_src):
                os.makedirs(mock_share_dir, exist_ok=True)
                shutil.copytree(mock_src, mock_share_dir, dirs_exist_ok=True, ignore=_ignore_pycache)
            else:
                log_cb(f"⚠️ bk 中不存在 mock_truck 目录: {mock_src}\n")

            # ★★★ bug3修复：复制完整的pp_controller包（从管理员install），确保ROS2能找到该包 ★★★
            # bk中只有launch/control_launch.py，缺少package.xml和lib，无法作为ROS2包被识别
            # ★★★ bug4修复：使用 dirs_exist_ok=True 合并复制，不删除目标目录中已有的文件 ★★★
            # ★★★ bug5修复：使用 _safe_copy2 作为 copy_function，先 unlink 目标可执行文件再复制，
            #   避免目标 pp_controller 正在被运行中进程执行时触发 ETXTBSY (Errno 26) ★★★
            # v5.0：pp_controller 源改为管理员当前生效版本 install（版本感知）
            admin_pp_src = os.path.join(get_admin_install_dir(), "pp_controller")
            if os.path.isdir(admin_pp_src):
                os.makedirs(pp_install_dir, exist_ok=True)
                shutil.copytree(admin_pp_src, pp_install_dir, dirs_exist_ok=True, ignore=_ignore_pycache, copy_function=_safe_copy2)
                # 用bk中最新的control_launch.py覆盖（bk版本支持多yaml参数）
                bk_launch = os.path.join(admin_bk, "pp_controller", "launch", "control_launch.py")
                user_launch = os.path.join(pp_install_dir, "share", "pp_controller", "launch", "control_launch.py")
                if os.path.isfile(bk_launch):
                    os.makedirs(os.path.dirname(user_launch), exist_ok=True)
                    _safe_copy2(bk_launch, user_launch)

            # 生成时直接使用share目录作为sim_dir和mock_dir
            root_dir = user_install  # 仅占位，实际使用下面的覆盖参数
            sim_dir_override = sim_share_dir
            mock_dir_override = mock_share_dir

        gen_ok = generate_files(root_dir, identifier, log_cb, sim_dir=sim_dir_override, mock_dir=mock_dir_override)
        # generate_files 返回 False 表示缺少模板文件等错误
        if gen_ok is False:
            return {"success": False, "error": "生成失败，请检查日志中的错误信息", "logs": logs}
        # device_sn 直接使用 SN（用户输入即为 SN）
        device_sn = identifier.strip()
        db.add_audit_log(current_user["username"], "batch_generate", f"{identifier} -> {device_sn}")
        return {"success": True, "device_sn": device_sn, "logs": logs}
    except Exception as e:
        logger.error(f"batch_generate 失败: {e}", exc_info=True)
        logs.append(f"✗ 异常: {e}")
        return {"success": False, "error": str(e), "logs": logs}

# ---------- Truck配置管理 ----------
TRUCK_CONFIG_DIR = os.path.expanduser("~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config")
if not os.path.isdir(TRUCK_CONFIG_DIR):
    TRUCK_CONFIG_DIR = os.path.expanduser("~/robotruck_ros2/Docker/bk/simulation_launches/config")

def get_truck_config_dir(current_user: dict):
    """获取当前用户的truck配置目录（普通用户使用自己工作空间）

    v5.0：管理员也走版本感知路径（当前生效版本的 install），
    版本目录不存在时回退旧版 TRUCK_CONFIG_DIR 逻辑（legacy install → bk）。
    """
    workspace_paths = get_user_workspace_paths(current_user)
    vconfig = os.path.join(workspace_paths["host_install"], "simulation_launches", "share", "simulation_launches", "config")
    if os.path.isdir(vconfig):
        return vconfig
    if current_user.get("role") == "admin":
        return TRUCK_CONFIG_DIR
    return vconfig

@router.get("/api/truck/config/list")
def list_truck_configs(current_user: dict = Depends(require_permission('tools'))):
    """列出所有truck*.yaml配置文件

    ★ 性能优化：同步 def —— glob 扫描放入线程池
    """
    try:
        config_dir = get_truck_config_dir(current_user)
        files = glob.glob(os.path.join(config_dir, "truck*.yaml"))
        truck_files = [os.path.basename(f) for f in files if os.path.isfile(f)]
        truck_files.sort()
        return {"success": True, "files": truck_files, "config_dir": config_dir}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/truck/config/{filename}")
def get_truck_config(filename: str, current_user: dict = Depends(require_permission('tools'))):
    """读取truck配置文件中的起点参数"""
    if not filename.startswith("truck") or not filename.endswith(".yaml"):
        raise HTTPException(400, "无效的文件名")
    config_dir = get_truck_config_dir(current_user)
    file_path = os.path.join(config_dir, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "文件不存在")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        start_x_match = re.search(r'start_x:\s*([\d\.\-]+)', content)
        start_y_match = re.search(r'start_y:\s*([\d\.\-]+)', content)
        start_yaw_match = re.search(r'start_yaw:\s*([\d\.\-]+)', content)
        start_z_match = re.search(r'start_z:\s*([\d\.\-]+)', content)
        return {
            "success": True,
            "filename": filename,
            "start_x": float(start_x_match.group(1)) if start_x_match else None,
            "start_y": float(start_y_match.group(1)) if start_y_match else None,
            "start_z": float(start_z_match.group(1)) if start_z_match else None,
            "start_yaw": float(start_yaw_match.group(1)) if start_yaw_match else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.put("/api/truck/config/{filename}")
async def update_truck_config(filename: str, data: Dict[str, float], current_user: dict = Depends(require_permission('tools'))):
    """更新truck配置文件中的起点参数"""
    if not filename.startswith("truck") or not filename.endswith(".yaml"):
        raise HTTPException(400, "无效的文件名")
    config_dir = get_truck_config_dir(current_user)
    file_path = os.path.join(config_dir, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "文件不存在")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if 'start_x' in data:
            content = re.sub(r'start_x:\s*[\d\.\-]+', f'start_x: {data["start_x"]}', content)
        if 'start_y' in data:
            content = re.sub(r'start_y:\s*[\d\.\-]+', f'start_y: {data["start_y"]}', content)
        if 'start_yaw' in data:
            content = re.sub(r'start_yaw:\s*[\d\.\-]+', f'start_yaw: {data["start_yaw"]}', content)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        db.add_audit_log(current_user["username"], "update_truck_config", f"{filename}: {data}")
        return {"success": True, "message": f"已更新 {filename} 的起点参数"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 白名单管理 ----------
@router.get("/api/system/whitelist")
async def get_whitelist(current_user: dict = Depends(require_permission('advanced-docker'))):
    """获取容器名称白名单"""
    try:
        prefixes = load_whitelist()
        return {"success": True, "prefixes": prefixes}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/whitelist")
async def add_whitelist(data: Dict[str, str], current_user: dict = Depends(require_permission('advanced-docker'))):
    """添加白名单前缀"""
    prefix = data.get("prefix", "")
    if not prefix:
        raise HTTPException(400, "缺少前缀")
    try:
        prefixes = load_whitelist()
        if prefix not in prefixes:
            prefixes.append(prefix)
        with open(WHITELIST_FILE, 'w') as f:
            json.dump({"prefixes": prefixes}, f, indent=2)
        db.add_audit_log(current_user["username"], "add_whitelist", prefix)
        return {"success": True, "prefixes": prefixes, "message": f"已添加前缀: {prefix}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/system/whitelist/{prefix}")
async def remove_whitelist(prefix: str, current_user: dict = Depends(require_permission('advanced-docker'))):
    """移除白名单前缀"""
    try:
        prefixes = load_whitelist()
        if prefix in prefixes:
            prefixes.remove(prefix)
        with open(WHITELIST_FILE, 'w') as f:
            json.dump({"prefixes": prefixes}, f, indent=2)
        db.add_audit_log(current_user["username"], "remove_whitelist", prefix)
        return {"success": True, "prefixes": prefixes, "message": f"已移除前缀: {prefix}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

