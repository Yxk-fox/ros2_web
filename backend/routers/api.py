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
    Depends, Request, status, Body, UploadFile, File, Form
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
    ws_clients, traffic_sender, timer_traffic_sender,
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, BCRYPT_ROUNDS,
    RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD,
    INPUT_FILTER_ENABLED, INPUT_FILTER_WHITELIST, ROS2_WS
)
from core.security import (
    hash_password, verify_password, create_jwt_token, decode_jwt_token,
    sanitize_command, limiter
)
from core.utils import (
    run_ros2_cmd, run_ros2_cmd_in_container, load_whitelist, parse_size,
    get_used_ports, find_free_port, build_dir_tree, extract_and_flatten,
    _safe_copy2, _normalize_rviz_config, _resolve_rviz_config, _maximize_rviz,
    error_response, generate_username_from_email, broadcast_log, generate_files
)
from core.workspace import (
    validate_user_path, get_user_workspace_paths, create_user_workspace
)
from core.cache import SimpleCache, _memory_cache
from database import db
from deps import get_current_user, require_admin, require_permission, security
from models import LoginRequest, RegisterRequest
from services.system_monitor import SystemMonitor
from services.docker_manager import DockerManager
from services.script_generator import ROS2ScriptGenerator
from services.system_utils import SystemUtils
from services.traffic_light import TrafficLightSender, TimerTrafficLightSender

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
    return {"success": True, "username": current_user["username"], "role": current_user["role"]}

@router.get("/api/admin/users")
async def list_users(current_user: dict = Depends(require_admin)):
    """管理员获取所有用户列表"""
    users = db.get_all_users()
    for u in users.values():
        u.pop("password", None)
        if not u.get("permissions"):
            u["permissions"] = []
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

# ---------- 系统状态与监控 ----------
@router.get("/api/system/status")
async def system_status(current_user: dict = Depends(get_current_user)):
    """获取系统状态（ROS2/Docker/目录）"""
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

@router.get("/api/system/monitor")
async def system_monitor(current_user: dict = Depends(require_permission('docker'))):
    """获取系统监控数据（CPU/内存/GPU/进程）"""
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


# ============================================================
# v3.6 Web 文件管理器（在浏览器中浏览/下载/删除/上传文件）
# ============================================================

def _resolve_user_dir(folder_type: str, current_user: dict, target_user: Optional[str]) -> str:
    """根据 folder_type 解析目标根目录，并校验合法性。

    支持的 folder_type:
        - bags / logs / install / bk / scripts
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    mapping = {
        "bags":    workspace_paths["bag_storage"],
        "logs":    workspace_paths["logs_dir"],
        "install": workspace_paths["host_install"],
        "bk":      workspace_paths["backup_dir"],
        "scripts": workspace_paths["scripts_dir"],
    }
    if folder_type not in mapping:
        raise HTTPException(400, "未知目录类型")
    root = mapping[folder_type]
    validate_user_path(root, current_user, target_user=target_user)
    return root


def _safe_join(root: str, subpath: str) -> str:
    """将 subpath 安全拼接到 root 下，防止路径遍历。"""
    if subpath is None:
        subpath = ""
    # 统一正斜杠
    subpath = subpath.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(root, subpath))
    root_norm = os.path.normpath(root)
    # 必须仍在 root 之下（或就是 root）
    if full != root_norm and not full.startswith(root_norm + os.sep):
        raise HTTPException(400, "非法路径访问")
    return full


@router.get("/api/files/list")
async def list_files(
    folder_type: str,
    subpath: Optional[str] = "",
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('tools'))
):
    """列出指定目录下的文件和子目录。

    返回结构：``{success, items:[{name,type,size,mtime,is_dir}], path, parent, exists}``
    """
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)

    if not os.path.exists(full):
        return {"success": True, "exists": False, "items": [], "path": full, "parent": None}
    if not os.path.isdir(full):
        raise HTTPException(400, "指定路径不是目录")

    items = []
    try:
        for name in sorted(os.listdir(full), key=lambda n: (not os.path.isdir(os.path.join(full, n)), n.lower())):
            p = os.path.join(full, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append({
                "name": name,
                "is_dir": os.path.isdir(p),
                "size": st.st_size if os.path.isfile(p) else 0,
                "mtime": int(st.st_mtime),
            })
    except PermissionError:
        raise HTTPException(403, "无权限访问该目录")

    rel = os.path.relpath(full, root)
    if rel == ".":
        rel = ""
    parent = os.path.dirname(rel) if rel else None
    if parent == "":
        parent = None
    return {
        "success": True,
        "exists": True,
        "items": items,
        "path": full,
        "rel": rel,
        "parent": parent,
        "root_type": folder_type,
        "target_user": target_user,
    }


@router.get("/api/files/download")
async def download_file(
    folder_type: str,
    subpath: str,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('tools'))
):
    """下载文件。"""
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.isfile(full):
        raise HTTPException(404, "文件不存在")
    return FileResponse(full, filename=os.path.basename(full))


@router.post("/api/files/delete")
async def delete_file(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """删除文件或空目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    target_user = data.get("target_user")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.exists(full):
        raise HTTPException(404, "路径不存在")
    if os.path.isdir(full):
        # 防止误删根目录
        if os.path.normpath(full) == os.path.normpath(root):
            raise HTTPException(400, "不允许删除根目录")
        shutil.rmtree(full)
        db.add_audit_log(current_user["username"], "file_delete",
                         f"dir {subpath} target={target_user or 'self'}")
    else:
        os.unlink(full)
        db.add_audit_log(current_user["username"], "file_delete",
                         f"file {subpath} target={target_user or 'self'}")
    return {"success": True, "message": "已删除"}


@router.post("/api/files/mkdir")
async def make_dir(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """在指定目录下创建子目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    target_user = data.get("target_user")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if os.path.exists(full):
        raise HTTPException(400, "路径已存在")
    os.makedirs(full, exist_ok=True)
    db.add_audit_log(current_user["username"], "file_mkdir",
                     f"dir {subpath} target={target_user or 'self'}")
    return {"success": True, "message": "已创建目录"}


@router.post("/api/files/upload")
async def upload_files(
    folder_type: str = Form(...),
    subpath: str = Form(""),
    target_user: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(require_permission('tools'))
):
    """上传一个或多个文件到指定目录。"""
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.isdir(full):
        # 若父目录不存在，自动创建（只到 root 之下）
        os.makedirs(full, exist_ok=True)

    saved = []
    for f in files:
        if not f.filename:
            continue
        # 仅取 basename，防止路径穿越
        safe_name = os.path.basename(f.filename)
        dest = os.path.join(full, safe_name)
        with open(dest, "wb") as out:
            while chunk := await f.read(8 * 1024 * 1024):
                out.write(chunk)
        saved.append(safe_name)
    db.add_audit_log(current_user["username"], "file_upload",
                     f"{len(saved)} files to {subpath} target={target_user or 'self'}")
    return {"success": True, "saved": saved, "count": len(saved)}


@router.post("/api/files/rename")
async def rename_file(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """重命名文件或目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    new_name = data.get("new_name", "").strip()
    target_user = data.get("target_user")
    if not new_name:
        raise HTTPException(400, "新名称不能为空")
    if '/' in new_name or '\\' in new_name:
        raise HTTPException(400, "名称不能包含路径分隔符")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.exists(full):
        raise HTTPException(404, "路径不存在")
    parent = os.path.dirname(full)
    new_full = os.path.join(parent, new_name)
    if os.path.exists(new_full):
        raise HTTPException(400, "目标名称已存在")
    os.rename(full, new_full)
    db.add_audit_log(current_user["username"], "file_rename",
                     f"{subpath} -> {os.path.join(os.path.dirname(subpath), new_name)} target={target_user or 'self'}")
    return {"success": True, "message": "已重命名"}


@router.post("/api/files/sync-bags")
async def sync_bags_from_containers(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """从运行中的ROS2容器同步bag文件到宿主机用户bags目录"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    bag_storage = workspace_paths["bag_storage"]
    container_bag_path = workspace_paths["container_bag_path"]
    container_bag_path_alt = workspace_paths.get("container_bag_path_alt", "/home/boonray/.boonray/bagfiles")
    validate_user_path(bag_storage, current_user)
    os.makedirs(bag_storage, exist_ok=True)

    containers = DockerManager.list_containers(running_only=True, filter_name="ros2_")
    if not containers:
        return {"success": True, "message": "没有运行中的ROS2容器", "synced_count": 0}

    synced_count = 0
    errors = []
    bag_paths_to_check = [container_bag_path, container_bag_path_alt]

    for container in containers:
        container_name = container["name"]
        for bag_path in bag_paths_to_check:
            rc, out, err = DockerManager.run_cmd(
                DockerManager._docker("exec", container_name, "bash", "-c", f"ls -d {bag_path}/rosbag2_* 2>/dev/null || true"),
                timeout=10
            )
            if rc != 0 or not out.strip():
                continue
            bag_dirs = [d.strip() for d in out.strip().split('\n') if d.strip()]
            for bag_dir in bag_dirs:
                bag_name = os.path.basename(bag_dir)
                dest_dir = os.path.join(bag_storage, bag_name)
                if os.path.exists(dest_dir):
                    continue
                rc, out, err = DockerManager.run_cmd(
                    DockerManager._docker("cp", f"{container_name}:{bag_dir}", dest_dir),
                    timeout=120
                )
                if rc == 0:
                    synced_count += 1
                else:
                    errors.append(f"{container_name}:{bag_name} - {err[:200]}")

    msg = f"已同步 {synced_count} 个bag"
    if errors:
        msg += f"，{len(errors)} 个失败"
    db.add_audit_log(current_user["username"], "sync_bags",
                     f"{synced_count} bags target={target_user or 'self'}")
    return {"success": True, "message": msg, "synced_count": synced_count, "errors": errors}


@router.get("/api/system/cloud-env")
async def get_cloud_env():
    """获取当前云环境配置（优先从 cloud.yaml 读取真实 IP，防止配置不同步）"""
    config_dir = os.path.expanduser(CONFIG.get("paths", {}).get("config_dir",
        "~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config"))
    actual_ip = SystemUtils.get_cloud_ip_from_yaml(config_dir)
    if actual_ip and actual_ip != CONFIG["cloud_env"].get("current_ip"):
        CONFIG["cloud_env"]["current_ip"] = actual_ip
        for env_name, env_ip in CONFIG["cloud_env"]["ip_map"].items():
            if env_ip == actual_ip:
                CONFIG["cloud_env"]["current_env"] = env_name
                break
        save_config(CONFIG)
    return {
        "success": True,
        "current_env": CONFIG["cloud_env"]["current_env"],
        "current_ip": CONFIG["cloud_env"]["current_ip"],
        "ip_map": CONFIG["cloud_env"]["ip_map"]
    }

@router.get("/api/system/cloud-status")
async def check_cloud_status():
    """检查云平台连接状态"""
    cloud_ip = CONFIG["cloud_env"]["current_ip"] or "139.196.75.44"
    cloud_port = 9201
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((cloud_ip, cloud_port))
        sock.close()
        connected = result == 0
        return {"success": True, "connected": connected, "ip": cloud_ip, "port": cloud_port}
    except Exception as e:
        return {"success": True, "connected": False, "ip": cloud_ip, "port": cloud_port, "error": str(e)}

# ---------- ROS2 命令 ----------
@router.post("/api/ros2/simulation/start")
async def start_simulation(data: Dict[str, str], current_user: dict = Depends(require_permission('simulation'))):
    """在容器中启动Mock Truck仿真"""
    container_id = data.get("container_id")
    cmd = data.get("command")
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    if not cmd:
        raise HTTPException(400, "缺少命令")
    # 使用 shlex.split 正确处理带引号的命令参数，避免破坏包含空格/引号的参数
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        raise HTTPException(400, f"命令格式错误: {e}")
    rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=60)
    db.add_audit_log(current_user["username"], "start_simulation", f"容器 {container_id}: {cmd}")
    if rc == 0:
        await broadcast_log("info", f"Mock Truck 仿真启动成功 (容器 {container_id}): {cmd}")
    else:
        await broadcast_log("error", f"Mock Truck 仿真启动失败 (容器 {container_id}): {err}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/ros2/cmd_vel")
async def publish_cmd_vel(data: Dict[str, Any], current_user: dict = Depends(require_permission('simulation'))):
    """发布速度控制指令"""
    topic = data.get("topic", "/cmd_vel")
    linear = data.get("linear_x", 0.0)
    angular = data.get("angular_z", 0.0)
    msg = f"linear: {{x: {linear}, y: 0.0, z: 0.0}}, angular: {{x: 0.0, y: 0.0, z: {angular}}}"
    rc, out, err = run_ros2_cmd(["ros2", "topic", "pub", "--once", topic, "geometry_msgs/msg/Twist", msg], timeout=5)
    db.add_audit_log(current_user["username"], "cmd_vel", f"{topic} lx={linear} az={angular}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/ros2/topic/pub")
async def topic_pub(data: Dict[str, Any], current_user: dict = Depends(require_permission('topics'))):
    """在容器中发布话题消息"""
    container_id = data.get("container_id")
    topic = data.get("topic")
    msg_type = data.get("msg_type", "std_msgs/msg/String")
    msg_data = data.get("data", "{}")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not topic:
        raise HTTPException(400, "缺少话题名")
    if not topic.startswith('/'):
        topic = '/' + topic
    cmd_parts = ["ros2", "topic", "pub", "--once", topic, msg_type, msg_data]
    rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=10)
    db.add_audit_log(current_user["username"], "topic_pub", f"{topic} -> {msg_data}")
    if rc == 0:
        return {"success": True, "stdout": out or "✅ 发布成功", "stderr": err}
    else:
        return {"success": False, "error": err or "发布失败", "stdout": out}

@router.post("/api/ros2/topic/kill")
async def topic_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('topics'))):
    """杀死发布指定话题的节点"""
    container_id = data.get("container_id")
    topic = data.get("topic")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not topic:
        raise HTTPException(400, "缺少话题名")
    if not topic.startswith('/'):
        topic = '/' + topic
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "info", topic], timeout=10)
    if rc != 0:
        return {"success": False, "error": f"无法获取话题 {topic} 的信息: {err}"}
    nodes = re.findall(r"Publisher: (/\S+)", out)
    if not nodes:
        return {"success": False, "error": f"未找到发布话题 {topic} 的节点", "info": out}
    results = []
    for node in nodes:
        rc2, out2, err2 = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
        results.append({"node": node, "success": rc2 == 0, "output": out2 if rc2 == 0 else err2})
    success_count = sum(1 for r in results if r["success"])
    db.add_audit_log(current_user["username"], "topic_kill", f"{topic} killed {success_count} nodes")
    return {"success": True, "results": results, "message": f"已尝试杀死 {len(results)} 个发布者节点，成功 {success_count} 个"}

@router.post("/api/ros2/node/kill")
async def node_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('nodes'))):
    """杀死指定节点"""
    container_id = data.get("container_id")
    node = data.get("node")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not node:
        raise HTTPException(400, "缺少节点名")
    if not node.startswith('/'):
        node = '/' + node
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
    db.add_audit_log(current_user["username"], "node_kill", node)
    if rc == 0:
        return {"success": True, "stdout": out or f"✅ 节点 {node} 已停止", "stderr": err}
    else:
        return {"success": False, "error": err or f"无法停止节点 {node}"}

@router.post("/api/ros2/service/kill")
async def service_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('services'))):
    """杀死提供指定服务的节点"""
    container_id = data.get("container_id")
    service = data.get("service")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not service:
        raise HTTPException(400, "缺少服务名")
    if not service.startswith('/'):
        service = '/' + service
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "info", service], timeout=10)
    if rc != 0:
        return {"success": False, "error": f"无法获取服务 {service} 的信息: {err}"}
    nodes = re.findall(r"Node: (/\S+)", out)
    if not nodes:
        return {"success": False, "error": f"未找到提供服务 {service} 的节点", "info": out}
    results = []
    for node in nodes:
        rc2, out2, err2 = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
        results.append({"node": node, "success": rc2 == 0, "output": out2 if rc2 == 0 else err2})
    success_count = sum(1 for r in results if r["success"])
    db.add_audit_log(current_user["username"], "service_kill", f"{service} killed {success_count} nodes")
    return {"success": True, "results": results, "message": f"已尝试杀死 {len(results)} 个提供服务的节点，成功 {success_count} 个"}

# ---------- ROS2 话题 ----------
@router.get("/api/ros2/topics")
async def list_topics(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 话题"""
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    # 权限检查：topics 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "topics" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问话题列表")
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "list"])
    if rc != 0:
        return {"success": False, "error": err}
    topics = [t for t in out.splitlines() if t]
    db.add_audit_log(current_user["username"], "list_topics", f"容器 {container_id}")
    return {"success": True, "topics": topics}

