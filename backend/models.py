#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic 请求模型定义
"""

from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    """登录请求体模型"""
    username: str
    password: str
    remember_me: bool = False
    remember_days: int = 1  # 1天(默认), 7天, 15天, 30天

class RegisterRequest(BaseModel):
    """普通用户注册请求体，注册接口不接受外部角色参数。"""
    username: str
    password: str

