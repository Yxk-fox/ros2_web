#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 设置 / 帮助文档 / sudo 检查 / 认证加密"""

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

# ---------- API 设置 ----------
APP_SETTINGS_FILE = os.path.expanduser("~/.ros2_docker_manager_settings.json")

@router.get("/api/system/api-settings")
async def get_api_settings(current_user: dict = Depends(require_admin)):
    """获取 API 设置"""
    try:
        if os.path.exists(APP_SETTINGS_FILE):
            with open(APP_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            return {"success": True, "settings": settings}
        return {"success": True, "settings": {"api_enabled": True, "api_port": PORT, "auth_required": False, "auth_token": ""}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/system/api-settings")
async def update_api_settings(data: Dict[str, Any], current_user: dict = Depends(require_admin)):
    """更新 API 设置"""
    try:
        settings = {
            "api_enabled": data.get("api_enabled", True),
            "api_port": data.get("api_port", PORT),
            "auth_required": data.get("auth_required", False),
            "auth_token": data.get("auth_token", "")
        }
        with open(APP_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        db.add_audit_log(current_user["username"], "update_api_settings", "")
        return {"success": True, "settings": settings, "message": "已保存设置"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 帮助文档 ----------
HELP_CONTENT = {
    "welcome": "## 欢迎页面\n\n这是 Mock Truck 的首页，显示系统概览和快速入口。\n\n- **ROS2 状态**: 显示 ROS2 环境是否可用\n- **Docker 状态**: 显示 Docker 服务是否连接\n- **安装目录**: 显示 ROS2 工作空间是否存在",
    "docker": "## 仿真车管理\n\n管理仿真车（Docker 容器）的启动、停止、重启、删除等操作。\n\n1. **选中容器**: 点击「✅ 选中」选择一个运行中的容器，用于 ROS2 功能操作\n2. **日志查看**: 点击「📜 日志」查看容器实时日志\n3. **命令执行**: 点击「💻 命令」在容器内执行命令\n4. **资源调整**: 点击「⚙ 资源」调整容器 CPU 和内存限制\n5. **终端**: 点击「🖥 终端」打开交互式终端",
    "scripts": "## 脚本与启动\n\n扫描 launch 文件并生成 Docker 启动脚本，然后启动仿真车辆。\n\n1. **扫描 Launch 文件**: 点击扫描按钮查看可用的 launch 文件\n2. **配置参数**: 设置 launch 目录、脚本输出目录、日志目录、Docker 镜像等\n3. **生成脚本**: 点击「⚡ 生成 ROS2 脚本」创建启动脚本\n4. **筛选脚本**: 使用筛选框快速查找脚本\n5. **批量操作**: 勾选多个脚本后批量启动\n6. **执行模式**: 选择顺序或并行执行",
    "monitor": "## 系统监控\n\n实时监控系统资源使用情况。\n\n- **CPU 使用率**: 整体和每核心\n- **内存/Swap**: 使用百分比和具体数值\n- **GPU 信息**: 利用率、显存、温度、功耗、PCIe 信息\n- **进程列表**: Top 20 CPU 占用进程\n- **自动刷新**: 点击「⏯ 自动刷新」每 3 秒更新一次",
    "tools": "## 系统工具\n\n提供系统级别的工具功能。\n\n- **一键换源**: 快速切换 apt 软件源\n- **软件安装**: 常用软件一键安装\n- **云配置切换**: 切换证书和云 IP 配置\n- **文件夹同步**: 同步 mock_truck 和 simulation_launches\n- **数据清理**: 清空 Bag 和 Log 目录",
    "simulation": "## 仿真控制\n\n控制 ROS2 仿真车辆。\n\n1. **启动仿真**: 输入 launch 命令并在选中的容器中执行\n2. **速度控制**: 使用摇杆或滑块发送 cmd_vel 速度指令\n3. **话题设置**: 自定义 cmd_vel 话题名称",
    "traffic": "## 红绿灯模拟——交通红绿灯模拟\n\n交通红绿灯模拟器通过 MQTT 接收控制指令，并通过 UDP 上报灯状态到云端。\n\n- 通过 HTTP 登录获取 token\n- 通过 MQTT 订阅灯状态变更指令\n- 通过 UDP 定时上报灯状态\n- 支持自动模式（云端控制）和手动模式（本地控制）\n- 可配置 SN 标识、服务器地址、登录/上报间隔",
    "api-manager": "## REST API 管理\n\n管理系统 REST API 服务，配置端口、认证，并提供 API 文档入口。\n\n### 功能说明\n\n1. **API 配置**\n   - API 端口: 设置 API 服务监听端口（默认 8875）\n   - 认证 Token: 设置访问令牌，留空表示无需认证\n   - 启用/禁用: 控制 API 服务开关\n   - 需要认证: 开启后所有 API 请求需携带 Token\n\n2. **API 文档入口**\n   - 📖 **Swagger UI**: 交互式 API 文档，支持在线测试\n   - 📄 **ReDoc**: 美观的文档展示界面\n   - 点击按钮即可在新窗口打开文档\n\n3. **认证方式**\n   如果启用了 Token 认证，调用 API 时需在请求头中添加：\n   ```\n   Authorization: Bearer YOUR_TOKEN\n   ```\n\n4. **连接测试**\n   点击「🔍 测试连接」可检测 API 服务是否正常响应，显示响应时间、接口数量等信息。",
    "settings": "## 系统设置\n\n查看系统状态和配置界面偏好。\n\n- **系统状态**: ROS2、Docker、安装目录状态\n- **界面偏好**: 脚本列表默认展开设置\n- **服务管理**: 重启 Web 服务\n- **实时日志**: 查看系统日志"
}

@router.get("/api/system/help/{page}")
async def get_help(page: str, current_user: dict = Depends(require_permission('docker'))):
    """获取页面帮助文档"""
    db_data = db.get_config("help_content", {}) or {}
    saved = db_data.get(page) if isinstance(db_data, dict) else None
    if isinstance(saved, str) and saved.strip():
        return {"success": True, "page": page, "content": saved}
    default_content = HELP_CONTENT.get(page, "")
    return {"success": True, "page": page, "content": default_content}

@router.get("/api/system/help-pages")
async def get_help_pages(current_user: dict = Depends(require_permission('docker'))):
    """获取所有帮助页面列表（菜单）"""
    pages = [
        {"id": "welcome", "name": "🏠 首页"},
        {"id": "scripts", "name": "📜 脚本与启动"},
        {"id": "advanced-scripts", "name": "📜 脚本执行增强"},
        {"id": "docker", "name": "🚛 仿真车管理"},
        {"id": "advanced-docker", "name": "🐳 容器管理增强"},
        {"id": "images", "name": "💿 镜像管理"},
        {"id": "traffic", "name": "🚦 红绿灯模拟"},
        {"id": "advanced-fault", "name": "💥 故障注入"},
        {"id": "batch", "name": "📦 车辆配置生成"},
        {"id": "tools", "name": "🛠️ 其他工具"},
        {"id": "simulation", "name": "🎮 仿真控制"},
        {"id": "topics", "name": "📡 话题查看"},
        {"id": "nodes", "name": "🔷 节点管理"},
        {"id": "services", "name": "🔧 服务管理"},
        {"id": "actions", "name": "⚡ Action 管理"},
        {"id": "advanced-extend", "name": "🔌 拓展功能"},
        {"id": "monitor", "name": "📊 系统监控"},
        {"id": "advanced-monitor", "name": "📊 监控面板增强"},
        {"id": "api-manager", "name": "📡 REST API 管理"},
        {"id": "check", "name": "✅ 系统自检"},
        {"id": "theme", "name": "🎨 主题设置"},
        {"id": "settings", "name": "⚙️ 系统设置"}
    ]
    return {"success": True, "pages": pages}

@router.post("/api/system/help")
async def save_help(data: dict, current_user: dict = Depends(require_permission('docker'))):
    """保存帮助文档内容。"""
    page = data.get("page")
    content = data.get("content")
    if not page or content is None:
        return {"success": False, "message": "参数错误"}
    if not isinstance(content, str):
        content = str(content)
    db_data = db.get_config("help_content", {}) or {}
    if not isinstance(db_data, dict):
        db_data = {}
    db_data[page] = content
    db.set_config("help_content", db_data)
    return {"success": True, "message": "帮助文档保存成功"}

@router.delete("/api/system/help/{page}")
async def delete_help(page: str, current_user: dict = Depends(require_permission('docker'))):
    """删除帮助文档内容（恢复为默认值）。"""
    db_data = db.get_config("help_content", {}) or {}
    if isinstance(db_data, dict) and page in db_data:
        del db_data[page]
        db.set_config("help_content", db_data)
    default_content = HELP_CONTENT.get(page, "")
    return {"success": True, "message": "帮助文档已恢复默认", "content": default_content}

# ---------- sudo 检查 ----------
@router.get("/api/system/sudo-check")
async def sudo_check(current_user: dict = Depends(require_admin)):
    """检查 sudo 免密配置"""
    try:
        rc, out, _ = DockerManager.run_cmd(["sudo", "-n", "true"])
        no_password = rc == 0
        docker_group = "docker" in subprocess.run(["groups"], capture_output=True, text=True).stdout
        return {
            "success": True,
            "no_password_sudo": no_password,
            "in_docker_group": docker_group,
            "message": "sudo 免密已配置" if no_password else "需要配置 sudo 免密",
            "fix_guide": "运行: sudo visudo -f /etc/sudoers.d/docker-nopasswd\n添加: fox ALL=(ALL) NOPASSWD: /usr/bin/docker" if not no_password else ""
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- 认证加密存储 ----------
@router.post("/api/system/auth/save")
async def save_auth_secure(data: Dict[str, str], current_user: dict = Depends(require_admin)):
    """加密保存认证信息"""
    username = data.get("username", "")
    password = data.get("password", "")
    token = data.get("token", "")
    auth_file = os.path.expanduser("~/.ros2_docker_manager_auth.json")
    try:
        import base64
        encoded = base64.b64encode(json.dumps({"username": username, "password": password, "token": token}).encode()).decode()
        with open(auth_file, 'w') as f:
            json.dump({"encoded": encoded, "method": "base64", "note": "使用系统密钥链加密存储"}, f, indent=2)
        db.add_audit_log(current_user["username"], "save_auth_secure", username)
        return {"success": True, "message": "已加密保存"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/system/auth/status")
async def auth_status(current_user: dict = Depends(require_permission('docker'))):
    """获取认证存储状态"""
    auth_file = os.path.expanduser("~/.ros2_docker_manager_auth.json")
    if os.path.exists(auth_file):
        try:
            with open(auth_file, 'r') as f:
                data = json.load(f)
            return {"success": True, "exists": True, "method": data.get("method", "unknown")}
        except:
            return {"success": True, "exists": True, "method": "plain"}
    return {"success": True, "exists": False}