@router.get("/api/ros2/topic/{name:path}/info")
async def topic_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('topics'))):
    """获取话题详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "info", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "topic", "info", name], timeout=10)
    if rc == 0:
        return {"success": True, "info": out if out else "✅ 话题存在（无额外信息）"}
    else:
        return {"success": False, "error": err or f"无法获取话题 {name} 的信息"}

@router.get("/api/ros2/topic/{name:path}/echo")
async def topic_echo(name: str, once: bool = True, container_id: str = None, current_user: dict = Depends(require_permission('topics'))):
    """获取话题最新一条消息"""
    if container_id:
        cmd_parts = ["ros2", "topic", "echo", name]
        if once:
            cmd_parts.append("--once")
        rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=10)
    else:
        cmd_parts = ["ros2", "topic", "echo", name]
        if once:
            cmd_parts.append("--once")
        rc, out, err = run_ros2_cmd(cmd_parts, timeout=10)
    db.add_audit_log(current_user["username"], "topic_echo", name)
    if rc == 0:
        return {"success": True, "data": out if out else "✅ 执行成功（无数据输出）"}
    else:
        return {"success": False, "error": err or "执行失败"}

# ---------- ROS2 节点 ----------
@router.get("/api/ros2/nodes")
async def list_nodes(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 节点"""
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    # 权限检查：nodes 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "nodes" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问节点列表")
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "list"])
    if rc != 0:
        return {"success": False, "error": err or "容器内执行失败"}
    nodes = [n for n in out.splitlines() if n and n not in ("/rosout", "/parameter_events")]
    db.add_audit_log(current_user["username"], "list_nodes", f"容器 {container_id}")
    return {"success": True, "nodes": nodes}

@router.get("/api/ros2/node/{name:path}/info")
async def node_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('nodes'))):
    """获取节点详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "info", name], timeout=15)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "node", "info", name], timeout=15)
    db.add_audit_log(current_user["username"], "node_info", name)
    if rc == 0:
        return {"success": True, "info": out if out else "✅ 节点存在（无额外信息）"}
    else:
        return {"success": False, "error": err or f"无法找到节点 {name}"}

# ---------- ROS2 服务 ----------
@router.get("/api/ros2/services")
async def list_services(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 服务"""
    # 权限检查：services 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "services" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问服务列表")
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "list"], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "list"], timeout=10)
    if rc != 0:
        raise HTTPException(500, err)
    services = [s for s in out.splitlines() if s]
    db.add_audit_log(current_user["username"], "list_services", f"容器 {container_id}")
    return {"success": True, "services": services}

@router.get("/api/ros2/service/{name:path}/type")
async def service_type(name: str, container_id: str = None, current_user: dict = Depends(require_permission('services'))):
    """获取服务类型"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "type", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "type", name], timeout=10)
    return {"success": rc == 0, "type": out if rc == 0 else err}

@router.post("/api/ros2/service/{name:path}/call")
async def call_service(name: str, data: Dict[str, Any], container_id: str = None, current_user: dict = Depends(require_permission('services'))):
    """调用 ROS2 服务"""
    srv_type = data.get("srv_type")
    req = data.get("data", "{}")
    if not srv_type:
        raise HTTPException(400, "缺少服务类型")
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "call", name, srv_type, req], timeout=15)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "call", name, srv_type, req], timeout=15)
    db.add_audit_log(current_user["username"], "call_service", f"{name} -> {srv_type}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

# ---------- ROS2 Action ----------
@router.get("/api/ros2/actions")
async def list_actions(container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """列出容器中的 ROS2 Action"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "list"], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "action", "list"], timeout=10)
    if rc != 0:
        raise HTTPException(500, err)
    actions = [a for a in out.splitlines() if a]
    db.add_audit_log(current_user["username"], "list_actions", f"容器 {container_id}")
    return {"success": True, "actions": actions}

