#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认证 / 管理员后台 / 审计日志 / 新手引导"""

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

@router.post("/api/auth/login")
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def login(request: Request, login_data: LoginRequest):
    """用户登录，返回 JWT Token"""
    user = db.verify_login(login_data.username, login_data.password)
    if not user:
        db.add_audit_log(login_data.username, "login_failed", "用户名或密码错误")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    email = user.get("email", login_data.username)
    role = user.get("role", "user")
    if login_data.remember_me:
        days = login_data.remember_days if login_data.remember_days in (7, 15, 30) else 7
    else:
        days = 1
    token = create_jwt_token({"sub": email, "role": role}, expires_delta=timedelta(days=days))
    db.add_audit_log(email, "login_success", f"登录成功, token有效{days}天")
    return {"success": True, "access_token": token, "token_type": "bearer", "role": role, "username": user.get("username", email), "email": email}

@router.post("/api/auth/register")
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def register(request: Request, reg_data: RegisterRequest):
    """用户注册（默认 user 角色，仅首页权限）"""
    if db.get_user(reg_data.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if len(reg_data.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    if not '@' in reg_data.username:
        raise HTTPException(status_code=400, detail="请使用邮箱注册")
    
    role = "user"
    username = generate_username_from_email(reg_data.username)
    home_folder_path = create_user_workspace(username)
    
    ok, result = db.create_user(reg_data.username, reg_data.password, role, home_folder_path)
    if ok:
        db.add_audit_log(reg_data.username, "register", f"新用户注册，角色 user，工作目录: {home_folder_path}")
        return {"success": True, "message": "注册成功", "username": username, "home_folder_path": home_folder_path}
    else:
        raise HTTPException(status_code=500, detail=f"注册失败: {result}")

@router.post("/api/auth/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """用户注销"""
    db.add_audit_log(current_user["username"], "logout", "用户注销")
    return {"success": True, "message": "已登出"}

@router.get("/api/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "success": True,
        "username": current_user["username"],
        "role": current_user["role"],
        # v5.0：当前选择的 install 版本（空表示未选择，使用旧版 install 目录）
        "current_version": current_user.get("current_version", "") or ""
    }

@router.get("/api/admin/users")
async def list_users(current_user: dict = Depends(require_admin)):
    """管理员获取所有用户列表

    v5.2：弹掉 bcrypt 哈希（不可逆，无意义），保留 password_plain 供管理员查看。
    Supabase 模式下若 password_plain 列未就绪，则 recheck 一次（补列后免重启自愈）。
    """
    # v5.2：Supabase 缺列自愈——若启动时探测为缺失，每次列表请求实时复查一次
    if hasattr(db, "password_plain_column_ok") and not db.password_plain_column_ok:
        recheck = getattr(db, "recheck_password_plain_column", None)
        if callable(recheck):
            recheck()

    users = db.get_all_users()
    for u in users.values():
        u.pop("password", None)  # 弹掉 bcrypt 哈希（不可逆，无需展示）
        if not u.get("permissions"):
            u["permissions"] = []
        # v5.2：password_plain 缺失时填空串，避免前端 undefined
        u.setdefault("password_plain", "")
    return {"success": True, "users": users}

@router.post("/api/admin/users")
async def create_user(data: Dict[str, Any], current_user: dict = Depends(require_admin)):
    """管理员创建新用户"""
    email = data.get("email") or data.get("username")
    password = data.get("password")
    role = data.get("role", "user")
    permissions = data.get("permissions")
    if not email or not password:
        raise HTTPException(400, "邮箱和密码必填")
    if len(password) < 6:
        raise HTTPException(400, "密码至少6位")
    if not '@' in email:
        raise HTTPException(400, "请使用邮箱注册")
    if db.get_user(email):
        raise HTTPException(400, "邮箱已存在")
    
    username = generate_username_from_email(email)
    home_folder_path = create_user_workspace(username)
    
    ok, result = db.create_user(email, password, role, home_folder_path, permissions=permissions)
    if ok:
        db.add_audit_log(current_user["username"], "create_user", f"创建用户 {email}，角色 {role}，工作目录: {home_folder_path}")
        return {"success": True, "message": "用户创建成功", "username": username, "home_folder_path": home_folder_path}
    else:
        raise HTTPException(500, f"创建失败: {result}")

@router.put("/api/admin/users/{user_id}")
async def update_user(user_id: str, data: Dict[str, Any], current_user: dict = Depends(require_admin)):
    """管理员更新用户信息"""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    
    if user_id == current_user.get("id") and data.get("role") == "user" and current_user["role"] == "admin":
        all_users = db.get_all_users()
        admins = [info for info in all_users.values() if info.get("role") == "admin"]
        if len(admins) <= 1:
            raise HTTPException(400, "不能移除最后一个管理员")
    
    updates = {}
    if "password" in data and data["password"]:
        updates["password"] = data["password"]
    if "role" in data:
        updates["role"] = data["role"]
    if "permissions" in data:
        updates["permissions"] = data["permissions"]

    if not updates:
        raise HTTPException(400, "无更新内容")
    
    ok = db.update_user(user_id, updates)
    if ok:
        db.add_audit_log(current_user["username"], "update_user", f"更新用户 {user.get('email', user_id)}")
        return {"success": True, "message": "用户更新成功"}
    else:
        raise HTTPException(500, "更新失败")

@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, current_user: dict = Depends(require_admin)):
    """v5.2：管理员一键重置用户密码为默认密码（B@@nray!123）

    - 仅管理员可调用；
    - 重置后 bcrypt hash 与 password_plain 同步更新，前端可立即查看新密码；
    - 写审计日志。
    """
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")

    ok = db.update_user(user_id, {"password": DEFAULT_RESET_PASSWORD})
    if ok:
        db.add_audit_log(
            current_user["username"], "reset_password",
            f"重置用户 {user.get('email', user_id)} 密码为默认密码"
        )
        return {
            "success": True,
            "message": f"密码已重置为默认密码：{DEFAULT_RESET_PASSWORD}",
            "new_password": DEFAULT_RESET_PASSWORD,
        }
    else:
        raise HTTPException(500, "密码重置失败")

@router.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(require_admin)):
    """管理员删除用户"""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    
    if user_id == current_user.get("id"):
        raise HTTPException(400, "不能删除自己")
    
    ok = db.delete_user(user_id)
    if ok:
        # 同步删除该用户的审计日志记录
        db.delete_audit_logs_by_user(user.get("username", user.get("email", "")))
        db.add_audit_log(current_user["username"], "delete_user", f"删除用户 {user.get('email', user_id)}")
        return {"success": True, "message": "用户删除成功"}
    else:
        raise HTTPException(500, "删除失败")

# ---------- 审计日志管理 ----------
@router.get("/api/admin/audit-logs")
async def get_audit_logs(limit: int = 100, current_user: dict = Depends(require_admin)):
    """管理员获取审计日志"""
    logs = db.get_audit_logs(limit)
    return {"success": True, "logs": logs, "total": len(logs)}

@router.delete("/api/admin/audit-logs")
async def delete_audit_logs(data: Dict[str, int] = None, current_user: dict = Depends(require_admin)):
    """管理员清除审计日志"""
    keep_recent = data.get("keep_recent", 0) if data else 0
    deleted = db.delete_audit_logs(keep_recent)
    db.add_audit_log(current_user["username"], "clear_audit_logs", f"删除 {deleted} 条日志，保留最近 {keep_recent} 条")
    return {"success": True, "message": f"已删除 {deleted} 条日志", "deleted": deleted}

@router.get("/api/auth/permissions")
async def get_current_permissions(current_user: dict = Depends(get_current_user)):
    """获取当前用户的权限列表"""
    perms = db.get_user_permissions(current_user["username"])
    return {"success": True, "permissions": perms, "role": current_user["role"]}

@router.post("/api/auth/change-password")
async def change_password(data: Dict[str, Any], current_user: dict = Depends(get_current_user)):
    """修改当前用户密码"""
    new_password = data.get("new_password")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    user_id = current_user.get("id")
    email = current_user.get("email")
    ok = db.update_user(user_id or email, {"password": new_password})
    if ok:
        db.add_audit_log(current_user["username"], "change_password", "密码修改成功")
        return {"success": True, "message": "密码修改成功"}
    else:
        raise HTTPException(status_code=500, detail="密码修改失败")

# ---------- 新手引导 ----------
@router.get("/api/auth/onboarding")
async def get_onboarding_state(current_user: dict = Depends(get_current_user)):
    """获取当前用户的新手引导状态"""
    state = db.get_onboarding_state(current_user["username"])
    return {"success": True, **state}

@router.put("/api/auth/onboarding")
async def set_onboarding_state(data: Dict[str, Any], current_user: dict = Depends(get_current_user)):
    """更新当前用户的新手引导状态"""
    completed = data.get("completed")
    skipped = data.get("skipped")
    ok = db.set_onboarding_state(current_user["username"], completed=completed, skipped=skipped)
    if ok:
        return {"success": True, "message": "状态已更新"}
    else:
        raise HTTPException(500, "更新失败")

