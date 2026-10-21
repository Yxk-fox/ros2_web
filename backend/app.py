#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Truck 管理工具 —— 解耦后端入口

架构分层：
- core/        核心工具（配置、日志、安全、中间件、缓存、工具函数）
- database/    数据库适配器（JSON / Supabase）
- services/    业务逻辑服务（Docker、脚本生成、系统监控、红绿灯等）
- routers/     API 路由（按业务领域分组，统一挂载）
- deps.py      FastAPI 依赖注入
- models.py    Pydantic 请求模型

后续开发规范：
1. 新增功能先在 services/ 实现业务逻辑
2. 在 routers/ 按领域新建或补充路由文件
3. 公共工具放入 core/
4. 禁止在 app.py 直接写业务代码
"""

import os
import sys
import time
import json
import socket

# 确保项目根目录在路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from logger import logger
from core.constants import (
    CONFIG, PORT, HOST, CORS_ALLOWED_ORIGINS, CORS_ALLOW_ORIGIN_REGEX,
    RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD
)
from core.security import limiter
from core.middleware import SecurityHeadersMiddleware, NoCacheStaticMiddleware

# ---------- 1. FastAPI 应用创建 ----------
app = FastAPI(
    title="Mock Truck API",
    version="3.2-decoupled",
    description="解耦版 Mock Truck 管理后端 API",
    docs_url="/api/docs",
    redoc_url=None
)

# ---------- 2. 全局异常处理 ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "系统内部错误，请稍后重试"}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": str(exc.detail)}
    )

# ---------- 3. 中间件注册 ----------
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(SecurityHeadersMiddleware)

# HTTPS 重定向
if CONFIG["server"].get("ssl_cert") and CONFIG["server"].get("ssl_key"):
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(NoCacheStaticMiddleware)

# 速率限制
if RATE_LIMIT_ENABLED:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------- 4. 路由注册 ----------
from routers.files import router as files_router
from routers.ros2 import router as ros2_router
from routers.vehicles import router as vehicles_router
from routers.visualization import router as visualization_router
from routers.docker import router as docker_router
from routers.scripts import router as scripts_router
from routers.api import router as api_router
from routers.fault import router as fault_router
from routers.tickets import router as tickets_router
from routers.auth import router as auth_router
from routers.system import router as system_router
from routers.fleet import router as fleet_router
from routers.monitor import router as monitor_router
from routers.remote import router as remote_router
from routers.config_api import router as config_api_router
app.include_router(api_router)
app.include_router(files_router)
app.include_router(ros2_router)
app.include_router(vehicles_router)
app.include_router(visualization_router)
app.include_router(docker_router)
app.include_router(scripts_router)
app.include_router(fault_router)
app.include_router(tickets_router)
app.include_router(auth_router)
app.include_router(system_router)
app.include_router(fleet_router)
app.include_router(monitor_router)
app.include_router(remote_router)
app.include_router(config_api_router)

# ---------- 4.1 资源监控历史采样守护（T-5.2-03，v5.2） ----------
from services.metrics_history import start_metrics_history

@app.on_event("startup")
async def start_metrics_history_task():
    """启动资源指标采样守护线程（30s 间隔，崩溃自动重启，不影响主服务）"""
    start_metrics_history()

# ---------- 5. 静态文件挂载 ----------
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
UI_DIR = os.path.join(BASE_DIR, "..", "ui")
DOCS_DIR = os.path.join(BASE_DIR, "..", "docs")

app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

# 根路径直接返回 index.html（绕过 catch-all 路由，避免 FileResponse 经过完整中间件链）
@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# ---------- 6. SPA 前端回退 ----------

@app.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(UI_DIR, "favicon.ico"))

@app.get("/api/redoc", include_in_schema=False)
async def redoc_documentation():
    from fastapi.openapi.docs import get_redoc_html
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="Mock Truck API - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"
    )

@app.get("/doc")
async def serve_doc_index():
    return FileResponse(os.path.join(DOCS_DIR, "index.html"))

@app.get("/doc/{full_path:path}")
async def serve_doc_files(full_path: str):
    file_path = os.path.join(DOCS_DIR, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(DOCS_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404)

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    file_path = os.path.join(FRONTEND_DIR, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# ---------- 6. 启动入口 ----------
if __name__ == "__main__":
    import uvicorn
    import netifaces

    ips = set()
    try:
        hostname = socket.gethostname()
        for addr in socket.gethostbyname_ex(hostname)[2]:
            if not addr.startswith('127.'):
                ips.add(addr)
    except:
        pass
    try:
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr['addr']
                    if not ip.startswith('127.'):
                        ips.add(ip)
    except:
        pass

    print("\n" + "="*50)
    print("🚀 Mock Truck 管理工具已启动（解耦版）！")
    print(f"📌 访问地址：")
    for ip in sorted(ips):
        print(f"   http://{ip}:{PORT}/")
    print("="*50 + "\n")

    ssl_key = CONFIG["server"].get("ssl_key")
    ssl_cert = CONFIG["server"].get("ssl_cert")
    if ssl_key and ssl_cert and os.path.exists(ssl_key) and os.path.exists(ssl_cert):
        uvicorn.run(app, host=HOST, port=PORT, log_level="info", ssl_keyfile=ssl_key, ssl_certfile=ssl_cert)
    else:
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")
