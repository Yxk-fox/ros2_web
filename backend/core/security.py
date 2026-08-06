#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全工具模块
JWT、密码哈希、命令过滤、速率限制
"""

import re
import os
from datetime import datetime, timedelta
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.constants import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, BCRYPT_ROUNDS,
    RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD,
    INPUT_FILTER_ENABLED, INPUT_FILTER_WHITELIST
)
import jwt


# ============================================================
# 3. 安全工具
# ============================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=BCRYPT_ROUNDS)

def hash_password(password: str) -> str:
    """hash_password 功能处理"""
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    """verify_password 功能处理"""
    return pwd_context.verify(plain, hashed)

def create_jwt_token(data: dict, expires_delta: timedelta = None) -> str:
    """create_jwt_token 功能处理"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> dict:
    """decode_jwt_token 功能处理"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

def sanitize_command(cmd_str: str) -> str:
    """过滤危险命令字符并校验白名单，防止命令注入"""
    if not INPUT_FILTER_ENABLED:
        return cmd_str
    cmd_str = re.sub(r'[;&|$`(){}<>\n\r]', ' ', cmd_str)
    parts = cmd_str.split()
    if not parts:
        return ""
    base_cmd = os.path.basename(parts[0])
    if base_cmd not in INPUT_FILTER_WHITELIST:
        raise ValueError(f"命令 '{base_cmd}' 不在白名单中")
    if len(cmd_str) > 1024:
        raise ValueError("命令长度超过1024字符")
    return cmd_str

limiter = Limiter(key_func=get_remote_address, default_limits=[] if not RATE_LIMIT_ENABLED else [f"{RATE_LIMIT_REQUESTS}/{RATE_LIMIT_PERIOD} second"])
