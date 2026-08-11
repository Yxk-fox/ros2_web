#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 中间件模块
安全头、缓存控制
"""

from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件，添加 X-Content-Type-Options、CSP 等安全头"""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path

        # API 文档路径不添加安全头限制
        if path.startswith(("/api/docs", "/api/redoc", "/openapi.json", "/api/docs/oauth2-redirect")):
            return response

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self' ws: wss: http: https:; "
            "worker-src 'self' blob:;"
        )
        return response


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """静态文件缓存中间件
    - 入口 HTML（/、index.html）：no-cache，确保用户拿到最新版本
    - 静态资源（js/css/图片/字体）：max-age=600 + must-revalidate，配合 ETag 校验
      浏览器命中缓存时不再下载，服务器更新后通过 ETag 自动失效
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        # 入口 HTML 始终不缓存，保证发布即时生效
        if path == "/" or path == "/index.html" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            if "etag" in response.headers:
                del response.headers["etag"]
            return response
        # 静态资源短缓存 + ETag 校验（10 分钟）
        if path.startswith("/css/") or path.startswith("/js/") or \
           path.startswith("/images/") or path.startswith("/fonts/") or \
           path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif",
                          ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot")):
            response.headers["Cache-Control"] = "public, max-age=600, must-revalidate"
            return response
        return response