@router.get("/api/ros2/action/{name}/info")
async def action_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """获取 Action 详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "info", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "action", "info", name], timeout=10)
    db.add_audit_log(current_user["username"], "action_info", name)
    return {"success": rc == 0, "info": out if rc == 0 else err}

@router.post("/api/ros2/action/{name}/send_goal")
async def send_action_goal(name: str, data: Dict[str, Any], container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """发送 Action 目标"""
    action_type = data.get("action_type")
    goal = data.get("data", "{}")
    if container_id:
        if action_type:
            rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "send_goal", name, action_type, goal], timeout=15)
        else:
            rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "send_goal", name, goal], timeout=15)
    else:
        if action_type:
            rc, out, err = run_ros2_cmd(["ros2", "action", "send_goal", name, action_type, goal], timeout=15)
        else:
            rc, out, err = run_ros2_cmd(["ros2", "action", "send_goal", name, goal], timeout=15)
    db.add_audit_log(current_user["username"], "send_action_goal", f"{name} -> {goal}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

# ---------- Docker 管理 ----------
def get_current_cloud_ip():
    """获取当前配置的云平台IP（优先从配置文件获取）"""
    current_ip = CONFIG["cloud_env"]["current_ip"]
    if current_ip:
        return current_ip
    
    config_dir = os.path.expanduser("~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config")
    if not os.path.isdir(config_dir):
        config_dir = os.path.expanduser("~/robotruck_ros2/Docker/bk/simulation_launches/config")
    if not os.path.isdir(config_dir):
        return None
    
    cloud_file = os.path.join(config_dir, "cloud.yaml")
    if os.path.isfile(cloud_file):
        try:
            with open(cloud_file, 'r', encoding='utf-8') as f:
                content = f.read()
                match = re.search(r'udp_server_url:\s*(\d+\.\d+\.\d+\.\d+)', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
    return None

def get_cloud_ip_from_host_mount(container_name):
    """从容器在宿主机的挂载点读取实际云IP配置"""
    try:
        mount_cmd = DOCKER_PREFIX.split() + [
            "docker", "inspect", container_name,
            "--format", "{{range .Mounts}}{{if eq .Destination \"/home/boonray/install\"}}{{.Source}}{{end}}{{end}}"
        ]
        rc, mount_src, _ = DockerManager.run_cmd(mount_cmd, timeout=5)
        if rc == 0 and mount_src.strip():
            cloud_yaml = os.path.join(
                mount_src.strip(),
                "simulation_launches/share/simulation_launches/config/cloud.yaml"
            )
            if os.path.isfile(cloud_yaml):
                with open(cloud_yaml, 'r', encoding='utf-8') as f:
                    content = f.read()
                m = re.search(r'udp_server_url:\s*([\d\.]+)', content)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def get_cloud_ip_from_container(container_name):
    """从容器提取云平台IP
    优先顺序：
    1. 运行中容器：从宿主机挂载点读取实际cloud.yaml配置（最准确，无需docker exec）
    2. 运行中容器（回退）：docker exec进入容器读取配置
    3. 标签读取：从 --label ros2.cloud_ip 读取启动时记录的IP
    4. 回退到当前全局配置的IP
    """
    label_ip = None
    try:
        cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "--format", "{{index .Config.Labels \"ros2.cloud_ip\"}}", container_name]
        rc, out, _ = DockerManager.run_cmd(cmd)
        if rc == 0 and out.strip() and out.strip() != "<no value>":
            label_ip = out.strip()
    except Exception:
        pass

    try:
        state_cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "-f", "{{.State.Running}}", container_name]
        rc_state, state_out, _ = DockerManager.run_cmd(state_cmd, timeout=5)
        is_running = rc_state == 0 and "true" in state_out.lower()

        if is_running:
            host_ip = get_cloud_ip_from_host_mount(container_name)
            if host_ip and re.match(r'^\d+\.\d+\.\d+\.\d+$', host_ip):
                return host_ip

            grep_cmd = ["bash", "-c",
                f"docker exec {shlex.quote(container_name)} bash -c "
                f"\"grep -oP 'udp_server_url:\\s*\\K[\\d\\.]+' "
                f"/home/boonray/install/simulation_launches/share/simulation_launches/config/cloud.yaml 2>/dev/null || true\""]
            rc_ip, ip_out, _ = DockerManager.run_cmd(grep_cmd, timeout=5)
            if rc_ip == 0 and ip_out.strip():
                actual_ip = ip_out.strip().split('\n')[0].strip()
                if re.match(r'^\d+\.\d+\.\d+\.\d+$', actual_ip):
                    return actual_ip
    except Exception:
        pass

    if label_ip:
        return label_ip

    return get_current_cloud_ip()

@router.get("/api/docker/containers")
async def list_containers(all: bool = True, filter_name: str = None, filter_image: str = None, current_user: dict = Depends(require_permission('docker'))):
    """列出 Docker 容器（普通用户仅可见自己启动的容器，管理员可看全部）"""
    try:
        if filter_image:
            import urllib.parse
            filter_image = urllib.parse.unquote(filter_image)
        # 普通用户权限隔离：只列出当前用户创建的容器
        visible_names = db.get_visible_container_names(current_user)
        containers = DockerManager.list_containers(running_only=not all, filter_name=filter_name, filter_image=filter_image)

        # 过滤可见容器
        filtered = []
        for c in containers:
            name = c["name"]
            if visible_names is not None and name not in visible_names:
                continue
            filtered.append(c)

        # 批量获取容器ID和云IP（单次 docker ps 调用）
        if filtered:
            # ★★★ 修复bug4：docker ps 模板不支持 .Config.Labels 索引（仅 docker inspect 支持）
            # 必须使用 docker ps 专用的 {{.Label "key"}} 函数，且字段名是 {{.Names}}（复数）
            # 旧格式 {{.Name}} + {{index .Config.Labels "..."}} 会让整个模板执行失败，
            # 导致 cloud_map 始终为空，容器列表的"云平台连接"列全部回退为当前配置IP，
            # 无法记住每个容器启动时记录的云IP（即"云平台连接失效没记住以前状态"的根因）。
            fmt = "{{.ID}}\t{{.Names}}\t{{.Label \"ros2.cloud_ip\"}}"
            cmd = DOCKER_PREFIX.split() + ["docker", "ps", "-a", "--format", fmt]
            rc, out, _ = DockerManager.run_cmd(cmd)
            id_map = {}
            cloud_map = {}
            if rc == 0:
                for line in out.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[1].lstrip("/")
                        id_map[name] = parts[0][:12]
                        if len(parts) >= 3 and parts[2] and parts[2] != "<no value>":
                            cloud_map[name] = parts[2]
            else:
                logger.warning(f"docker ps 批量获取云IP失败，回退到逐个 inspect: {out[:200]}")
                # 回退方案：逐个 docker inspect（与 0716_Web 参考实现一致）
                for c in filtered:
                    nm = c["name"]
                    id_map[nm] = ""
                    cloud_map[nm] = get_cloud_ip_from_container(nm)
        else:
            id_map = {}
            cloud_map = {}

        # 批量获取运行中容器的真实启动时间（State.StartedAt）
        # —— 用于前端“运行时长”权威展示，停止的容器不返回该字段（自动归零）
        started_at_map = {}
        running_names = [c["name"] for c in filtered if "up" in c["status"].lower()]
        if running_names:
            inspect_fmt = "{{.Name}}\t{{.State.StartedAt}}"
            cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "--format", inspect_fmt] + running_names
            rc, out, _ = DockerManager.run_cmd(cmd, timeout=15)
            if rc == 0:
                for line in out.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        nm = parts[0].lstrip("/")
                        started_at_map[nm] = parts[1]

        # 批量获取容器归属（避免 N+1 查询）
        owner_map = {}
        if visible_names is None and filtered:
            try:
                names_list = [c["name"] for c in filtered]
                resp = db._client.table("containers").select("name,created_by").in_("name", names_list).execute()
                for row in resp.data:
                    owner_map[row["name"]] = row.get("created_by", "")
            except Exception:
                pass

        result = []
        for c in filtered:
            name = c["name"]
            cid = id_map.get(name, "")
            status_lower = c["status"].lower()
            state = "running" if "up" in status_lower else "exited"
            # 云平台连接仅对 ROS2 容器有意义：优先读取容器启动时记录的 label，
            # 缺失时（旧 ROS2 容器未设置 label）回退到当前配置 IP。
            # 非 ROS2 容器（grafana/prometheus 等）不返回 cloud_ip，避免误显示。
            image_lower = (c.get("image") or "").lower()
            is_ros2 = name.startswith("ros2_") or any(k in image_lower for k in ("ros2", "humble", "foxy"))
            cloud_ip = cloud_map.get(name)
            if not cloud_ip and is_ros2:
                cloud_ip = get_current_cloud_ip()
            owner = "self" if (visible_names is not None) else owner_map.get(name, "")
            # 运行中容器返回真实启动时间（ISO8601），停止容器不返回（前端据此归零）
            started_at = started_at_map.get(name) if state == "running" else None
            result.append({
                "id": cid,
                "name": name,
                "status": c["status"],
                "image": c["image"],
                "created": c.get("created", ""),
                "state": state,
                "cloud_ip": cloud_ip,
                "owner": owner,
                "started_at": started_at
            })
        return {"success": True, "containers": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _check_container_access(container_name_or_id: str, current_user: dict):
    """校验当前用户是否有权操作容器（管理员直接通过；普通用户需为创建者）"""
    if current_user.get("role") == "admin":
        return True
    # 先按 name 查；如果传的是 ID，尝试从 DockerManager 获取 name
    owner = db.get_container_owner(container_name_or_id)
    if owner is None:
        # 尝试按容器 ID 反查 name
        rc, out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", container_name_or_id))
        if rc == 0 and out.strip():
            name = out.strip().lstrip("/")
            owner = db.get_container_owner(name)
    if owner is None:
        return True  # 未记录归属的旧容器，放行避免误拦
    return str(owner) == str(current_user.get("id"))

@router.post("/api/docker/container/{id}/start")
async def start_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """启动 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("start", id))
    db.add_audit_log(current_user["username"], "start_container", id)
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/stop")
async def stop_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """停止 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("kill", id))
    # 尝试更新容器状态
    rc_name, name_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", id))
    if rc_name == 0 and name_out.strip():
        db.update_container_state(name_out.strip().lstrip("/"), "exited")
    db.add_audit_log(current_user["username"], "stop_container", id)
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/restart")
async def restart_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """重启 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("restart", id))
    db.add_audit_log(current_user["username"], "restart_container", id)
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/rviz")
async def open_rviz(id: str, current_user: dict = Depends(require_permission('docker'))):
    """在容器中启动 RVIZ2 可视化工具（参考 ros2_docker_manager.py 的 open_rviz2 实现）"""
    try:
        import time
        debug_info = []

        # 获取容器默认用户
        rc_u, user_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", "whoami"))
        container_user = user_out.strip() if rc_u == 0 and user_out.strip() else "boonray"

        # 获取容器环境变量以获取 ROS_DOMAIN_ID
        rc, env_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Config.Env}}", id))
        domain_id = "0"
        if rc == 0 and env_out:
            match = re.search(r'ROS_DOMAIN_ID=(\d+)', env_out)
            if match:
                domain_id = match.group(1)
                debug_info.append(f"ROS_DOMAIN_ID={domain_id}")

        # 确保容器内有 X 服务器运行（rviz2 需要图形环境）
        rc_x, x_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "ps aux | grep -E '[X]vfb|[X]tigervnc|[X]org' | awk '{for(i=11;i<=NF;i++) if($i ~ /^:[0-9]+$/){print $i; exit}}'"
        ))
        if rc_x == 0 and x_out.strip().startswith(":"):
            display_num = x_out.strip()
            debug_info.append(f"复用已有 X server: DISPLAY={display_num}")
        else:
            display_num = ":99"
            # 从配置中读取 VNC 分辨率，默认 1920x1080
            vnc_geometry = CONFIG.get("visualization", {}).get("methods", {}).get("vnc", {}).get("geometry", "1920x1080")
            # 解析分辨率，Xvfb 需要 宽x高x色深 格式
            xvfb_screen = f"{vnc_geometry}x24" if 'x' in vnc_geometry and vnc_geometry.count('x') == 1 else "1920x1080x24"
            debug_info.append(f"未检测到 X 服务器，启动 Xvfb :99 ({xvfb_screen})...")
            DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", "-d", id, "bash", "-c",
                f"rm -f /tmp/.X{display_num.lstrip(':')}-lock && "
                f"Xvfb {display_num} -screen 0 {xvfb_screen} -ac +extension GLX +render -noreset > /log/xvfb.log 2>&1 &"))
            time.sleep(2)

        # 确保 xdotool/wmctrl 可用（用于最大化窗口）
        DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "export DEBIAN_FRONTEND=noninteractive && "
            "which wmctrl xdotool >/dev/null 2>&1 || "
            "(apt-get update -qq && apt-get install -y -qq wmctrl xdotool >/log/wmtools_install.log 2>&1)"
        ), timeout=120)

        # 查找/注入 rviz 配置（容器内 -> 宿主机 install -> 项目 data/simu.rviz）
        rviz_config = _resolve_rviz_config(id, container_user)
        if rviz_config:
            debug_info.append(f"使用 rviz 配置: {rviz_config}")
        else:
            debug_info.append("未找到 simu.rviz，使用默认空配置启动")

        # 如果 rviz2 已经在跑（连到任意 DISPLAY），先杀掉避免多窗口
        DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", container_user, id, "bash", "-c", "pkill -f rviz2 2>/dev/null || true"
        ))
        time.sleep(1)

        if rviz_config:
            rviz_cmd = (
                f"cd /home/boonray && source install/setup.bash && "
                f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                f"export LIBGL_ALWAYS_SOFTWARE=1 && export OGRE_RENDER_SYSTEM=OpenGL && "
                f"export QT_X11_NO_MITSHM=1 && "
                f"nohup rviz2 -d {rviz_config} > /log/rviz2.log 2>&1 &"
            )
        else:
            rviz_cmd = (
                f"cd /home/boonray && source install/setup.bash && "
                f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                f"export LIBGL_ALWAYS_SOFTWARE=1 && export OGRE_RENDER_SYSTEM=OpenGL && "
                f"export QT_X11_NO_MITSHM=1 && "
                f"nohup rviz2 > /log/rviz2.log 2>&1 &"
            )

        debug_info.append(f"执行命令: {rviz_cmd}")
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", container_user, "-d", id, "bash", "-c", rviz_cmd))

        # 等待 rviz 窗口出现后最大化
        _maximize_rviz(id, container_user, display_num, wait_seconds=8)
        time.sleep(1)

        # 检查 rviz2 进程是否启动
        rc_ps, ps_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", "ps aux | grep rviz2 | grep -v grep || echo NOT_RUNNING"))
        rviz_running = not ps_out.strip().endswith('NOT_RUNNING')

        db.add_audit_log(current_user["username"], "open_rviz", f"{id} - {' | '.join(debug_info)}")

        if rviz_running:
            debug_info.append("RVIZ2 进程已启动")
            return {"success": True, "message": f"已启动 RVIZ2 (domain_id={domain_id}, display={display_num})", "debug": debug_info}
        else:
            rc_log, log_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "cat", "/log/rviz2.log"))
            debug_info.append(f"进程未启动，日志内容: {log_out[:500]}")
            return {"success": False, "error": "RVIZ2 进程未启动，请检查日志", "debug": debug_info}
    except Exception as e:
        logger.error(f"启动 RVIZ2 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

@router.delete("/api/docker/container/{id}")
async def delete_container(id: str, force: bool = False, current_user: dict = Depends(require_permission('docker'))):
    """删除 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    # 反查容器名，删除后同步清理 containers 表
    rc_name, name_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", id))
    cmd = DockerManager._docker("rm") + (["-f"] if force else []) + [id]
    rc, out, err = DockerManager.run_cmd(cmd)
    if rc == 0 and rc_name == 0 and name_out.strip():
        db.remove_container_record(name_out.strip().lstrip("/"))
    db.add_audit_log(current_user["username"], "delete_container", f"{id} force={force}")
    return {"success": rc == 0, "message": out or err}

@router.get("/api/docker/container/{id}/logs")
async def container_logs(id: str, tail: int = 100, current_user: dict = Depends(require_permission('docker'))):
    """获取容器日志"""
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("logs", "--tail", str(tail), id))
    return {"success": rc == 0, "logs": out if rc == 0 else err}

@router.post("/api/docker/container/{id}/exec")
async def container_exec(id: str, data: Dict[str, str], current_user: dict = Depends(require_permission('docker'))):
    """在容器内执行命令"""
    if not id or id == "undefined":
        raise HTTPException(status_code=400, detail="无效的容器 ID")
    cmd = data.get("command")
    if not cmd:
        raise HTTPException(status_code=400, detail="缺少命令")
    # ★ bug2 修复：ros2 topic echo 需自动补 --once，避免持续输出导致终端阻塞
    stripped = cmd.strip()
    if stripped.startswith("ros2 topic echo") and "--once" not in cmd and "--head" not in cmd and "-n " not in cmd:
        # 仅在末尾无管道/重定向时补 --once
        if not any(op in cmd for op in ["|", ">", "<", "&"]):
            cmd = cmd + " --once"
    if not cmd.startswith("source"):
        container_install = ROS2_DEFAULT["container_install"]
        full_cmd = f"bash -c 'source {container_install}/setup.bash && {cmd}'"
    else:
        full_cmd = f"bash -c '{cmd}'"
    rc, out, err = DockerManager.exec_command(id, full_cmd)
    db.add_audit_log(current_user["username"], "container_exec", f"{id} -> {cmd}")
    return {"success": rc == 0, "stdout": out, "stderr": err}


@router.get("/api/docker/container/{id}/roslogs")
async def container_roslogs(id: str, tail: int = 200, current_user: dict = Depends(require_permission('docker'))):
    """读取容器对应的宿主机 ROS2 日志文件（~/robotruck_ros2/Docker/logs/{容器名}_*.log）

    用于解决 `docker logs` 仅显示容器 stdout/stderr 而无法读取 ROS2 节点日志的问题。
    """
    # 1. 取容器名
    rc, name_out, name_err = DockerManager.run_cmd(
        DockerManager._docker("inspect", "--format", "{{.Name}}", id)
    )
    container_name = (name_out or "").strip().lstrip("/") if rc == 0 else ""

    workspace_paths = get_user_workspace_paths(current_user)
    logs_dir = workspace_paths["logs_dir"]
    candidates: List[str] = []
    if container_name:
        candidates.extend(sorted(glob.glob(os.path.join(logs_dir, f"{container_name}_*.log"))))
        candidates.extend(sorted(glob.glob(os.path.join(logs_dir, f"{container_name}.log"))))
    # 兜底：取 logs 目录中最近修改的 5 个 .log 文件
    all_logs = sorted(
        glob.glob(os.path.join(logs_dir, "*.log")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for f in all_logs:
        if f not in candidates:
            candidates.append(f)

    logs_content = ""
    used_file = ""
    for cand in candidates[:3]:
        try:
            if not os.path.isfile(cand):
                continue
            with open(cand, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail_lines = lines[-tail:] if tail > 0 else lines
            logs_content += f"\n===== {os.path.basename(cand)} =====\n" + "".join(tail_lines)
            used_file = cand
            break
        except Exception as e:
            logger.warning(f"读取容器日志文件失败: {cand}, {e}")
            continue

    if not logs_content:
        return {
            "success": False,
            "error": f"未找到容器 {container_name or id} 对应的日志文件（查找目录: {logs_dir}）",
            "logs_dir": logs_dir,
            "container_name": container_name,
        }

    return {
        "success": True,
        "logs": logs_content,
        "log_file": used_file,
        "container_name": container_name,
        "logs_dir": logs_dir,
    }

@router.post("/api/docker/container/{id}/update")
async def container_update(id: str, data: Dict[str, Any], current_user: dict = Depends(require_permission('docker'))):
    """更新容器资源限制"""
    cpus = data.get("cpus")
    mem = data.get("memory_gb")
    rc, out, err = DockerManager.update_resources(id, cpus, mem)
    db.add_audit_log(current_user["username"], "container_update", f"{id} cpu={cpus} mem={mem}GB")
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/stop-all-ros2")
async def stop_all_ros2(current_user: dict = Depends(require_permission('docker'))):
    """停止所有 ROS2 容器（普通用户仅停止自己启动的容器，管理员停止全部）"""
    # 普通用户权限隔离：只停止当前用户创建的容器
    visible_names = db.get_visible_container_names(current_user)
    if visible_names is None:
        # admin 或 JSON 模式：停止所有 ros2_ 前缀容器
        results = DockerManager.stop_all_ros2_containers()
        scope = f"{len(results)} containers (all)"
    else:
        # 普通用户：仅停止自己启动的 ros2_ 前缀容器
        results = DockerManager.stop_all_ros2_containers(container_names=list(visible_names))
        scope = f"{len(results)} containers (own)"
    db.add_audit_log(current_user["username"], "stop_all_ros2", scope)
    return {"success": True, "results": [{"name": r[0], "ok": r[1]} for r in results]}

@router.post("/api/docker/sync-time")
async def sync_time(current_user: dict = Depends(require_permission('docker'))):
    """同步宿主机时间到所有运行中容器"""
    containers = DockerManager.list_containers(running_only=True)
    success = []
    failed = []
    for c in containers:
        name = c["name"]
        cmd = DockerManager._docker("cp", "/etc/localtime", f"{name}:/etc/localtime")
        rc, out, err = DockerManager.run_cmd(cmd)
        if rc == 0:
            success.append(name)
        else:
            failed.append(name)
    db.add_audit_log(current_user["username"], "sync_time", f"success={len(success)}, failed={len(failed)}")
    return {"success": True, "success_list": success, "failed_list": failed}

@router.post("/api/docker/container/{id}/commit")
async def commit_container(id: str, data: Dict[str, str], current_user: dict = Depends(require_permission('advanced-docker'))):
    """将容器变更提交为新镜像"""
    repo = data.get("repository", "custom_image")
    tag = data.get("tag", "latest")
    message = data.get("message", "")
    image_name = f"{repo}:{tag}"
    cmd = DockerManager._docker("commit")
    if message:
        cmd.extend(["-m", message])
    cmd.extend([id, image_name])
    rc, out, err = DockerManager.run_cmd(cmd, timeout=60)
    db.add_audit_log(current_user["username"], "commit_container", f"{id} -> {image_name}")
    return {"success": rc == 0, "image": image_name if rc == 0 else "", "message": out or err}

@router.get("/api/docker/container/{id}/foxglove-url")
async def get_foxglove_url(id: str, current_user: dict = Depends(require_permission('docker'))):
    """获取 Foxglove Studio 可视化 URL"""
    container_ip = DockerManager.get_container_info(id, "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
    if not container_ip:
        return {"success": False, "error": "无法获取容器IP"}
    
    host_ip = get_host_ip()
    config = VISUALIZATION_METHODS.get("foxglove", {})
    container_port = config.get("container_port", config.get("port", 9090))
    host_port = get_host_port(id, container_port)
    if not host_port:
        host_port = str(config.get("port", 9090))
    
    bridge_url = f"ws://{host_ip}:{host_port}"
    foxglove_url = f"https://studio.foxglove.dev/?ds=foxglove-websocket&ds.url={bridge_url}"
    return {"success": True, "foxglove_url": foxglove_url, "bridge_url": bridge_url, "container_ip": container_ip.strip(), "host_ip": host_ip, "host_port": host_port}

# ---------- 可视化方案 API ----------
@router.get("/api/visualization/methods")
async def get_visualization_methods(current_user: dict = Depends(require_permission('docker'))):
    """获取所有可用的可视化方案配置"""
    methods = {}
    for key, config in VISUALIZATION_METHODS.items():
        methods[key] = {
            "name": config.get("name", key),
            "description": config.get("description", ""),
            "enabled": config.get("enabled", False)
        }
    # 获取顺序配置，默认为所有方法的key列表
    order = VISUALIZATION_CONFIG.get("order", list(VISUALIZATION_METHODS.keys()))
    return {
        "success": True,
        "default_method": DEFAULT_VISUALIZATION_METHOD,
        "methods": methods,
        "order": order
    }

@router.post("/api/visualization/set-default")
async def set_default_visualization_method(method: str, current_user: dict = Depends(require_permission('admin'))):
    """设置默认可视化方案"""
    if method not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method}"}
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        cfg["visualization"]["default_method"] = method
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    
    global DEFAULT_VISUALIZATION_METHOD
    DEFAULT_VISUALIZATION_METHOD = method
    
    return {"success": True, "message": f"已设置默认可视化方案为: {VISUALIZATION_METHODS[method].get('name', method)}"}

@router.post("/api/visualization/method/{method_key}")
async def update_visualization_method(method_key: str, config: dict = Body(...), current_user: dict = Depends(require_permission('admin'))):
    """更新可视化方案配置"""
    if method_key not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method_key}"}
    
    # 更新内存中的配置
    if "enabled" in config:
        VISUALIZATION_METHODS[method_key]["enabled"] = config["enabled"]
    if "name" in config:
        VISUALIZATION_METHODS[method_key]["name"] = config["name"]
    if "description" in config:
        VISUALIZATION_METHODS[method_key]["description"] = config["description"]
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        if "methods" not in cfg["visualization"]:
            cfg["visualization"]["methods"] = {}
        if method_key not in cfg["visualization"]["methods"]:
            cfg["visualization"]["methods"][method_key] = {}
        
        if "enabled" in config:
            cfg["visualization"]["methods"][method_key]["enabled"] = config["enabled"]
        if "name" in config:
            cfg["visualization"]["methods"][method_key]["name"] = config["name"]
        if "description" in config:
            cfg["visualization"]["methods"][method_key]["description"] = config["description"]
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    
    return {
        "success": True, 
        "message": f"已更新可视化方案: {VISUALIZATION_METHODS[method_key].get('name', method_key)}",
        "method": {
            "key": method_key,
            "name": VISUALIZATION_METHODS[method_key].get("name", method_key),
            "description": VISUALIZATION_METHODS[method_key].get("description", ""),
            "enabled": VISUALIZATION_METHODS[method_key].get("enabled", False)
        }
    }

@router.post("/api/visualization/order")
async def update_visualization_order(order: list = Body(...), current_user: dict = Depends(require_permission('admin'))):
    """更新可视化方案顺序"""
    # 验证顺序中的所有key都有效
    for key in order:
        if key not in VISUALIZATION_METHODS:
            return {"success": False, "error": f"未知的可视化方案: {key}"}
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        cfg["visualization"]["order"] = order
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    
    return {"success": True, "message": "可视化方案顺序已更新", "order": order}

@router.post("/api/docker/container/{id}/visualize")
async def visualize_container(id: str, method: str = None, request: Request = None, current_user: dict = Depends(require_permission('docker'))):
    """启动容器可视化"""
    if method is None:
        method = DEFAULT_VISUALIZATION_METHOD
    
    if method not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method}"}
    
    method_config = VISUALIZATION_METHODS[method]
    if not method_config.get("enabled", False):
        return {"success": False, "error": f"可视化方案 {method} 未启用"}
    
    container_info = DockerManager.get_container_info(id, "{{.State.Running}}")
    if not container_info or "true" not in container_info.lower():
        return {"success": False, "error": "容器未运行，无法启动可视化"}

    scheme = "http"
    host_ip = get_host_ip()

    # v3.6: Foxglove 已注释，仅保留 vnc 和 rviz_x11（均通过容器内 noVNC 实现）
    # 两个方法共用容器内的 Xvfb + x11vnc + noVNC 方案，vnc 打开纯桌面，rviz_x11 自动启动 rviz2
    if method == "foxglove":
        # return await start_foxglove_visualization(id, container_ip, scheme)
        return {"success": False, "error": "Foxglove 已禁用，请使用 VNC 远程桌面或原生 RVIZ"}
    elif method == "vnc":
        return await start_vnc_visualization(id, host_ip, scheme, auto_start_rviz=False)
    elif method == "rviz_x11":
        return await start_vnc_visualization(id, host_ip, scheme, auto_start_rviz=True)
    else:
        return {"success": False, "error": f"未实现的可视化方案: {method}"}

def get_host_ip():
    """获取宿主机IP地址"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_host_port(container_id, container_port):
    """获取容器端口映射到宿主机的端口"""
    try:
        cmd = DockerManager._docker("port", container_id, str(container_port))
        rc, out, _ = DockerManager.run_cmd(cmd)
        if rc == 0 and out.strip():
            lines = out.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line and ":" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        return parts[-1]
    except Exception as e:
        pass
    return None

async def start_foxglove_visualization(id, container_ip, scheme="http"):
    """启动 Foxglove Studio 可视化"""
    host_ip = get_host_ip()
    config = VISUALIZATION_METHODS["foxglove"]
    container_port = config.get("container_port", config.get("port", 9090))
    host_port = get_host_port(id, container_port)
    
    # 如果没有端口映射，尝试获取容器端口
    if not host_port:
        host_port = str(container_port)
    
    # 检查 rosbridge 是否运行
    rc, out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", 
        f"source /opt/ros/humble/setup.bash && ros2 node list 2>/dev/null | grep -i rosbridge || true"))
    
    if not out.strip():
        # 检查 rosbridge 是否安装
        rc_check, out_check, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", 
            "source /opt/ros/humble/setup.bash && ros2 pkg list 2>/dev/null | grep -i rosbridge || true"))
        if not out_check.strip():
            # 安装 rosbridge_server
            DockerManager.run_cmd(DockerManager._docker("exec", "-d", id, "bash", "-c", 
                "source /opt/ros/humble/setup.bash && apt-get update && apt-get install -y ros-humble-rosbridge-server"))
        
        # 启动 rosbridge_server
        cmd = f"source /opt/ros/humble/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml > /tmp/rosbridge.log 2>&1 &"
        DockerManager.run_cmd(DockerManager._docker("exec", "-d", id, "bash", "-c", cmd))
        # 等待启动
        import time
        time.sleep(5)
    
    # 根据请求协议生成正确的WebSocket URL
    ws_scheme = "wss" if scheme == "https" else "ws"
    bridge_url = f"{ws_scheme}://{host_ip}:{host_port}"
    foxglove_url = f"https://studio.foxglove.dev/?ds=foxglove-websocket&ds.url={bridge_url}"
    
    return {
        "success": True,
        "method": "foxglove",
        "name": "Foxglove Studio",
        "url": foxglove_url,
        "bridge_url": bridge_url,
        "container_ip": container_ip,
        "host_ip": host_ip,
        "host_port": host_port,
        "message": "Foxglove Studio URL 已生成，请点击链接打开。打开后在 Foxglove 中添加数据源选择 WebSocket 连接。"
    }

