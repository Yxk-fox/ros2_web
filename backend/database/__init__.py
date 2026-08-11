#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库工厂模块
根据配置自动选择 JSON 或 Supabase 数据库
"""

from logger import logger
from core.constants import DB_TYPE, SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY, DB_PATH, AUDIT_DB_PATH
from database.json_db import JsonDatabase
from database.supabase_db import SupabaseDatabase

def init_database():
    """初始化数据库，根据配置选择 Supabase 或 JSON 模式"""
    if DB_TYPE == "supabase" and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDatabase(SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY)
    else:
        if DB_TYPE == "supabase" and not SUPABASE_URL:
            logger.warning("配置为 Supabase 模式但未配置 URL，回退到 JSON 模式")
        return JsonDatabase(DB_PATH, AUDIT_DB_PATH)

db = init_database()
