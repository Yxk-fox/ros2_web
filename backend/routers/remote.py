#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""远程主机 / 插件系统 / 辅助测试工具"""

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

# ---------- 远程主机管理 ----------
REMOTE_HOSTS_FILE = os.path.expanduser("~/.ros2_docker_manager_remote_hosts.json")

@router.get("/api/system/remote-hosts")
async def get_remote_hosts(current_user: dict = Depends(require_admin)):
    """获取远程主机列表"""
    try:
        if os.path.exists(REMOTE_HOSTS_FILE):
            with open(REMOTE_HOSTS_FILE, 'r') as f:
                hosts = json.load(f)
            return {"success": True, "hosts": hosts}
        return {"success": True, "hosts": []}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/remote-hosts")
async def add_remote_host(data: Dict[str, str], current_user: dict = Depends(require_admin)):
    """添加远程主机"""
    name = data.get("name", "")
    host = data.get("host", "")
    port = data.get("port", "22")
    user = data.get("user", "root")
    auth_type = data.get("auth_type", "password")
    auth_value = data.get("auth_value", "")
    if not name or not host:
        raise HTTPException(400, "缺少名称或主机地址")
    host_entry = {
        "name": name, "host": host, "port": port, "user": user,
        "auth_type": auth_type, "auth_value": auth_value,
        "added_at": datetime.now().isoformat()
    }
    try:
        hosts = []
        if os.path.exists(REMOTE_HOSTS_FILE):
            with open(REMOTE_HOSTS_FILE, 'r') as f:
                hosts = json.load(f)
        hosts = [h for h in hosts if h.get("name") != name]
        hosts.append(host_entry)
        with open(REMOTE_HOSTS_FILE, 'w') as f:
            json.dump(hosts, f, indent=2, ensure_ascii=False)
        db.add_audit_log(current_user["username"], "add_remote_host", name)
        return {"success": True, "hosts": hosts, "message": f"已添加主机: {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/system/remote-hosts/{name}")
