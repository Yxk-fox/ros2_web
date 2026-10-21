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


# ---------- 红绿灯模拟 ----------
@router.get("/api/traffic-light/status")
def traffic_status(current_user: dict = Depends(require_permission('docker'))):
    """获取红绿灯模拟器运行状态

    ★ 性能优化：同步 def —— 前端每3s轮询，避免事件循环阻塞
    """
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
def get_light_status(current_user: dict = Depends(require_permission('docker'))):
    """获取红绿灯详细状态

    ★ 性能优化：同步 def —— 前端每2s轮询，避免事件循环阻塞
    """
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

# ---------- 人工模式计时红绿灯模拟 ----------
@router.get("/api/manual-timer-traffic-light/status")
async def manual_timer_traffic_status(current_user: dict = Depends(require_permission('docker'))):
    """获取人工模式计时红绿灯模拟器运行状态"""
    if manual_timer_traffic_sender and manual_timer_traffic_sender._running:
        return {"success": True, **manual_timer_traffic_sender.get_status()}
    return {"success": True, "running": False}

@router.post("/api/manual-timer-traffic-light/start")
async def start_manual_timer_traffic(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """启动人工模式计时红绿灯模拟器"""
    global manual_timer_traffic_sender
    if manual_timer_traffic_sender and manual_timer_traffic_sender._running:
        return {"success": False, "message": "已在运行"}
    config = {
        "sn": data.get("sn", "js_001"),
        "host": data.get("host", "106.14.223.60"),
        "port": data.get("port", 1234),
        "manual_time": data.get("manual_time", 255),
        "auto_mode": data.get("auto_mode", 2),
        "state": data.get("state", 0)
    }
    manual_timer_traffic_sender = ManualTimerTrafficLightSender(
        config, log_callback=lambda msg: logger.info(f"[ManualTimerTraffic] {msg}"))
    manual_timer_traffic_sender.start()
    db.add_audit_log(current_user["username"], "start_manual_timer_traffic_light",
                     f"sn={config['sn']}, host={config['host']}:{config['port']}, manual_time={config['manual_time']}, auto_mode={config['auto_mode']}")
    return {"success": True, "message": "已启动"}

@router.post("/api/manual-timer-traffic-light/stop")
async def stop_manual_timer_traffic(current_user: dict = Depends(require_permission('traffic'))):
    """停止人工模式计时红绿灯模拟器"""
    global manual_timer_traffic_sender
    if manual_timer_traffic_sender:
        manual_timer_traffic_sender.stop()
        manual_timer_traffic_sender = None
    db.add_audit_log(current_user["username"], "stop_manual_timer_traffic_light", "")
    return {"success": True, "message": "已停止"}

@router.post("/api/manual-timer-traffic-light/set-state")
async def set_manual_timer_state(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """人工切换灯态(0黄闪 1黄 2红 3绿 4绿闪 5黑)"""
    if not (manual_timer_traffic_sender and manual_timer_traffic_sender._running):
        return {"success": False, "message": "模拟器未运行"}
    state = data.get("state")
    if not manual_timer_traffic_sender.set_state(state):
        return {"success": False, "message": "无效灯态，应为 0-5"}
    db.add_audit_log(current_user["username"], "set_manual_timer_traffic_state", f"state={state}")
    return {"success": True, "message": "灯态已切换", **manual_timer_traffic_sender.get_status()}

# ---------- 破碎站红绿灯模拟（T-5.3，对应 ck/lk_light_state*.py）----------
from services.traffic_light import start_crushing_light, stop_crushing_light, get_crushing_light_status

@router.get("/api/crushing-traffic-light/status")
async def crushing_traffic_status(current_user: dict = Depends(require_permission('docker'))):
    """获取破碎站红绿灯模拟器运行状态"""
    return {"success": True, **get_crushing_light_status()}

@router.post("/api/crushing-traffic-light/start")
async def start_crushing_traffic(data: Dict[str, Any], current_user: dict = Depends(require_permission('traffic'))):
    """启动破碎站红绿灯模拟器（纯 UDP 广播 light_state，三阶段循环）"""
    config = {
        "sn": data.get("sn", "hz_test_light01"),
        "host": data.get("host", "106.14.223.60"),
        "port": data.get("port", 1234),
        "red_duration": data.get("red_duration", 10),
        "green_duration": data.get("green_duration", 30),
        "yellow_duration": data.get("yellow_duration", 3),
        "send_interval": data.get("send_interval", 1),
    }
    ok, msg = start_crushing_light(config, log_callback=lambda m: logger.info(f"[CrushingTraffic] {m}"))
    if ok:
        db.add_audit_log(current_user["username"], "start_crushing_traffic_light",
                         f"sn={config['sn']}, host={config['host']}:{config['port']}")
    return {"success": ok, "message": msg}

@router.post("/api/crushing-traffic-light/stop")
async def stop_crushing_traffic(current_user: dict = Depends(require_permission('traffic'))):
    """停止破碎站红绿灯模拟器"""
    ok, msg = stop_crushing_light()
    if ok:
        db.add_audit_log(current_user["username"], "stop_crushing_traffic_light", "")
    return {"success": ok, "message": msg}


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