def find_available_port():
    """查找一个可用的空闲端口"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

def run_host_cmd(cmd, timeout=30, background=False):
    """在宿主机上执行命令（不添加docker前缀）"""
    import subprocess
    try:
        if isinstance(cmd, str):
            if background:
                pass
            else:
                cmd = cmd.split()
        if not background and USE_SUDO and cmd[0] not in ['sudo', 'which', 'bash']:
            cmd = ['sudo'] + cmd
        
        if background:
            if isinstance(cmd, list):
                cmd = ' '.join(cmd)
            full_cmd = cmd
            if USE_SUDO and not cmd.startswith('sudo ') and not cmd.startswith('which ') and not cmd.startswith('bash '):
                full_cmd = 'sudo ' + full_cmd
            proc = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return 0, str(proc.pid), ""
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)

def check_host_command(cmd):
    """检查宿主机上是否有某个命令"""
    rc, _, _ = run_host_cmd(["which", cmd])
    return rc == 0

async def start_vnc_visualization(id, host_ip, scheme="http", auto_start_rviz=False):
    """启动容器内 VNC 远程桌面可视化（含 noVNC）。

    v3.6 重写：
    - 根据容器 ID 哈希动态分配 DISPLAY 号（:99~:199），避免多容器共享
      /tmp/.X11-unix 时 Xvfb socket 冲突导致画面串台。
    - 若容器已有 Xvfb 进程则复用其 display。
    - 在容器内以 root 启动 x11vnc（attach 到该 DISPLAY）和 websockify/noVNC（监听 6080）。
    - 容器通过 docker-compose 映射 6080→宿主机固定端口（如 ros2_fz001→6100），
      宿主机无需安装任何软件，直接访问宿主机端口即可打开 noVNC。
    - rviz2 使用容器默认用户（boonray）在目标 DISPLAY 上启动。
    """
    import time
    container_vnc_port = 5901
    container_web_port = 6080

    # 获取容器默认运行用户（用于启动 rviz2）
    rc, container_user, _ = DockerManager.run_cmd(DockerManager._docker(
        "exec", id, "bash", "-c", "whoami"
    ))
    container_user = container_user.strip() if rc == 0 and container_user.strip() else "boonray"

    # 获取 DISPLAY 号：优先级 1) 容器已有 Xvfb 进程 -> 复用；2) 容器标签 ros2.display -> 使用预设；3) 动态哈希分配
    # 新版脚本（2026-07）不再挂载宿主机 /tmp/.X11-unix，每个容器完全独立，Xvfb 在容器启动时已启动
    rc, xvfb_out, _ = DockerManager.run_cmd(DockerManager._docker(
        "exec", "-u", "root", id, "bash", "-c",
        "ps aux | grep '[X]vfb' | grep -oP 'Xvfb \\K:\\d+' | head -1"
    ))
    if xvfb_out.strip():
        display_num = xvfb_out.strip()
        need_start_xvfb = False
        logger.info(f"[{id}] 容器内已有 Xvfb {display_num} 运行，复用之")
    else:
        # 优先检查容器标签中预设的 display
        rc, label_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "inspect", "-f", "{{index .Config.Labels \"ros2.display\"}}", id
        ))
        if rc == 0 and label_out.strip() and label_out.strip() != "<no value>":
            display_num = label_out.strip()
            if not display_num.startswith(":"):
                display_num = ":" + display_num
            need_start_xvfb = False
            logger.info(f"[{id}] 使用容器标签预设的 DISPLAY={display_num}，Xvfb 应已启动")
        else:
            # 回退：动态哈希分配（兼容旧容器）
            import hashlib
            base_display = 99 + (int(hashlib.md5(id.encode()).hexdigest(), 16) % 100)
            display_num = f":{base_display}"
            for offset in range(0, 100):
                d = base_display + offset
                rc, chk, _ = DockerManager.run_cmd(DockerManager._docker(
                    "exec", "-u", "root", id, "bash", "-c",
                    f"test -e /tmp/.X11-unix/X{d} && echo EXISTS || echo FREE"
                ))
                if 'FREE' in chk:
                    display_num = f":{d}"
                    break
            need_start_xvfb = True
            logger.info(f"[{id}] 未检测到预设 DISPLAY，动态分配 Xvfb {display_num} 虚拟显示")

    # 1) 检查 VNC(5901) / noVNC(6080) 端口是否在监听
    def port_listening(port):
        rc, out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"netstat -tln 2>/dev/null | grep -q ':{port} ' && echo YES || echo NO"
        ))
        return 'YES' in out

    vnc_listening = port_listening(container_vnc_port)
    web_listening = port_listening(container_web_port)
    services_running = vnc_listening and web_listening

    if not services_running:
        # 2) 以 root 在容器内安装必要软件（缺则装）
        rc, which_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "which Xvfb x11vnc websockify >/dev/null 2>&1 && echo ALL_PRESENT || echo NEED_INSTALL"
        ))
        if 'NEED_INSTALL' in which_out:
            logger.info(f"[{id}] 容器内缺少 VNC 组件，开始 root 安装...")
            install_cmd = (
                "export DEBIAN_FRONTEND=noninteractive && "
                "apt-get update -qq && "
                "apt-get install -y -qq xvfb x11vnc novnc websockify x11-utils wmctrl xdotool "
                "> /log/vnc_install.log 2>&1 && "
                "echo INSTALL_OK >> /log/vnc_install.log"
            )
            rc, out, err = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c", install_cmd
            ), timeout=180)
            logger.info(f"[{id}] 容器内安装包 rc={rc}, err={err[:200] if err else ''}")

        # 3) 若需要，启动 Xvfb
        if need_start_xvfb:
            disp_n = display_num.lstrip(":")
            # 从配置中读取 VNC 分辨率，默认 1920x1080
            vnc_geometry = CONFIG.get("visualization", {}).get("methods", {}).get("vnc", {}).get("geometry", "1920x1080")
            xvfb_screen = f"{vnc_geometry}x24" if 'x' in vnc_geometry and vnc_geometry.count('x') == 1 else "1920x1080x24"
            DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c",
                f"rm -f /tmp/.X{disp_n}-lock && "
                f"Xvfb {display_num} -screen 0 {xvfb_screen} -ac +extension GLX +render -noreset "
                f"> /log/xvfb.log 2>&1 &"
            ))
            time.sleep(2)

        # 4) 启动 x11vnc（attach 到目标 DISPLAY，监听 5901）
        # -noshm 解决容器内 X MIT-SHM 权限问题；-noxdamage 避免部分 X server 崩溃
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c",
            f"x11vnc -display {display_num} -rfbport {container_vnc_port} -forever -shared -nopw "
            f"-noxdamage -ncache 0 -rfbwait 30000 -noshm -bg -o /log/x11vnc.log"
        ))
        time.sleep(2)

        # 检查 x11vnc 是否监听
        rc, chk_vnc, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"netstat -tln 2>/dev/null | grep -q ':{container_vnc_port} ' && echo LISTEN || echo NOT_LISTEN"
        ))
        if 'NOT_LISTEN' in chk_vnc:
            logger.warning(f"[{id}] x11vnc 首次启动未监听，查看日志")
            rc, log_out, _ = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c", "tail -20 /log/x11vnc.log"
            ))
            logger.warning(f"[{id}] x11vnc log: {log_out[:500]}")

        # 5) 启动 websockify + novnc（监听 0.0.0.0:6080）
        rc, np_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "for p in /usr/share/novnc /usr/share/www/novnc; do "
            "[ -d $p ] && echo $p && break; done"
        ))
        novnc_path = np_out.strip() if rc == 0 and np_out.strip() else "/usr/share/novnc"
        rc, wsbin_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "which websockify || (ls /usr/share/novnc/utils/websockify/run 2>/dev/null) || echo websockify"
        ))
        wsbin = wsbin_out.strip().split('\n')[0] if wsbin_out.strip() else "websockify"

        ws_launch_cmd = (
            f"cd {novnc_path} && "
            f"nohup {wsbin} --web={novnc_path} 0.0.0.0:{container_web_port} localhost:{container_vnc_port} "
            f"> /log/novnc.log 2>&1 &"
        )
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c", ws_launch_cmd))
        time.sleep(3)

        # 等待 6080 监听
        for _ in range(8):
            rc, chk, _ = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c",
                f"netstat -tln 2>/dev/null | grep -q ':{container_web_port} ' && echo LISTEN || echo NOT_LISTEN"
            ))
            if 'LISTEN' in chk:
                logger.info(f"[{id}] 容器内 {container_web_port} 已监听")
                break
            time.sleep(2)

    # 6) 获取容器 6080 映射到宿主机的端口
    host_web_port = get_host_port(id, container_web_port)
    if not host_web_port:
        host_web_port = str(container_web_port)
        logger.warning(f"[{id}] 容器 6080 端口未映射到宿主机，回退到容器端口")

    # 7) 自动启动 rviz2（仅 rviz_x11 模式，用容器默认用户）
    #    关键：必须确保 rviz2 运行在 VNC 可见的 DISPLAY（display_num）上。
    #    如果 rviz2 已经在错误的 display（如 :0 宿主机 X）上运行，需要杀掉后在正确 display 重启。
    if auto_start_rviz:
        # 检查当前 DISPLAY 上是否有 rviz2 窗口
        rc, win_check, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"DISPLAY={display_num} xwininfo -root -children 2>/dev/null | grep -i rviz | head -1 || echo NO_RVIZ_WIN"
        ))
        rviz_on_correct_display = 'rviz' in win_check.lower() and 'NO_RVIZ_WIN' not in win_check

        # 检查是否有 rviz2 进程在跑
        rc, rviz_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", container_user, id, "bash", "-c",
            f"ps -u $(id -u) -o pid=,comm=,args= | grep -v grep | grep rviz2 || echo NOT_RUNNING"
        ))
        rviz_running = 'NOT_RUNNING' not in rviz_out

        # 如果 rviz2 跑错了 display（VNC 屏幕上看不到），先杀掉旧进程
        need_restart_rviz = rviz_running and not rviz_on_correct_display
        if need_restart_rviz:
            logger.info(f"[{id}] rviz2 运行中但不在 DISPLAY={display_num} 上（可能连到了宿主机 :0），将在正确 display 重启")
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", container_user, id, "bash", "-c",
                "pkill -f rviz2; sleep 1"
            ))
            rviz_running = False

        if not rviz_running:
            # 获取 ROS_DOMAIN_ID
            rc, env_out, _ = DockerManager.run_cmd(DockerManager._docker(
                "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", id
            ))
            domain_id = "0"
            if env_out:
                m = re.search(r'ROS_DOMAIN_ID=(\d+)', env_out)
                if m:
                    domain_id = m.group(1)

            # 确保 wmctrl/xdotool 已存在（用于后续最大化 rviz 窗口）
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c",
                "export DEBIAN_FRONTEND=noninteractive && "
                "which wmctrl xdotool >/dev/null 2>&1 || "
                "(apt-get update -qq && apt-get install -y -qq wmctrl xdotool >/log/wmtools_install.log 2>&1)"
            ), timeout=120)

            # 查找/注入 rviz 配置（优先用户 install 内，找不到则回退到宿主机 data/simu.rviz）
            rviz_config = _resolve_rviz_config(id, container_user)

            if rviz_config:
                rviz_cmd = (
                    f"cd /home/boonray && source install/setup.bash && "
                    f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                    f"export LIBGL_ALWAYS_SOFTWARE=1 && export QT_X11_NO_MITSHM=1 && "
                    f"nohup rviz2 -d {rviz_config} > /log/rviz2.log 2>&1 &"
                )
            else:
                rviz_cmd = (
                    f"cd /home/boonray && source install/setup.bash && "
                    f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                    f"export LIBGL_ALWAYS_SOFTWARE=1 && export QT_X11_NO_MITSHM=1 && "
                    f"nohup rviz2 > /log/rviz2.log 2>&1 &"
                )
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", container_user, id, "bash", "-c", rviz_cmd
            ))
            time.sleep(2)
            # 等待 rviz 窗口出现并最大化、移到 (0,0)，避免配置文件里保存的 1692x1094@(437,118)
            # 导致右侧面板被截断在 Xvfb 1920x1080 屏幕外
            _maximize_rviz(id, container_user, display_num, wait_seconds=8)
        elif rviz_running and rviz_on_correct_display:
            # rviz2 已经在正确 DISPLAY 上运行，可能是之前启动时窗口位置/尺寸偏移，补一次最大化
            _maximize_rviz(id, container_user, display_num, wait_seconds=2)

    # 8) 构建访问 URL
    #    novnc 不同版本 websocket 路径可能是 /websockify 或 /，URL 用 vnc.html 默认参数即可自动连接
    web_vnc_url = f"{scheme}://{host_ip}:{host_web_port}/vnc.html?autoconnect=true&resize=scale&path=websockify"
    method_name = "原生 RVIZ (X11)" if auto_start_rviz else "VNC 远程桌面"
    msg = f"{method_name} 已启动！Web 访问地址: {web_vnc_url}（无需密码，DISPLAY={display_num}"
    if auto_start_rviz:
        msg += "，rviz2 已自动启动"
    msg += "）"

    return {
        "success": True,
        "method": "rviz_x11" if auto_start_rviz else "vnc",
        "name": method_name,
        "url": web_vnc_url,
        "host_ip": host_ip,
        "host_web_port": host_web_port,
        "display": display_num,
        "message": msg,
    }

# v3.6: 旧版 start_rviz_x11_visualization 已废弃，功能合并到 start_vnc_visualization(auto_start_rviz=True)
# async def start_rviz_x11_visualization(...): 保留空实现占位避免代码引用出错
async def start_rviz_x11_visualization(*args, **kwargs):
    """Deprecated: 已合并到 start_vnc_visualization(auto_start_rviz=True)。"""
    host_ip = get_host_ip()
    cid = args[0] if args else kwargs.get('id')
    return await start_vnc_visualization(cid, host_ip, kwargs.get('scheme', 'http'), auto_start_rviz=True)

# ---------- Docker 镜像 ----------
@router.get("/api/docker/images")
async def list_images(current_user: dict = Depends(require_permission('docker'))):
    """列出 Docker 镜像"""
    cmd = DockerManager._docker("images", "--format", "json")
    rc, out, err = DockerManager.run_cmd(cmd)
    if rc != 0:
        return {"success": False, "error": err}
    images = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            img = json.loads(line)
            repo = img.get("Repository", "")
            tag = img.get("Tag", "")
            if repo == "<none>" and tag == "<none>":
                continue
            tags = [f"{repo}:{tag}"]
            img_id = img.get("ID", "")
            size_bytes = parse_size(img.get("Size", "0B"))
            images.append({"tags": tags, "id": img_id, "size": size_bytes})
        except json.JSONDecodeError:
            continue
    return {"success": True, "images": images}

@router.post("/api/docker/images/load")
async def load_image(
    file: UploadFile = File(None),
    path: str = Body(None),
    current_user: dict = Depends(require_permission('images'))
):
    """加载 Docker 镜像，支持文件上传或本地路径"""
    # 优先处理文件上传
    if file is not None:
        suffix = os.path.splitext(file.filename or "")[1].lower()
        if suffix not in ('.tar', '.tgz'):
            raise HTTPException(400, "仅支持 .tar 或 .tgz 文件")
        tmp_path = os.path.join(tempfile.gettempdir(), f"docker_load_{int(time.time())}{suffix}")
        try:
            with open(tmp_path, 'wb') as f:
                shutil.copyfileobj(file.file, f)
            rc, out, err = DockerManager.load_image(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        db.add_audit_log(current_user["username"], "load_image", file.filename)
        return {"success": rc == 0, "message": out or err}

    # 兼容本地路径方式
    if not path or not os.path.isfile(path):
        raise HTTPException(400, "文件不存在")
    rc, out, err = DockerManager.load_image(path)
    db.add_audit_log(current_user["username"], "load_image", path)
    return {"success": rc == 0, "message": out or err}

@router.delete("/api/docker/images/{name}")
async def delete_image(name: str, current_user: dict = Depends(require_permission('images'))):
    """删除 Docker 镜像"""
    rc, out, err = DockerManager.remove_image(name)
    db.add_audit_log(current_user["username"], "delete_image", name)
    return {"success": rc == 0, "message": out or err}

# ---------- 脚本管理 ----------
@router.get("/api/scripts/launch-files")
async def get_launch_files(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取 launch 文件列表（按用户工作空间隔离）"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    launch_dir = workspace_paths["launch_dir"]
    if not os.path.isdir(launch_dir):
        return {"success": False, "error": f"目录不存在: {launch_dir}"}
    files = [f for f in os.listdir(launch_dir) if f.endswith('.py')]
    return {"success": True, "files": [{"name": f} for f in files], "launch_dir": launch_dir}

@router.post("/api/scripts/generate")
async def generate_scripts(data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """生成 ROS2 启动脚本（固定端口映射 + 索引管理 + 角色配额）

    安全：launch_dir / scripts_dir / logs_dir 强制使用用户工作空间路径，
    不接受客户端传入的值，防止越权访问其他用户的 install 目录。
    配额：管理员最多 10 辆，普通用户最多 5 辆，全局上限 25 辆。
    端口：VNC = 5900 + 车辆索引，Web = 6080 + 车辆索引。
    """
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]

    if not os.path.isdir(host_install):
        return {"success": False, "error": f"安装目录不存在: {host_install}，请先上传 install.zip 安装包"}

    # ★★★ 安全修复：路径强制使用工作空间路径，不接受客户端覆盖 ★★★
    launch_dir = workspace_paths["launch_dir"]
    scripts_dir = workspace_paths["scripts_dir"]
    logs_dir = workspace_paths["logs_dir"]
    # 校验所有路径均在用户工作空间内
    validate_user_path(launch_dir, current_user, target_user=target_user)
    validate_user_path(scripts_dir, current_user, target_user=target_user)
    validate_user_path(logs_dir, current_user, target_user=target_user)
    validate_user_path(host_install, current_user, target_user=target_user)

    cfg = {
        "launch_dir": launch_dir,
        "scripts_dir": scripts_dir,
        "logs_dir": logs_dir,
        "host_install": host_install,
        "host_ws": workspace_paths["host_ws"],
        "container_install": workspace_paths["container_install"],
        "bag_storage": workspace_paths["bag_storage"],
        "container_bag_path": workspace_paths["container_bag_path"],
        "container_bag_path_alt": workspace_paths["container_bag_path_alt"],
        "docker_image": data.get("docker_image", ROS2_DEFAULT["docker_image"]),
        "default_host_install": ROS2_DEFAULT["host_install"],
    }
    try:
        user_role = current_user.get("role", "user")
        gen = ROS2ScriptGenerator(cfg, user_paths=workspace_paths, user_role=user_role)
        ids, port_warnings = gen.generate()
        db.add_audit_log(current_user["username"], "generate_scripts", f"{len(ids)} scripts")
        # 容器名带 owner 段（与脚本生成器派生规则一致）
        owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
        return {
            "success": True,
            "warnings": port_warnings,
            "host_install": host_install,
            "generated": [{"name": f"start_docker_ros2_{id}.sh", "container": f"ros2_{owner}_{id}", "domain_id": "auto"} for id in ids]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 安装包上传、检测、目录树
# ============================================================
@router.get("/api/install/status")
async def get_install_status(target_user: Optional[str] = None, refresh: Optional[bool] = False, current_user: dict = Depends(get_current_user)):
    """检测当前用户 install 目录状态（带 5 秒缓存）

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间。
    ``refresh=true`` 时强制跳过缓存，切换用户等场景使用。
    """
    cache_key = f"install_status:{current_user['email']}:{target_user or 'self'}"
    if not refresh:
        cached = _memory_cache.get(cache_key)
        if cached:
            return cached

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]
    host_ws = workspace_paths["host_ws"]

    exists = os.path.isdir(host_install)
    has_setup_bash = os.path.isfile(os.path.join(host_install, "setup.bash")) if exists else False
    tree = build_dir_tree(host_install, max_depth=2) if exists else None

    # v3.6：检测各工作目录的存在状态，用于前端提示
    dirs_status = {
        "install": {"path": host_install, "exists": exists},
        "bk":      {"path": workspace_paths["backup_dir"],   "exists": os.path.isdir(workspace_paths["backup_dir"])},
        "bags":    {"path": workspace_paths["bag_storage"],  "exists": os.path.isdir(workspace_paths["bag_storage"])},
        "logs":    {"path": workspace_paths["logs_dir"],     "exists": os.path.isdir(workspace_paths["logs_dir"])},
        "scripts": {"path": workspace_paths["scripts_dir"],  "exists": os.path.isdir(workspace_paths["scripts_dir"])},
    }

    result = {
        "success": True,
        "exists": exists,
        "has_setup_bash": has_setup_bash,
        "host_install": host_install,
        "host_ws": host_ws,
        "host_bk": workspace_paths["backup_dir"],
        "host_bags": workspace_paths["bag_storage"],
        "host_logs": workspace_paths["logs_dir"],
        "host_scripts": workspace_paths["scripts_dir"],
        "host_bk_backups": workspace_paths["bk_backups_dir"],
        "dirs_status": dirs_status,
        "tree": tree,
        "target_user": workspace_paths.get("target_user"),
        "message": "安装包已就绪" if has_setup_bash else ("install目录存在但setup.bash缺失，请重新上传" if exists else "未检测到安装包，请上传 install.zip / .tar.gz / .tgz / .tar.bz2")
    }
    _memory_cache.set(cache_key, result, ttl=5)
    return result


@router.post("/api/install/upload")
async def upload_install_package(
    file: UploadFile = File(...),
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission("scripts"))
):
    """上传并解压 install 安装包

    v3.6：支持 .zip / .tar.gz / .tgz / .tar.bz2 多种压缩格式；
    管理员可通过 ``target_user`` 切换到目标用户空间代为上传。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    host_install = workspace_paths["host_install"]

    filename = (file.filename or "").lower()
    supported_ext = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar")
    if not filename.endswith(supported_ext):
        return {"success": False, "error": f"仅支持以下格式压缩包: {', '.join(supported_ext)}"}

    os.makedirs(host_ws, exist_ok=True)

    # 根据扩展名生成临时文件名（保留原扩展，便于解压器识别）
    ext = ".zip"
    for cand in (".tar.gz", ".tar.bz2", ".tgz", ".tar", ".zip"):
        if filename.endswith(cand):
            ext = cand
            break
    tmp_path = os.path.join(host_ws, f"_upload_{uuid.uuid4().hex}{ext}")
    try:
        size = 0
        with open(tmp_path, "wb") as f:
            while chunk := await file.read(8 * 1024 * 1024):
                f.write(chunk)
                size += len(chunk)
                if size > 5 * 1024 * 1024 * 1024:
                    raise HTTPException(413, "安装包大小超过 5GB 限制")

        if os.path.isdir(host_install):
            backup_dir = os.path.join(host_ws, f"install.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.move(host_install, backup_dir)

        try:
            extract_and_flatten(tmp_path, host_install)
        except (zipfile.BadZipFile, tarfile.TarError, ValueError) as e:
            return {"success": False, "error": f"压缩包损坏或格式不正确: {e}"}

        if not os.path.isfile(os.path.join(host_install, "setup.bash")):
            return {
                "success": False,
                "error": "解压后未找到 setup.bash，请确保压缩包为正确的 ROS2 install 目录结构",
                "host_install": host_install
            }

        _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")

        tree = build_dir_tree(host_install, max_depth=2)
        audit_target = workspace_paths.get("target_user")
        audit_details = f"size={size} target={audit_target or 'self'}"
        db.add_audit_log(current_user["username"], "install_upload", audit_details)
        return {
            "success": True,
            "message": "安装包上传并解压成功",
            "host_install": host_install,
            "target_user": audit_target,
            "tree": tree
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传安装包失败: {e}", exc_info=True)
        return {"success": False, "error": f"处理失败: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.get("/api/install/tree")
async def get_install_tree(target_user: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """获取 install 目录树"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]
    if not os.path.isdir(host_install):
        return {"success": False, "error": "install 目录不存在"}
    return {"success": True, "tree": build_dir_tree(host_install, max_depth=3), "host_install": host_install}


@router.post("/api/install/delete")
async def delete_install_package(
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission("scripts"))
):
    """删除用户空间自己的install安装包
    普通用户只能删除自己空间的install，管理员可通过target_user删除指定用户的install
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]
    host_ws = workspace_paths["host_ws"]
    
    # 检查是否是删除自己的空间，或者是管理员
    is_admin = current_user.get("role") == "admin"
    target = workspace_paths.get("target_user")
    if target and not is_admin:
        return {"success": False, "error": "普通用户只能删除自己空间的install"}
    
    if not os.path.isdir(host_install):
        return {"success": False, "error": "install目录不存在，无需删除"}
    
    try:
        # 备份后删除（保留3个备份）
        import glob
        backup_pattern = os.path.join(host_ws, "install.bak.*")
        existing_backups = sorted(glob.glob(backup_pattern), reverse=True)
        for old_backup in existing_backups[2:]:  # 只保留最近2个备份
            try:
                shutil.rmtree(old_backup)
            except Exception:
                pass
        
        backup_dir = os.path.join(host_ws, f"install.deleted.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.move(host_install, backup_dir)
        
        _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")
        
        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(current_user["username"], "install_delete", f"target={audit_target or 'self'}")
        
        return {
            "success": True,
            "message": "安装包已删除（已自动备份）",
            "backup_dir": backup_dir
        }
    except Exception as e:
        logger.error(f"删除install失败: {e}", exc_info=True)
        return {"success": False, "error": f"删除失败: {str(e)}"}


# ============================================================
# v3.6 安装目录管理 & 文件夹同步增强 & 备份回滚 & 操作历史
# ============================================================

# install/ -> Docker/bk/ 部署映射表
# 说明：mock_truck 与 simulation_launches 使用完全一致的"整目录复制"逻辑，
# 确保 *_Supervisor_001.yaml / *_Supervisor_001.py 等附加文件也能被复制；
# .pem 证书由 _copy_install_to_bk 统一跳过，不会被覆盖。
INSTALL_TO_BK_MAPPINGS: List[Dict[str, str]] = [
    {
        # 整个 mock_truck/config 目录（含 mock_truck.yaml、mock_truck_Supervisor_001.yaml）
        "src_dir": "mock_truck/share/mock_truck/config",
        "dst_dir": "mock_truck/config",
        "glob": "*",
    },
    {
        # 整个 mock_truck/launch 目录（含 mock_truck_launch.py、mock_truck_Supervisor_001.py）
        "src_dir": "mock_truck/share/mock_truck/launch",
        "dst_dir": "mock_truck/launch",
        "glob": "*",
    },
    {
        # 整个 simulation_launches/config 目录
        "src_dir": "simulation_launches/share/simulation_launches/config",
        "dst_dir": "simulation_launches/config",
        "glob": "*",
    },
    {
        # 整个 simulation_launches/launch 目录（含 simulation_launch.py、Supervisor_001.py）
        "src_dir": "simulation_launches/share/simulation_launches/launch",
        "dst_dir": "simulation_launches/launch",
        "glob": "*",
    },
]

# ============================================================
# bk 目录白名单：以下文件/目录在任何部署/清空/回滚操作中都不应被修改或删除
# 证书目录（106证书/139证书/192证书）和启动模板由管理员手动维护，
# 部署流程只负责镜像更新 mock_truck 和 simulation_launches。
# ============================================================

# bk 根目录下受保护的文件/目录名（精确匹配）
BK_PROTECTED_NAMES = {
    "106证书",
    "139证书",
    "192证书",
    "start_docker_template.sh",
}

# 受保护的文件名模式（fnmatch 语法，在任意子目录下匹配）
BK_PROTECTED_PATTERNS = ("*.pem",)

# 允许部署/清空/回滚操作的子目录（白名单之外的子目录一律不动）
BK_DEPLOYABLE_SUBDIRS = (
    "mock_truck/config",
    "mock_truck/launch",
    "simulation_launches/config",
    "simulation_launches/launch",
    "mock_truck",
    "simulation_launches",
)


def _is_bk_protected(name: str) -> bool:
    """判断 bk 目录下的文件/目录名是否受白名单保护（不应被修改或删除）。

    匹配规则：
    1. 精确命中 BK_PROTECTED_NAMES（如 ``106证书``、``start_docker_template.sh``）
    2. 通配命中 BK_PROTECTED_PATTERNS（如 ``*.pem``）
    """
    if name in BK_PROTECTED_NAMES:
        return True
    import fnmatch
    for pat in BK_PROTECTED_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


# 单次操作保留的最近备份数量
BK_BACKUP_KEEP = 5

# 视为"安装目录相关"操作的审计 action 白名单
INSTALL_AUDIT_ACTIONS = {
    "install_upload", "install_deploy", "bk_clean", "bk_copy_from_install",
    "bk_rollback", "sync_folder", "upload_install",
}


def _backup_bk_dir(bk_dir: str, backups_dir: str, op_type: str) -> Optional[str]:
    """将 Docker/bk 目录打包备份到 .bk_backups/bk_backup_<时间戳>_<op>.tar.gz。

    返回备份文件绝对路径；备份失败返回 None。
    """
    if not os.path.isdir(bk_dir):
        return None
    try:
        os.makedirs(backups_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"bk_backup_{ts}_{op_type}.tar.gz"
        backup_path = os.path.join(backups_dir, backup_name)
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(bk_dir, arcname="bk")
        # 保留最近 BK_BACKUP_KEEP 个备份
        backups = sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
        )
        for old in backups[:-BK_BACKUP_KEEP]:
            try:
                os.remove(old)
            except Exception:
                pass
        return backup_path
    except Exception as e:
        logger.error(f"备份 bk 目录失败: {e}", exc_info=True)
        return None


def _restore_bk_dir(bk_dir: str, backup_path: str) -> bool:
    """从备份包恢复 Docker/bk 目录

    白名单保护：只回滚 ``mock_truck`` 和 ``simulation_launches`` 子目录，
    证书目录（106证书/139证书/192证书）和 ``start_docker_template.sh`` 保持不动。
    子目录内的 ``*.pem`` 文件同样受保护不被覆盖（证书由管理员单独维护）。
    """
    if not os.path.isfile(backup_path):
        return False
    try:
        import tempfile
        # 解压到临时目录，避免直接覆盖 bk_dir 中的受保护文件
        with tempfile.TemporaryDirectory(prefix="bk_restore_") as tmp_dir:
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(tmp_dir)
            # tar 包内根目录为 bk，定位到实际内容目录
            content_dir = os.path.join(tmp_dir, "bk")
            if not os.path.isdir(content_dir):
                content_dir = tmp_dir
            # 只恢复 mock_truck 和 simulation_launches 子目录
            os.makedirs(bk_dir, exist_ok=True)
            for sub in ("mock_truck", "simulation_launches"):
                src_sub = os.path.join(content_dir, sub)
                if not os.path.isdir(src_sub):
                    continue
                dst_sub = os.path.join(bk_dir, sub)
                # 清空目标子目录（白名单：保留 *.pem 证书文件）
                if os.path.isdir(dst_sub):
                    SystemUtils.clean_directory(dst_sub, keep_patterns=BK_PROTECTED_PATTERNS)
                else:
                    os.makedirs(dst_sub, exist_ok=True)
                # 从备份复制到 bk（白名单：跳过 *.pem）
                for root, _dirs, files in os.walk(src_sub):
                    rel = os.path.relpath(root, src_sub)
                    dst_root = dst_sub if rel == "." else os.path.join(dst_sub, rel)
                    os.makedirs(dst_root, exist_ok=True)
                    for fname in files:
                        if _is_bk_protected(fname):
                            continue
                        shutil.copy2(os.path.join(root, fname), os.path.join(dst_root, fname))
        return True
    except Exception as e:
        logger.error(f"恢复 bk 目录失败: {e}", exc_info=True)
        return False


def _copy_install_to_bk(host_install: str, bk_dir: str) -> Dict[str, Any]:
    """根据 INSTALL_TO_BK_MAPPINGS 把 install 目录中的文件复制到 Docker/bk。

    返回 ``{"success": True, "copied": [...], "skipped": [...]}``。

    白名单保护：命中 ``BK_PROTECTED_PATTERNS``（如 ``*.pem``）的文件一律跳过，
    避免敏感凭证被同步到 bk 目录。部署只镜像 mock_truck 和 simulation_launches。
    """
    copied: List[str] = []
    skipped: List[str] = []
    if not os.path.isdir(host_install):
        return {"success": False, "copied": copied, "skipped": skipped, "error": "install 目录不存在"}
    os.makedirs(bk_dir, exist_ok=True)
    for m in INSTALL_TO_BK_MAPPINGS:
        try:
            if "src_dir" in m:
                src_dir = os.path.join(host_install, m["src_dir"])
                dst_dir = os.path.join(bk_dir, m["dst_dir"])
                if not os.path.isdir(src_dir):
                    skipped.append(m["src_dir"])
                    continue
                os.makedirs(dst_dir, exist_ok=True)
                for f in glob.glob(os.path.join(src_dir, m.get("glob", "*"))):
                    if os.path.isfile(f):
                        fname = os.path.basename(f)
                        # 白名单：跳过受保护文件（*.pem 证书等）
                        if _is_bk_protected(fname):
                            skipped.append(os.path.relpath(f, host_install))
                            continue
                        dst = os.path.join(dst_dir, fname)
                        shutil.copy2(f, dst)
                        copied.append(os.path.relpath(dst, bk_dir))
            else:
                src = os.path.join(host_install, m["src"])
                dst = os.path.join(bk_dir, m["dst"])
                if not os.path.isfile(src):
                    skipped.append(m["src"])
                    continue
                # 白名单：单文件映射也跳过受保护文件
                if _is_bk_protected(os.path.basename(src)):
                    skipped.append(m["src"])
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(os.path.relpath(dst, bk_dir))
        except Exception as e:
            logger.warning(f"复制 install -> bk 失败: {m}, {e}")
            skipped.append(f"{m.get('src', m.get('src_dir', '?'))}: {e}")
    return {"success": True, "copied": copied, "skipped": skipped}


def _clean_bk_subdir(bk_dir: str, sub: str) -> Dict[str, Any]:
    """清空 Docker/bk 下的指定子目录（mock_truck/config 等）。

    ``sub`` 取值：``mock_truck/config``、``mock_truck/launch``、
    ``simulation_launches/config``、``simulation_launches/launch``、``all``。
    """
    valid_subs = {
        "mock_truck/config", "mock_truck/launch",
        "simulation_launches/config", "simulation_launches/launch",
        "all",
    }
    if sub not in valid_subs:
        return {"success": False, "error": f"未知子目录: {sub}"}
    if not os.path.isdir(bk_dir):
        return {"success": False, "error": "bk 目录不存在"}
    targets = []
    if sub == "all":
        for s in valid_subs - {"all"}:
            targets.append(s)
    else:
        targets.append(sub)
    cleaned: List[str] = []
    for t in targets:
        path = os.path.join(bk_dir, t)
        if not os.path.isdir(path):
            cleaned.append(f"{t} (不存在)")
            continue
        try:
            # 白名单：清空目录时保留受保护文件（*.pem 证书等，部署不会重新复制证书）
            ok, msg = SystemUtils.clean_directory(path, keep_patterns=BK_PROTECTED_PATTERNS)
            cleaned.append(f"{t} ({'清空' if ok else '失败'})")
        except Exception as e:
            cleaned.append(f"{t} (失败: {e})")
    return {"success": True, "cleaned": cleaned}


@router.get("/api/install/workspace-users")
async def list_workspace_users(current_user: dict = Depends(require_admin)):
    """获取管理员下拉切换器可选用户列表（仅 role=user 的普通用户）。

    返回 ``[{username, email, home_folder_path}, ...]``，并附加 ``admin`` 自身。
    """
    try:
        users = db.get_all_users()
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        users = {}
    result = [{
        "username": "admin",
        "email": "admin",
        "home_folder_path": os.path.expanduser("~/robotruck_ros2"),
    }]
    for key, info in users.items():
        if not isinstance(info, dict):
            continue
        if info.get("role") != "user":
            continue
        username = info.get("username") or generate_username_from_email(info.get("email", ""))
        if not username:
            continue
        result.append({
            "username": username,
            "email": info.get("email", ""),
            "home_folder_path": info.get("home_folder_path") or os.path.expanduser(f"~/robotruck_ros2/{username}"),
        })
    return {"success": True, "users": result, "current_user": current_user.get("username")}


@router.post("/api/install/deploy")
async def deploy_install_to_bk(data: Dict[str, Any], current_user: dict = Depends(require_permission('scripts'))):
    """上传后的部署：从 install 复制新配置到 Docker/bk（覆盖同名文件，带备份）

    v3.8：默认 ``clean=False``，仅覆盖同名文件，不执行删除操作，
    符合"不要清空 bk，要替换（cp 过去）"的要求。
    保留 ``clean`` 参数供管理员显式启用旧清空流程（向后兼容）。

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "clean": false,                # 是否清空 bk 目录（默认 false，仅覆盖）
            "backup": true                 # 是否生成备份包（默认 true）
        }
    """
    target_user = data.get("target_user")
    clean = data.get("clean", False)
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        host_install = workspace_paths["host_install"]
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        if not os.path.isdir(host_install):
            return {"success": False, "error": f"install 目录不存在: {host_install}，请先上传安装包"}

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, "install_deploy")

        cleaned: List[str] = []
        if clean:
            if os.path.isdir(bk_dir):
                for sub in [
                    "mock_truck/config", "mock_truck/launch",
                    "simulation_launches/config", "simulation_launches/launch",
                ]:
                    path = os.path.join(bk_dir, sub)
                    if os.path.isdir(path):
                        for item in os.listdir(path):
                            p = os.path.join(path, item)
                            # 白名单：保留受保护文件（*.pem 证书等，部署不会重新复制证书）
                            if _is_bk_protected(item):
                                continue
                            try:
                                if os.path.isfile(p) or os.path.islink(p):
                                    os.unlink(p)
                                elif os.path.isdir(p):
                                    shutil.rmtree(p)
                            except Exception as e:
                                logger.warning(f"清理 {p} 失败: {e}")
                        cleaned.append(sub)

        copy_result = _copy_install_to_bk(host_install, bk_dir)

        audit_target = workspace_paths.get("target_user")
        audit_details = (
            f"target={audit_target or 'self'} clean={clean} backup={backup_path or 'none'} "
            f"copied={len(copy_result.get('copied', []))} skipped={len(copy_result.get('skipped', []))}"
        )
        db.add_audit_log(current_user["username"], "install_deploy", audit_details)

        return {
            "success": copy_result["success"],
            "cleaned": cleaned,
            "copied": copy_result.get("copied", []),
            "skipped": copy_result.get("skipped", []),
            "backup": backup_path,
            "message": "部署完成" if copy_result["success"] else "部署失败",
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"install_deploy 失败: {e}", exc_info=True)
        return {"success": False, "error": f"部署失败: {str(e)}"}


@router.post("/api/system/bk/clean")
async def bk_clean(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """清空 bk 子目录（mock_truck/config 等）

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "sub": "mock_truck/config",   # 或 "all"
            "backup": true
        }
    """
    target_user = data.get("target_user")
    sub = data.get("sub", "all")
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, f"bk_clean_{sub.replace('/', '_')}")

        result = _clean_bk_subdir(bk_dir, sub)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_clean",
            f"sub={sub} target={audit_target or 'self'} backup={backup_path or 'none'}",
        )
        return {
            "success": result["success"],
            "cleaned": result.get("cleaned", []),
            "error": result.get("error"),
            "backup": backup_path,
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_clean 失败: {e}", exc_info=True)
        return {"success": False, "error": f"清空失败: {str(e)}"}


@router.post("/api/system/bk/copy-from-install")
async def bk_copy_from_install(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """从 install 复制配置到 bk（不清空，仅覆盖同名文件）

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "backup": true
        }
    """
    target_user = data.get("target_user")
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        host_install = workspace_paths["host_install"]
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        if not os.path.isdir(host_install):
            return {"success": False, "error": f"install 目录不存在: {host_install}"}

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, "bk_copy_from_install")

        result = _copy_install_to_bk(host_install, bk_dir)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_copy_from_install",
            f"target={audit_target or 'self'} backup={backup_path or 'none'} copied={len(result.get('copied', []))}",
        )
        return {
            "success": result["success"],
            "copied": result.get("copied", []),
            "skipped": result.get("skipped", []),
            "backup": backup_path,
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_copy_from_install 失败: {e}", exc_info=True)
        return {"success": False, "error": f"复制失败: {str(e)}"}


@router.get("/api/system/bk/backups")
async def list_bk_backups(target_user: Optional[str] = None, current_user: dict = Depends(require_permission('tools'))):
    """列出当前（或目标）用户的所有 bk 备份包"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    backups_dir = workspace_paths["bk_backups_dir"]
    backups: List[Dict[str, Any]] = []
    if os.path.isdir(backups_dir):
        for f in sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        ):
            try:
                st = os.stat(f)
                backups.append({
                    "name": os.path.basename(f),
                    "path": f,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except Exception:
                continue
    return {"success": True, "backups": backups, "target_user": workspace_paths.get("target_user")}


@router.post("/api/system/bk/rollback")
async def bk_rollback(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """回滚到指定备份包

    请求体::

        {
            "target_user": "shijie_guo",
            "backup": "bk_backup_20260720_120000_install_deploy.tar.gz"
        }
    """
    target_user = data.get("target_user")
    backup_name = data.get("backup")
    if not backup_name:
        return {"success": False, "error": "缺少 backup 参数"}

    # 防止路径遍历
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", backup_name):
        return {"success": False, "error": "备份包名非法"}

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]
        backup_path = os.path.join(backups_dir, backup_name)
        if not os.path.isfile(backup_path):
            return {"success": False, "error": f"备份包不存在: {backup_name}"}

        ok = _restore_bk_dir(bk_dir, backup_path)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_rollback",
            f"backup={backup_name} target={audit_target or 'self'} result={'ok' if ok else 'fail'}",
        )
        return {
            "success": ok,
            "backup": backup_path,
            "target_user": audit_target,
            "message": "回滚成功" if ok else "回滚失败，请查看日志",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_rollback 失败: {e}", exc_info=True)
        return {"success": False, "error": f"回滚失败: {str(e)}"}


@router.get("/api/system/bk/history")
async def list_bk_history(
    target_user: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(require_permission('tools')),
):
    """获取当前（或目标）用户的安装目录相关操作历史

    合并审计日志和备份包信息，按时间倒序返回。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    audit_target = workspace_paths.get("target_user")

    # 1. 取审计日志
    try:
        all_logs = db.get_audit_logs(limit=500)
    except Exception:
        all_logs = []

    # 2. 过滤相关 action
    target_filter = None
    if audit_target:
        target_filter = f"target={audit_target}"
    elif current_user.get("role") != "admin":
        # 非管理员仅看自己的记录
        target_filter = f"target=self"

    history: List[Dict[str, Any]] = []
    for log in all_logs:
        if not isinstance(log, dict):
            continue
        action = log.get("action", "")
        if action not in INSTALL_AUDIT_ACTIONS:
            continue
        details = log.get("details", "")
        # 简单按 target= 过滤
        if target_filter and target_filter not in details:
            # 对于无 target= 字段的旧日志，仅管理员能看见
            if current_user.get("role") == "admin" and "target=" not in details:
                pass
            else:
                continue
        history.append({
            "timestamp": log.get("timestamp"),
            "user": log.get("username"),
            "action": action,
            "details": details,
            "backup": _extract_backup_from_details(details),
        })

    history = history[:limit]

    # 3. 合并备份包信息
    backups_dir = workspace_paths["bk_backups_dir"]
    backup_files: List[Dict[str, Any]] = []
    if os.path.isdir(backups_dir):
        for f in sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        ):
            try:
                st = os.stat(f)
                backup_files.append({
                    "name": os.path.basename(f),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except Exception:
                continue

    return {
        "success": True,
        "history": history,
        "backups": backup_files,
        "target_user": audit_target,
    }


def _extract_backup_from_details(details: str) -> Optional[str]:
    """从审计 details 字符串中提取 backup=xxx 的备份文件名"""
    if not details:
        return None
    m = re.search(r"backup=([^\s]+)", details)
    if not m:
        return None
    val = m.group(1)
    if val in ("none", "None", "null"):
        return None
    return os.path.basename(val)


@router.get("/api/ports/used")
async def get_used_ports_api(current_user: dict = Depends(get_current_user)):
    """获取当前宿主机已占用端口列表（管理员可用）"""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可查看端口占用情况")
    used = sorted(get_used_ports())
    return {"success": True, "used_ports": used, "count": len(used)}


@router.get("/api/scripts/list")
async def list_scripts(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """列出已生成的启动脚本"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    scripts = [f for f in os.listdir(scripts_dir) if f.startswith("start_docker_ros2_") and f.endswith(".sh")]
    return {"success": True, "scripts": scripts, "scripts_dir": scripts_dir}

@router.delete("/api/scripts/clear-all")
async def clear_all_scripts(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """清空所有已生成的启动脚本"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    removed = 0
    for f in os.listdir(scripts_dir):
        if f.endswith(".sh"):
            os.remove(os.path.join(scripts_dir, f))
            removed += 1
    db.add_audit_log(current_user["username"], "clear_scripts", f"清空 {removed} 个脚本")
    return {"success": True, "removed": removed, "message": f"已清空 {removed} 个脚本"}

@router.get("/api/scripts/default-paths")
async def get_default_paths(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取默认路径配置（根据用户角色返回对应工作空间路径）"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    return {
        "success": True,
        "host_install": workspace_paths["host_install"],
        "container_install": workspace_paths["container_install"],
        "bag_storage": workspace_paths["bag_storage"],
        "container_bag_path": workspace_paths.get("container_bag_path", "/root/robotruck_ros2/bags"),
        "launch_dir": workspace_paths["launch_dir"],
        "scripts_dir": workspace_paths["scripts_dir"],
        "logs_dir": workspace_paths["logs_dir"],
        "docker_image": ROS2_DEFAULT["docker_image"]
    }

@router.get("/api/scripts/quota")
async def get_quota_status(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """查询当前用户的配额使用情况"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    user_role = current_user.get("role", "user")

    from services.script_generator import ROS2ScriptGenerator as Gen
    current_count = Gen._count_scripts_in_dir(scripts_dir)
    global_count = Gen.get_global_script_count()
    role_quota = Gen.ADMIN_QUOTA if user_role == "admin" else Gen.USER_QUOTA
    used_indices = Gen.get_all_used_indices()
    available_indices = [i for i in range(Gen.GLOBAL_MAX) if i not in used_indices]

    return {
        "success": True,
        "user_role": user_role,
        "role_quota": role_quota,
        "current_count": current_count,
        "role_remaining": max(0, role_quota - current_count),
        "global_max": Gen.GLOBAL_MAX,
        "global_count": global_count,
        "global_remaining": max(0, Gen.GLOBAL_MAX - global_count),
        "used_indices": sorted(used_indices),
        "available_indices": available_indices,
        "available_count": len(available_indices),
    }

@router.get("/api/scripts/{script_name}/content")
async def get_script_content(script_name: str, target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取脚本文件内容"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"success": True, "content": content}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.put("/api/scripts/{script_name}")
async def update_script(script_name: str, data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """更新脚本文件内容"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    new_content = data.get("content")
    if new_content is None:
        raise HTTPException(400, "缺少 content")
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.chmod(full_path, os.stat(full_path).st_mode | 0o111)
        db.add_audit_log(current_user["username"], "update_script", script_name)
        return {"success": True, "message": "已更新"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/api/scripts/{script_name}")
async def delete_script(script_name: str, target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """删除脚本文件"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    try:
        os.remove(full_path)
        db.add_audit_log(current_user["username"], "delete_script", script_name)
        return {"success": True, "message": "已删除"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/api/scripts/batch-execute")
async def batch_execute_scripts(data: Dict[str, Any], current_user: dict = Depends(require_permission('scripts'))):
    """批量执行启动脚本（顺序/并行）"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts = data.get("scripts", [])
    mode = data.get("mode", "顺序")
    retry_count = int(data.get("retry_count", 0))
    retry_delay = int(data.get("retry_delay", 5))
    if not scripts:
        raise HTTPException(400, "未选择脚本")
    scripts_dir = workspace_paths["scripts_dir"]
    results = []
    def run_one_with_retry(name):
        """执行单个脚本（支持重试）"""
        full_path = os.path.join(scripts_dir, name)
        validate_user_path(full_path, current_user, target_user=target_user)
        if not os.path.isfile(full_path):
            return {"name": name, "success": False, "error": "文件不存在"}
        for attempt in range(retry_count + 1):
            rc, out, err = DockerManager.run_cmd(["bash", full_path], timeout=300)
            if rc == 0:
                return {"name": name, "success": True, "stdout": out, "stderr": err, "attempts": attempt + 1}
            if attempt < retry_count:
                logger.info(f"脚本 {name} 第 {attempt+1} 次执行失败，{retry_delay}s 后重试...")
                time.sleep(retry_delay)
        return {"name": name, "success": False, "stdout": out, "stderr": err, "attempts": retry_count + 1}
    if mode == "顺序":
        for name in scripts:
            results.append(run_one_with_retry(name))
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(scripts)) as executor:
            future_results = [executor.submit(run_one_with_retry, name) for name in scripts]
            for future in concurrent.futures.as_completed(future_results):
                results.append(future.result())
    db.add_audit_log(current_user["username"], "batch_execute_scripts", f"{len(scripts)} scripts, mode={mode}")
    # 批量登记容器归属（成功执行的脚本对应的容器归当前用户所有）
    for r in results:
        name = r.get("name", "")
        if r.get("success") and name.startswith("start_docker_ros2_") and name.endswith(".sh"):
            id_part = name[len("start_docker_ros2_"):-len(".sh")]
            owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
            container_name = f"ros2_{owner}_{id_part}"
            rc_cid, cid_out, _ = DockerManager.run_cmd(
                DOCKER_PREFIX.split() + ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}"]
            )
            cid = cid_out.strip()[:12] if rc_cid == 0 and cid_out.strip() else ""
            rc_img, img_out, _ = DockerManager.run_cmd(
                DockerManager._docker("inspect", "--format", "{{.Config.Image}}", container_name)
            )
            img = img_out.strip() if rc_img == 0 else ""
            db.register_container(cid, container_name, img, "running", current_user.get("id"))
    return {"success": True, "results": results}

@router.post("/api/scripts/execute")
async def execute_script(data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """执行单个启动脚本"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    script = data.get("script")
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(400, "脚本不存在")
    rc, out, err = DockerManager.run_cmd(["bash", full_path], timeout=300)
    db.add_audit_log(current_user["username"], "execute_script", script)
    # 脚本执行成功后，根据脚本名登记容器归属
    if rc == 0:
        await broadcast_log("info", f"脚本 {script} 执行成功")
        # 从脚本名提取容器名（start_docker_ros2_xxx.sh -> ros2_{owner}_xxx）
        base = script
        if base.startswith("start_docker_ros2_") and base.endswith(".sh"):
            id_part = base[len("start_docker_ros2_"):-len(".sh")]
            owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
            container_name = f"ros2_{owner}_{id_part}"
            # 反查容器 ID
            rc_cid, cid_out, _ = DockerManager.run_cmd(
                DOCKER_PREFIX.split() + ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}"]
            )
            cid = cid_out.strip()[:12] if rc_cid == 0 and cid_out.strip() else ""
            # 反查镜像
            rc_img, img_out, _ = DockerManager.run_cmd(
                DockerManager._docker("inspect", "--format", "{{.Config.Image}}", container_name)
            )
            img = img_out.strip() if rc_img == 0 else ""
            db.register_container(cid, container_name, img, "running", current_user.get("id"))
    else:
        await broadcast_log("error", f"脚本 {script} 执行失败: {err}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/scripts/remove-gpu")
async def remove_gpu_from_scripts(data: Dict[str, str] = None, current_user: dict = Depends(require_permission('scripts'))):
    """从启动脚本中移除 GPU 相关参数"""
    target_user = data.get("target_user") if data else None
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    scripts = [f for f in os.listdir(scripts_dir) if f.startswith("start_docker_ros2_") and f.endswith(".sh")]
    patterns = [
        r'\s*--cpus=[\d\.]+\s*\\?\s*',
        r'\s*--memory=[\d\.]+g\s*\\?\s*',
        r'\s*--gpus\s+all\s*\\?\s*',
        r'\s*--shm-size=[\d\.]+g\s*\\?\s*',
        r'\s*--env=NVIDIA_VISIBLE_DEVICES=all\s*\\?\s*',
        r'\s*--env=NVIDIA_DRIVER_CAPABILITIES=all\s*\\?\s*',
        r'\s*--env=CUDA_VISIBLE_DEVICES=[\d\.]+\s*\\?\s*',
        r'\s*--env=TF_GPU_ALLOCATOR=cuda_malloc_async\s*\\?\s*',
    ]
    modified = 0
    for script in scripts:
        path = os.path.join(scripts_dir, script)
        validate_user_path(path, current_user)
        with open(path, 'r') as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            matched = False
            for pat in patterns:
                if re.search(pat, line):
                    matched = True
                    break
            if not matched:
                new_lines.append(line)
        if len(new_lines) != len(lines):
            with open(path, 'w') as f:
                f.writelines(new_lines)
            os.chmod(path, os.stat(path).st_mode | 0o111)
            modified += 1
    db.add_audit_log(current_user["username"], "remove_gpu_from_scripts", f"{modified} scripts modified")
    return {"success": True, "modified": modified}

# ---------- 红绿灯模拟 ----------
@router.get("/api/traffic-light/status")
async def traffic_status(current_user: dict = Depends(require_permission('docker'))):
    """获取红绿灯模拟器运行状态"""
    global traffic_sender
    running = traffic_sender is not None and traffic_sender._running
    return {"running": running}

@router.post("/api/traffic-light/start")
async def start_traffic(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """启动交通红绿灯模拟器"""
    global traffic_sender
    if traffic_sender and traffic_sender._running:
        return {"success": False, "message": "已在运行"}
    config = {
        "sn": data.get("sn", "hd_light"),
        "project_id": data.get("project_id", ""),
        "token": data.get("token", ""),
        "http_host": data.get("http_host", "139.196.75.44:8900"),
        "mqtt_host": data.get("mqtt_host", "139.196.75.44:1883"),
        "cloud_host": data.get("cloud_host", "139.196.75.44:1234"),
        "login_interval": data.get("login_interval", 60),
        "report_interval": data.get("report_interval", 1)
    }
    traffic_sender = TrafficLightSender(config, log_callback=lambda msg: logger.info(f"[Traffic] {msg}"))
    traffic_sender.start()
    db.add_audit_log(current_user["username"], "start_traffic_light", f"sn={config['sn']}, project_id={config['project_id']}, http={config['http_host']}, mqtt={config['mqtt_host']}")
    return {"success": True, "message": "已启动"}

@router.post("/api/traffic-light/stop")
async def stop_traffic(current_user: dict = Depends(require_permission('traffic'))):
    """停止红绿灯模拟器"""
    global traffic_sender
    if traffic_sender:
        traffic_sender.stop()
        traffic_sender = None
    db.add_audit_log(current_user["username"], "stop_traffic_light", "")
    return {"success": True, "message": "已停止"}

@router.get("/api/traffic-light/light-status")
async def get_light_status(current_user: dict = Depends(require_permission('docker'))):
    """获取红绿灯详细状态"""
    global traffic_sender
    if traffic_sender and traffic_sender._running:
        return {"success": True, **traffic_sender.get_status()}
    else:
        return {"success": True, "running": False, "light_state": 1, "second_light_state": 2, "light_mode": 1, "mqtt_connected": False}

@router.post("/api/traffic-light/set-light-state")
async def set_light_state(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """手动设置灯状态"""
    global traffic_sender
    if not traffic_sender or not traffic_sender._running:
        return {"success": False, "message": "红绿灯模拟器未运行"}
    light_state = data.get("light_state")
    second_light_state = data.get("second_light_state")
    traffic_sender.set_light_state(light_state, second_light_state)
    db.add_audit_log(current_user["username"], "set_light_state", f"light_state={light_state}, second_light_state={second_light_state}")
    await broadcast_traffic_light_status()
    return {"success": True, "message": "灯状态已更新", **traffic_sender.get_status()}

@router.post("/api/traffic-light/set-mode")
async def set_traffic_mode(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """切换红绿灯模式"""
    global traffic_sender
    if not traffic_sender or not traffic_sender._running:
        return {"success": False, "message": "红绿灯模拟器未运行"}
    mode = data.get("mode")
    if mode not in [1, 2]:
        return {"success": False, "message": "无效的模式值，必须是1或2"}
    traffic_sender.set_mode(mode)
    db.add_audit_log(current_user["username"], "set_traffic_mode", f"mode={mode}")
    await broadcast_traffic_light_status()
    return {"success": True, "message": "模式已切换", **traffic_sender.get_status()}

# ---------- 计时红绿灯模拟 ----------
@router.get("/api/timer-traffic-light/status")
async def timer_traffic_status(current_user: dict = Depends(require_permission('docker'))):
    """获取计时红绿灯模拟器运行状态"""
    global timer_traffic_sender
    running = timer_traffic_sender is not None and timer_traffic_sender._running
    return {"running": running}

@router.post("/api/timer-traffic-light/start")
async def start_timer_traffic(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """启动计时红绿灯模拟器"""
    global timer_traffic_sender
    if timer_traffic_sender and timer_traffic_sender._running:
        return {"success": False, "message": "已在运行"}
    config = {
        "sn": data.get("sn", "hd_light2"),
        "host": data.get("host", "192.168.9.252"),
        "port": data.get("port", 1234),
        "red_duration": data.get("red_duration", 15),
        "green_duration": data.get("green_duration", 35),
        "yellow_duration": data.get("yellow_duration", 5)
    }
    timer_traffic_sender = TimerTrafficLightSender(config, log_callback=lambda msg: logger.info(f"[TimerTraffic] {msg}"))
    timer_traffic_sender.start()
    db.add_audit_log(current_user["username"], "start_timer_traffic_light", f"sn={config['sn']}, host={config['host']}:{config['port']}")
    return {"success": True, "message": "已启动"}

@router.post("/api/timer-traffic-light/stop")
async def stop_timer_traffic(current_user: dict = Depends(require_permission('traffic'))):
    """停止计时红绿灯模拟器"""
    global timer_traffic_sender
    if timer_traffic_sender:
        timer_traffic_sender.stop()
        timer_traffic_sender = None
    db.add_audit_log(current_user["username"], "stop_timer_traffic_light", "")
    return {"success": True, "message": "已停止"}

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
            admin_pp_src = os.path.join(ROS2_DEFAULT["host_install"], "pp_controller")
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
    """获取当前用户的truck配置目录（普通用户使用自己工作空间）"""
    if current_user.get("role") == "admin":
        return TRUCK_CONFIG_DIR
    workspace_paths = get_user_workspace_paths(current_user)
    return os.path.join(workspace_paths["host_install"], "simulation_launches", "share", "simulation_launches", "config")

@router.get("/api/truck/config/list")
async def list_truck_configs(current_user: dict = Depends(require_permission('tools'))):
    """列出所有truck*.yaml配置文件"""
    try:
        config_dir = get_truck_config_dir(current_user)
        files = glob.glob(os.path.join(config_dir, "truck*.yaml"))
        truck_files = [os.path.basename(f) for f in files if os.path.isfile(f)]
        truck_files.sort()
        return {"success": True, "files": truck_files, "config_dir": config_dir}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/truck/config/{filename}")
async def get_truck_config(filename: str, current_user: dict = Depends(require_permission('tools'))):
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

# ---------- 帮助文档 ----------
HELP_CONTENT = {
    "welcome": "## 欢迎页面\n\n这是 Mock Truck 的首页，显示系统概览和快速入口。\n\n- **ROS2 状态**: 显示 ROS2 环境是否可用\n- **Docker 状态**: 显示 Docker 服务是否连接\n- **安装目录**: 显示 ROS2 工作空间是否存在",
    "docker": "## Docker 管理\n\n管理 Docker 容器的启动、停止、重启、删除等操作。\n\n1. **选中容器**: 点击「✅ 选中」选择一个运行中的容器，用于 ROS2 功能操作\n2. **日志查看**: 点击「📜 日志」查看容器实时日志\n3. **命令执行**: 点击「💻 命令」在容器内执行命令\n4. **资源调整**: 点击「⚙ 资源」调整容器 CPU 和内存限制\n5. **终端**: 点击「🖥 终端」打开交互式终端",
    "scripts": "## 脚本生成\n\n扫描 launch 文件并生成 Docker 启动脚本。\n\n1. **扫描 Launch 文件**: 点击扫描按钮查看可用的 launch 文件\n2. **配置参数**: 设置 launch 目录、脚本输出目录、日志目录、Docker 镜像等\n3. **生成脚本**: 点击「⚡ 生成 ROS2 脚本」创建启动脚本",
    "vehicle": "## 仿真车启动\n\n管理已生成的启动脚本，支持批量启动仿真车辆。\n\n1. **筛选脚本**: 使用筛选框快速查找脚本\n2. **批量操作**: 勾选多个脚本后批量启动\n3. **执行模式**: 选择顺序或并行执行",
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
        {"id": "scripts", "name": "📜 脚本生成"},
        {"id": "advanced-scripts", "name": "📜 脚本执行增强"},
        {"id": "vehicle", "name": "🚛 仿真车启动"},
        {"id": "docker", "name": "🐳 Docker 管理"},
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

# ---------- 故障注入 ----------
FAULT_HISTORY_FILE = os.path.expanduser("~/.ros2_docker_manager_fault_history.json")

@router.post("/api/fault/inject")
async def inject_fault(data: Dict[str, Any], current_user: dict = Depends(require_permission('advanced-fault'))):
    """注入故障（网络延迟/节点杀死/CPU压力等）"""
    container_id = data.get("container_id", "")
    fault_type = data.get("fault_type", "")
    params = data.get("params", {})
    if not container_id:
        raise HTTPException(400, "请先选中容器")
    if not fault_type:
        raise HTTPException(400, "缺少故障类型")
    results = {"success": True, "faults": []}
    if fault_type == "topic_stop":
        topic = params.get("topic", "")
        if not topic:
            return {"success": False, "error": "缺少话题名"}
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'source /home/boonray/install/setup.bash && ros2 topic pub {topic} --once std_msgs/msg/String \"data: FAULT_STOP\"'")
        results["faults"].append({"type": "topic_stop", "topic": topic, "ok": rc == 0, "output": out or err})
    elif fault_type == "topic_delay":
        topic = params.get("topic", "")
        delay_ms = params.get("delay_ms", 1000)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc add dev eth0 root netem delay {delay_ms}ms'")
        results["faults"].append({"type": "topic_delay", "delay_ms": delay_ms, "ok": rc == 0, "output": out or err})
    elif fault_type == "node_kill":
        node = params.get("node", "")
        if not node:
            return {"success": False, "error": "缺少节点名"}
        # ROS2 没有 ros2 node kill 命令，通过进程名杀掉节点
        # 节点名格式如 /ipp_controller，去掉开头的/作为进程名关键词
        node_name = node.lstrip('/')
        # 先查找进程PID，然后kill
        kill_cmd = f"bash -c 'pids=$(pgrep -f \"{node_name}\"); if [ -n \"$pids\" ]; then kill $pids && echo \"Killed nodes: $pids\"; else echo \"Node process not found\"; fi'"
        rc, out, err = DockerManager.exec_command(container_id, kill_cmd, timeout=15)
        results["faults"].append({"type": "node_kill", "node": node, "ok": rc == 0, "output": out or err})
    elif fault_type == "service_timeout":
        service = params.get("service", "")
        timeout_ms = params.get("timeout_ms", 5000)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc add dev eth0 root netem delay {timeout_ms}ms'")
        results["faults"].append({"type": "service_timeout", "service": service, "timeout_ms": timeout_ms, "ok": rc == 0, "output": out or err})
    elif fault_type == "cpu_stress":
        cpu_count = params.get("cpu_count", 1)
        duration = params.get("duration", 30)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'stress --cpu {cpu_count} --timeout {duration}s &'", detach=True)
        results["faults"].append({"type": "cpu_stress", "cpu_count": cpu_count, "duration": duration, "ok": rc == 0})
    elif fault_type == "memory_leak":
        mem_mb = params.get("mem_mb", 256)
        duration = params.get("duration", 30)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'stress --vm 1 --vm-bytes {mem_mb}M --timeout {duration}s &'", detach=True)
        results["faults"].append({"type": "memory_leak", "mem_mb": mem_mb, "duration": duration, "ok": rc == 0})
    elif fault_type == "network_loss":
        loss_pct = params.get("loss_pct", 10)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc add dev eth0 root netem loss {loss_pct}%'")
        results["faults"].append({"type": "network_loss", "loss_pct": loss_pct, "ok": rc == 0, "output": out or err})
    elif fault_type == "gps_drift":
        topic = params.get("topic", "/gps/fix")
        drift_m = params.get("drift_m", 5.0)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'source /home/boonray/install/setup.bash && ros2 topic pub {topic} --once sensor_msgs/msg/NavSatFix \"{{latitude: 31.0, longitude: 121.0, altitude: {drift_m}}}\"'")
        results["faults"].append({"type": "gps_drift", "topic": topic, "drift_m": drift_m, "ok": rc == 0, "output": out or err})
    else:
        return {"success": False, "error": f"未知故障类型: {fault_type}"}
    history = []
    if os.path.exists(FAULT_HISTORY_FILE):
        try:
            with open(FAULT_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except:
            pass
    history.append({
        "timestamp": datetime.now().isoformat(),
        "container_id": container_id,
        "fault_type": fault_type,
        "params": params,
        "results": results["faults"]
    })
    with open(FAULT_HISTORY_FILE, 'w') as f:
        json.dump(history[-100:], f, indent=2, ensure_ascii=False)
    db.add_audit_log(current_user["username"], "inject_fault", f"{fault_type} -> {container_id}")
    await broadcast_log("warning", f"故障注入: {fault_type} -> 容器 {container_id}")
    return results

@router.post("/api/fault/clear")
async def clear_fault(data: Dict[str, str], current_user: dict = Depends(require_permission('advanced-fault'))):
    """清除容器上的所有故障注入"""
    container_id = data.get("container_id", "")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    results = []
    rc1, out1, err1 = DockerManager.exec_command(container_id, "bash -c 'tc qdisc del dev eth0 root 2>/dev/null'")
    results.append({"action": "clear_network", "ok": True, "output": "已清除网络故障"})
    rc2, out2, err2 = DockerManager.exec_command(container_id, "bash -c 'pkill -9 stress 2>/dev/null'")
    results.append({"action": "clear_stress", "ok": True, "output": "已停止压力测试"})
    db.add_audit_log(current_user["username"], "clear_fault", container_id)
    await broadcast_log("info", f"已清除容器 {container_id} 的所有故障")
    return {"success": True, "results": results}

@router.get("/api/fault/list")
async def fault_list(container_id: str = None, current_user: dict = Depends(require_permission('advanced-fault'))):
    """列出容器上的活跃故障"""
    active_faults = []
    if container_id:
        rc, out, _ = DockerManager.exec_command(container_id, "bash -c 'tc qdisc show dev eth0 2>/dev/null'")
        if "netem" in (out or ""):
            active_faults.append({"type": "network_fault", "detail": out.strip()})
        rc2, out2, _ = DockerManager.exec_command(container_id, "bash -c 'pgrep -a stress 2>/dev/null'")
        if out2 and out2.strip():
            active_faults.append({"type": "stress", "detail": out2.strip()})
    return {"success": True, "active_faults": active_faults}

@router.get("/api/fault/history")
async def fault_history(current_user: dict = Depends(require_permission('advanced-fault'))):
    """获取故障注入历史记录"""
    try:
        if os.path.exists(FAULT_HISTORY_FILE):
            with open(FAULT_HISTORY_FILE, 'r') as f:
                history = json.load(f)
            return {"success": True, "history": history}
        return {"success": True, "history": []}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/fault/history/clear")
async def clear_fault_history(current_user: dict = Depends(require_permission('advanced-fault'))):
    """清除故障注入历史记录"""
    try:
        if os.path.exists(FAULT_HISTORY_FILE):
            os.remove(FAULT_HISTORY_FILE)
        db.add_audit_log(current_user["username"], "clear_fault_history", "已清除故障历史")
        await broadcast_log("info", "故障注入历史已清除")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------- WebSocket 端点 ----------
@router.websocket("/ws/containers/{name}/logs")
async def websocket_container_logs(websocket: WebSocket, name: str):
    """WebSocket 实时推送容器日志"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="未提供认证令牌")
        return
    payload = decode_jwt_token(token)
    if not payload:
        await websocket.close(code=1008, reason="无效令牌")
        return
    username = payload.get("sub")
    if not username:
        await websocket.close(code=1008, reason="无效用户")
        return
    await websocket.accept()
    proc = None
    try:
        cmd = DockerManager._docker("logs", "-f", name)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.rstrip())
            except asyncio.CancelledError:
                break
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"容器日志流错误 ({name}): {e}", exc_info=True)
        await websocket.send_text(f"错误: {str(e)}")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except:
                proc.kill()
        try:
            await websocket.close()
        except:
            pass

async def broadcast_traffic_light_status():
    """广播红绿灯状态给所有WebSocket客户端"""
    global traffic_sender
    if traffic_sender and traffic_sender._running:
        status = traffic_sender.get_status()
    else:
        status = {"running": False, "light_state": 1, "second_light_state": 2, "light_mode": 1, "mqtt_connected": False}
    message = json.dumps({"type": "traffic_light_status", **status})
    for client in ws_clients:
        try:
            await client.send_text(message)
        except Exception as e:
            logger.debug(f"广播红绿灯状态失败: {e}")

@router.websocket("/ws")
async def websocket_general(websocket: WebSocket):
    """通用 WebSocket 连接（心跳保活 + 红绿灯状态推送）"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="未提供认证令牌")
        return
    payload = decode_jwt_token(token)
    if not payload:
        await websocket.close(code=1008, reason="无效令牌")
        return
    username = payload.get("sub")
    if not username:
        await websocket.close(code=1008, reason="无效用户")
        return
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        db.add_audit_log(username, "websocket_connected", "WebSocket 连接")
        await websocket.send_text(json.dumps({"type": "log", "log_type": "info", "data": "WebSocket 连接已建立", "timestamp": time.time()}))
        traffic_broadcast_count = 0
        while True:
            try:
                await asyncio.sleep(2)
                # 每 2 秒广播一次红绿灯状态（含 MQTT 连接状态）
                if traffic_broadcast_count % 1 == 0:
                    await broadcast_traffic_light_status()
                traffic_broadcast_count += 1
                # 每 30 秒发送一次心跳
                if traffic_broadcast_count % 15 == 0:
                    await websocket.send_text(json.dumps({"type": "ping", "timestamp": time.time()}))
            except asyncio.CancelledError:
                break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.debug(f"WebSocket ping 失败: {e}")
                break
    except WebSocketDisconnect:
        logger.info("WebSocket 客户端主动断开")
    except Exception as e:
        logger.error(f"WebSocket 通用错误: {e}", exc_info=True)
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
        db.add_audit_log(username, "websocket_disconnected", "WebSocket 断开")
        try:
            await websocket.close()
        except:
            pass

@router.websocket("/ws/containers/{name}/shell")
async def websocket_container_shell(websocket: WebSocket, name: str):
    """WebSocket 交互式终端（支持 root 模式）"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="未提供认证令牌")
        return
    payload = decode_jwt_token(token)
    if not payload:
        await websocket.close(code=1008, reason="无效令牌")
        return
    username = payload.get("sub")
    if not username:
        await websocket.close(code=1008, reason="无效用户")
        return
    
    # ★★★ 前置检查：容器是否运行 ★★★
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.State.Running}}", name))
    if rc != 0:
        await websocket.close(code=1011, reason="容器不存在")
        return
    if out.strip().lower() != "true":
        await websocket.close(code=1011, reason="容器未运行")
        return
    
    # 获取模式参数（普通或 root）
    mode = websocket.query_params.get("mode", "normal")
    
    await websocket.accept()
    import pty
    import os
    import subprocess
    import termios
    import threading
    import asyncio
    master_fd, slave_fd = pty.openpty()
    try:
        attrs = termios.tcgetattr(master_fd)
        attrs[3] = attrs[3] | termios.ECHO | termios.ICANON
        termios.tcsetattr(master_fd, termios.TCSANOW, attrs)
    except Exception as e:
        logger.warning(f"设置终端属性失败: {e}")
    
    # 根据模式决定是否使用 root 用户
    # 添加 X11 环境变量支持，使容器内可以运行 GUI 程序
    # DISPLAY=:1 对应 VNC 服务器端口
    if mode == "root":
        cmd = DockerManager._docker("exec", "--user", "root", "-it", "-e", "DISPLAY=:1", "-e", "QT_QPA_PLATFORM=xcb", "-e", "XAUTHORITY=/home/boonray/.Xauthority", name, "bash", "-l")
    else:
        cmd = DockerManager._docker("exec", "-it", "-e", "DISPLAY=:1", "-e", "QT_QPA_PLATFORM=xcb", "-e", "XAUTHORITY=/home/boonray/.Xauthority", name, "bash", "-l")
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        close_fds=True
    )
    os.close(slave_fd)
    loop = asyncio.get_running_loop()
    stop_reader = False
    def reader():
        """终端输出读取线程"""
        nonlocal stop_reader
        try:
            while not stop_reader:
                try:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    asyncio.run_coroutine_threadsafe(
                        websocket.send_bytes(data), loop
                    )
                except OSError as e:
                    if e.errno in (9, 5):
                        break
                    raise
        except Exception as e:
            logger.error(f"终端 reader 错误: {e}", exc_info=True)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        while True:
            try:
                data = await websocket.receive_bytes()
                if data:
                    os.write(master_fd, data)
            except asyncio.CancelledError:
                break
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"Shell WebSocket 处理错误 (容器: {name}): {e}", exc_info=True)
    finally:
        stop_reader = True
        try:
            os.close(master_fd)
        except Exception:
            pass
        thread.join(timeout=1)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        try:
            await websocket.close()
        except:
            pass

# ---------- 工单系统模块 API ----------

# 工单附件存储目录
TICKET_ATTACHMENTS_DIR = os.path.expanduser("~/ros2_web/data/ticket_attachments")
ALLOWED_ATTACHMENT_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
                           ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                           ".txt", ".log", ".csv", ".md", ".json", ".yaml", ".yml",
                           ".zip", ".tar", ".gz", ".bz2", ".7z"}
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50MB