async def remove_remote_host(name: str, current_user: dict = Depends(require_admin)):
    """移除远程主机"""
    try:
        if os.path.exists(REMOTE_HOSTS_FILE):
            with open(REMOTE_HOSTS_FILE, 'r') as f:
                hosts = json.load(f)
            hosts = [h for h in hosts if h.get("name") != name]
            with open(REMOTE_HOSTS_FILE, 'w') as f:
                json.dump(hosts, f, indent=2, ensure_ascii=False)
            db.add_audit_log(current_user["username"], "remove_remote_host", name)
            return {"success": True, "hosts": hosts, "message": f"已移除主机: {name}"}
        return {"success": False, "error": "主机列表为空"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/remote-hosts/{name}/test")
async def test_remote_host(name: str, current_user: dict = Depends(require_admin)):
    """测试远程主机连接"""
    try:
        if not os.path.exists(REMOTE_HOSTS_FILE):
            return {"success": False, "error": "主机列表不存在"}
        with open(REMOTE_HOSTS_FILE, 'r') as f:
            hosts = json.load(f)
        host_info = None
        for h in hosts:
            if h.get("name") == name:
                host_info = h
                break
        if not host_info:
            return {"success": False, "error": "主机不存在"}
        host = host_info["host"]
        rc, out, err = DockerManager.run_cmd(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", f"{host_info['user']}@{host}", "docker ps"], timeout=10)
        db.add_audit_log(current_user["username"], "test_remote_host", name)
        return {"success": rc == 0, "stdout": out, "stderr": err}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 插件系统 ----------
PLUGINS_DIR = os.path.expanduser("~/.ros2_docker_manager_plugins")
PLUGIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def validate_plugin_name(name: str) -> str:
    """校验插件名称，防止目录穿越和非法文件名。"""
    if not name or not PLUGIN_NAME_PATTERN.fullmatch(name):
        raise HTTPException(400, "插件名称仅允许 1-64 位字母、数字、下划线和短横线")
    return name

def get_plugin_path(name: str) -> str:
    """根据安全插件名称生成插件文件路径。"""
    safe_name = validate_plugin_name(name)
    base_dir = os.path.abspath(os.path.expanduser(PLUGINS_DIR))
    plugin_path = os.path.abspath(os.path.join(base_dir, f"{safe_name}.py"))
    if not plugin_path.startswith(base_dir + os.sep):
        raise HTTPException(400, "非法插件路径")
    return plugin_path

@router.get("/api/system/plugins")
async def list_plugins(current_user: dict = Depends(require_admin)):
    """列出已安装的插件"""
    try:
        os.makedirs(PLUGINS_DIR, exist_ok=True)
        plugins = []
        for f in os.listdir(PLUGINS_DIR):
            if f.endswith('.py') and not f.startswith('_'):
                plugin_path = os.path.join(PLUGINS_DIR, f)
                with open(plugin_path, 'r') as pf:
                    first_line = pf.readline().strip()
                desc = first_line.replace('#', '').strip() if first_line.startswith('#') else "无描述"
                plugins.append({"name": f[:-3], "file": f, "description": desc, "path": plugin_path})
        return {"success": True, "plugins": plugins, "plugins_dir": PLUGINS_DIR}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/plugins")
async def create_plugin(data: Dict[str, str], current_user: dict = Depends(require_admin)):
    """创建新插件"""
    name = validate_plugin_name(data.get("name", ""))
    code = data.get("code", "")
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    plugin_path = get_plugin_path(name)
    try:
        with open(plugin_path, 'w') as f:
            f.write(code or f"# 插件: {name}\ndef run(config):\n    print(f'插件 {name} 已执行')\n    return True\n")
        db.add_audit_log(current_user["username"], "create_plugin", name)
        return {"success": True, "message": f"已创建插件: {name}", "path": plugin_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/system/plugins/{name}")
async def delete_plugin(name: str, current_user: dict = Depends(require_admin)):
    """删除插件"""
    plugin_path = get_plugin_path(name)
    if not os.path.isfile(plugin_path):
        raise HTTPException(404, "插件不存在")
    try:
        os.remove(plugin_path)
        db.add_audit_log(current_user["username"], "delete_plugin", name)
        return {"success": True, "message": f"已删除插件: {name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/plugins/{name}/execute")
async def execute_plugin(name: str, data: Dict[str, Any] = None, current_user: dict = Depends(require_admin)):
    """执行插件（需在配置中启用）"""
    if not PLUGIN_EXECUTION_ENABLED:
        raise HTTPException(403, "插件执行默认关闭，请在 config.json 中显式启用 plugins.execution_enabled")
    plugin_path = get_plugin_path(name)
    if not os.path.isfile(plugin_path):
        raise HTTPException(404, "插件不存在")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, 'run'):
            result = module.run(data or {})
            db.add_audit_log(current_user["username"], "execute_plugin", name)
            return {"success": True, "result": str(result)}
        return {"success": False, "error": "插件未定义 run 函数"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 辅助测试工具 ----------
MOCK_TOOLS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ck", "mock_tools.py")

@router.get("/api/system/mock-tools/info")
async def mock_tools_info(current_user: dict = Depends(require_admin)):
    """获取辅助测试工具信息"""
    exists = os.path.isfile(MOCK_TOOLS_PATH)
    tools = [
        {"name": "Chair 座椅控制", "icon": "🪑", "color": "#4A90D9", "desc": "座椅控制 / 附件 / 车况回显"},
        {"name": "V2E 控车", "icon": "🚜", "color": "#27ae60", "desc": "行走 / 举升 / 位置调整"},
        {"name": "故障模拟", "icon": "⚠️", "color": "#e67e22", "desc": "change_status / mock_status"},
        {"name": "交通灯控制", "icon": "🚦", "color": "#8e44ad", "desc": "手动 / 计时 · 多灯独立"},
        {"name": "地图工具", "icon": "🗺️", "color": "#16a085", "desc": "bag 分析 / map 格式转换"},
        {"name": "仿真测试", "icon": "🧪", "color": "#c0392b", "desc": "单案例 / 批量 / 容器会话"},
        {"name": "Orin 烧录", "icon": "💾", "color": "#7f8c8d", "desc": "镜像扫描 / 整机烧录"},
        {"name": "网络工具", "icon": "🌐", "color": "#2980b9", "desc": "tc 延迟注入 / 清理"},
        {"name": "云平台工具", "icon": "☁️", "color": "#d35400", "desc": "UDP 灯态 / MQTT / TCP"},
        {"name": "目标点更新", "icon": "📍", "color": "#34495e", "desc": "dump_goal 坐标平移"},
    ]
    return {"success": True, "exists": exists, "path": MOCK_TOOLS_PATH, "tools": tools}

@router.post("/api/system/mock-tools/launch")
async def launch_mock_tools(current_user: dict = Depends(require_admin)):
    """启动辅助测试工具桌面应用"""
    if not os.path.isfile(MOCK_TOOLS_PATH):
        return {"success": False, "error": f"文件不存在: {MOCK_TOOLS_PATH}"}
    try:
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":0")
        subprocess.Popen(
            ["python3", MOCK_TOOLS_PATH],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        db.add_audit_log(current_user["username"], "launch_mock_tools", MOCK_TOOLS_PATH)
        return {"success": True, "message": "辅助测试工具已启动（桌面窗口）"}
    except Exception as e:
        return {"success": False, "error": str(e)}

