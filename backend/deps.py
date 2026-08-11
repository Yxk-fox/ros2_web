#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 依赖注入模块
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from logger import logger
from core.constants import ALL_PANELS
from core.security import decode_jwt_token
from database import db

security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """从 Bearer Token 中解析当前用户"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    email = payload.get("sub")
    role = payload.get("role")
    if not email:
        raise HTTPException(status_code=401, detail="无效令牌")
    
    user_info = {"email": email, "role": role, "username": email}
    
    user = db.get_user(email)
    if user:
        user_info["username"] = user.get("username", email)
        user_info["home_folder_path"] = user.get("home_folder_path", "")
        user_info["id"] = user.get("id", "")
    
    return user_info

# ★★★ 先定义 require_admin ★★★
def require_admin(current_user: dict = Depends(get_current_user)):
    """验证当前用户是否为管理员"""
    if current_user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return current_user

# ★★★ 再定义 require_permission ★★★
def require_permission(panel: str):
    """验证当前用户是否拥有指定面板权限"""
    async def dependency(current_user: dict = Depends(get_current_user)):
        """权限校验依赖函数"""
        if current_user["role"] == "admin":
            return current_user
        email = current_user["email"]
        permissions = db.get_user_permissions(email)
        if panel not in permissions:
            raise HTTPException(status_code=403, detail=f"无权限访问 {panel}")
        return current_user
    return dependency