# 工单状态机：状态 -> 允许的下一状态
TICKET_STATUS_TRANSITIONS = {
    "pending":    ["processing", "resolved", "closed"],
    "processing": ["resolved", "closed", "pending"],
    "resolved":   ["closed", "processing"],
    "closed":     ["processing"],  # 允许重新打开
}

# 工单分类列表
TICKET_CATEGORIES = [
    "车辆控制", "容器异常", "仿真启动", "脚本生成", "证书同步",
    "车辆配置", "环境配置", "权限问题", "其他"
]

def _ticket_user_filter(current_user: dict) -> Optional[Dict[str, Any]]:
    """普通用户只看自己的工单；管理员看全部"""
    if current_user.get("role") == "admin":
        return None
    return {"customer_id": current_user.get("id")}

async def _broadcast_ticket_event(event: str, ticket_id: str, payload: dict = None):
    """向所有 WebSocket 客户端广播工单事件"""
    msg = json.dumps({
        "type": "ticket_event",
        "event": event,                # create/update/reply/delete/status_change
        "ticket_id": ticket_id,
        "data": payload or {},
        "timestamp": time.time()
    })
    for client in ws_clients[:]:
        try:
            await client.send_text(msg)
        except Exception:
            if client in ws_clients:
                ws_clients.remove(client)


# ---------- 工单元信息接口 ----------

@router.get("/api/tickets/meta")
async def get_tickets_meta(current_user: dict = Depends(get_current_user)):
    """获取工单元信息（分类、状态、优先级、权限）"""
    return {
        "success": True,
        "categories": TICKET_CATEGORIES,
        "statuses": ["pending", "processing", "resolved", "closed"],
        "priorities": [1, 2, 3, 4, 5],
        "transitions": TICKET_STATUS_TRANSITIONS,
        "is_admin": current_user.get("role") == "admin",
        "current_user_id": current_user.get("id"),
        "current_username": current_user.get("username") or current_user.get("email", "")
    }


# ---------- 工单 CRUD ----------

@router.post("/api/tickets")
async def create_ticket_api(req: Dict[str, Any] = None, current_user: dict = Depends(get_current_user)):
    """创建工单（普通用户 + 管理员均可）"""
    req = req or {}
    title = (req.get("title") or "").strip()
    content = (req.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(400, "标题和内容不能为空")
    if len(title) > 200:
        raise HTTPException(400, "标题不能超过 200 字符")
    category = (req.get("category") or "其他").strip()
    priority = int(req.get("priority", 3))
    if priority < 1 or priority > 5:
        priority = 3
    attachments = req.get("attachments") or []
    customer_name = current_user.get("username") or current_user.get("email", "")
    # v3.6：默认处理人 = 登录用户（创建人）
    assignee_id = req.get("assignee_id") or current_user.get("id")
    assignee_name = req.get("assignee_name") or current_user.get("username") or customer_name

    ticket = db.create_ticket(
        customer_id=current_user.get("id"),
        customer_name=customer_name,
        title=title,
        content=content,
        category=category,
        priority=priority,
        attachments=attachments,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
    )
    if not ticket:
        raise HTTPException(500, "创建工单失败")

    await _broadcast_ticket_event("create", ticket.get("id"), {
        "ticket_no": ticket.get("ticket_no"),
        "title": title,
        "customer_name": customer_name,
        "status": "pending",
    })
    logger.info(f"用户 {customer_name} 创建工单 {ticket.get('ticket_no')}")
    return {"success": True, "ticket": ticket}


@router.get("/api/tickets")
async def list_tickets_api(
    status: str = None, category: str = None, priority: int = None,
    keyword: str = None, start_date: str = None, end_date: str = None,
    assignee_id: str = None, page: int = 1, limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """查询工单列表（普通用户仅看自己；管理员看全部）"""
    if page < 1: page = 1
    if limit < 1 or limit > 100: limit = 20
    filters = {
        "status": status, "category": category, "priority": priority,
        "keyword": keyword, "start_date": start_date, "end_date": end_date,
        "assignee_id": assignee_id,
    }
    user_filter = _ticket_user_filter(current_user)
    result = db.list_tickets(filters=filters, user_filter=user_filter, page=page, limit=limit)
    return {
        "success": True,
        "items": result["items"],
        "total": result["total"],
        "page": result["page"],
        "limit": result["limit"],
        "is_admin": current_user.get("role") == "admin",
    }


@router.get("/api/tickets/{ticket_id}")
async def get_ticket_api(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """获取工单详情 + 回复列表"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    # 权限校验：普通用户只能查看自己的工单
    if current_user.get("role") != "admin" and ticket.get("customer_id") != current_user.get("id"):
        raise HTTPException(403, "无权访问该工单")
    replies = db.list_replies(ticket_id)
    return {
        "success": True,
        "ticket": ticket,
        "replies": replies,
        "is_admin": current_user.get("role") == "admin",
        "current_user_id": current_user.get("id"),
    }


@router.put("/api/tickets/{ticket_id}")
@router.patch("/api/tickets/{ticket_id}")
async def update_ticket_api(ticket_id: str, req: Dict[str, Any] = None,
                            current_user: dict = Depends(get_current_user)):
    """更新工单（标题/内容/分类/优先级/状态/处理人）

    同时支持 PUT 和 PATCH 方法，便于不同前端客户端调用。
    """
    req = req or {}
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    is_admin = current_user.get("role") == "admin"
    is_owner = ticket.get("customer_id") == current_user.get("id")
    if not is_admin and not is_owner:
        raise HTTPException(403, "无权修改该工单")

    updates: Dict[str, Any] = {}
    # 普通字段：标题/内容/分类/优先级，仅创建者或管理员可改
    for field in ["title", "content", "category"]:
        if field in req:
            if not is_admin and not is_owner:
                raise HTTPException(403, f"无权修改 {field}")
            val = (req.get(field) or "").strip() if field != "category" else (req.get(field) or "").strip()
            if field == "title" and not val:
                raise HTTPException(400, "标题不能为空")
            if field == "content" and not val:
                raise HTTPException(400, "内容不能为空")
            updates[field] = val
    if "priority" in req:
        if not is_admin and not is_owner:
            raise HTTPException(403, "无权修改优先级")
        try:
            p = int(req["priority"])
            if 1 <= p <= 5:
                updates["priority"] = p
        except Exception:
            pass

    # 状态机：仅管理员可改状态
    if "status" in req:
        if not is_admin:
            raise HTTPException(403, "仅管理员可修改工单状态")
        new_status = req["status"]
        if new_status not in TICKET_STATUS_TRANSITIONS:
            raise HTTPException(400, f"无效的状态: {new_status}")
        old_status = ticket.get("status")
        if new_status != old_status:
            allowed = TICKET_STATUS_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise HTTPException(400, f"状态流转不允许: {old_status} -> {new_status}")
            updates["status"] = new_status
            if new_status == "resolved":
                updates["resolved_at"] = datetime.utcnow().isoformat()
            elif new_status == "closed":
                updates["closed_at"] = datetime.utcnow().isoformat()

    # 处理人：仅管理员可指派
    if "assignee_id" in req:
        if not is_admin:
            raise HTTPException(403, "仅管理员可指派工单")
        assignee_id = req["assignee_id"]
        assignee_name = req.get("assignee_name", "")
        updates["assignee_id"] = assignee_id
        updates["assignee_name"] = assignee_name

    if not updates:
        return {"success": True, "ticket": ticket, "message": "无更新字段"}

    ok = db.update_ticket(ticket_id, updates)
    if not ok:
        raise HTTPException(500, "更新失败")

    updated = db.get_ticket(ticket_id)
    await _broadcast_ticket_event("update", ticket_id, {
        "updates": updates,
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
    })
    # 状态变更单独广播事件
    if "status" in updates:
        await _broadcast_ticket_event("status_change", ticket_id, {
            "old_status": ticket.get("status"),
            "new_status": updates["status"],
            "ticket_no": ticket.get("ticket_no"),
            "title": ticket.get("title"),
        })
    return {"success": True, "ticket": updated}


@router.delete("/api/tickets/{ticket_id}")
async def delete_ticket_api(ticket_id: str, current_user: dict = Depends(require_admin)):
    """软删除工单（仅管理员）"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    db.soft_delete_ticket(ticket_id)
    await _broadcast_ticket_event("delete", ticket_id, {
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
    })
    return {"success": True, "message": "工单已删除"}


# ---------- 工单回复 ----------

@router.post("/api/tickets/{ticket_id}/replies")
async def add_reply_api(ticket_id: str, req: Dict[str, Any] = None,
                        current_user: dict = Depends(get_current_user)):
    """添加工单回复"""
    req = req or {}
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    # 权限校验：普通用户只能回复自己的工单；管理员可回复任意
    is_admin = current_user.get("role") == "admin"
    is_owner = ticket.get("customer_id") == current_user.get("id")
    if not is_admin and not is_owner:
        raise HTTPException(403, "无权回复该工单")

    content = (req.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "回复内容不能为空")
    attachments = req.get("attachments") or []
    reply_user_name = current_user.get("username") or current_user.get("email", "")
    reply_user_type = "admin" if is_admin else "customer"

    reply = db.add_reply(
        ticket_id=ticket_id,
        reply_user_id=current_user.get("id"),
        reply_user_name=reply_user_name,
        reply_user_type=reply_user_type,
        content=content,
        attachments=attachments,
    )
    if not reply:
        raise HTTPException(500, "回复失败")

    await _broadcast_ticket_event("reply", ticket_id, {
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
        "reply_user_name": reply_user_name,
        "reply_user_type": reply_user_type,
        "content_preview": content[:100],
    })
    return {"success": True, "reply": reply}


@router.get("/api/tickets/{ticket_id}/replies")
async def list_replies_api(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """获取工单的所有回复"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if current_user.get("role") != "admin" and ticket.get("customer_id") != current_user.get("id"):
        raise HTTPException(403, "无权访问该工单")
    replies = db.list_replies(ticket_id)
    return {"success": True, "replies": replies}


# ---------- 工单附件上传 ----------

@router.post("/api/tickets/attachments")
async def upload_attachment_api(file: UploadFile = File(...),
                                current_user: dict = Depends(get_current_user)):
    """上传附件到本地存储，返回附件信息"""
    if not file.filename:
        raise HTTPException(400, "未提供文件")
    filename = os.path.basename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    # 读取并校验大小
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(400, f"文件大小超过限制 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB")

    # 按日期/用户分目录存储
    today = datetime.utcnow().strftime("%Y%m%d")
    user_dir = os.path.join(TICKET_ATTACHMENTS_DIR, today, current_user.get("id", "anon"))
    os.makedirs(user_dir, exist_ok=True)
    # 避免文件名冲突
    unique_name = f"{int(time.time() * 1000)}_{filename}"
    file_path = os.path.join(user_dir, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)

    # 返回附件元数据（前端存到工单 attachments 字段）
    attachment = {
        "filename": filename,
        "saved_name": unique_name,
        "size": len(content),
        "ext": ext,
        "path": file_path,
        "url": f"/api/tickets/attachments/{today}/{current_user.get('id', 'anon')}/{unique_name}",
        "uploaded_at": datetime.utcnow().isoformat(),
        "uploaded_by": current_user.get("username") or current_user.get("email", ""),
    }
    return {"success": True, "attachment": attachment}


@router.get("/api/tickets/attachments/{date_dir}/{user_id}/{filename}")
async def download_attachment_api(date_dir: str, user_id: str, filename: str,
                                  current_user: dict = Depends(get_current_user)):
    """下载工单附件"""
    # 安全：禁止路径穿越
    if "/" in date_dir or "/" in user_id or "/" in filename:
        raise HTTPException(400, "非法请求")
    if ".." in date_dir or ".." in user_id or ".." in filename:
        raise HTTPException(400, "非法请求")
    file_path = os.path.join(TICKET_ATTACHMENTS_DIR, date_dir, user_id, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "附件不存在")
    return FileResponse(file_path, filename=filename)


# ============================================================
# 工单系统模块 END
# ============================================================


# ============================================================
# 数据导出模块（新增功能，零侵入）
# 与 api.py 顶部注释「后续可按业务领域进一步拆分」预期一致，
# 落地为独立的 routers/data_export.py 路由文件
# ============================================================
from routers.data_export import router as data_export_router
router.include_router(data_export_router)


# 前端 SPA 路由处理 - 必须定义在所有 API 路由之后
# 注意：由于 FastAPI/Starlette 按定义顺序匹配路由，
# 前面已经定义了 /api/*, /ws, /docs, /redoc, /openapi.json 等路由，
# 这里的 catch-all 只处理前端页面和其他静态文件

