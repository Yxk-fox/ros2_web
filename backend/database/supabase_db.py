#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Supabase 数据库适配器
"""

import os
import json
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from supabase import create_client, Client

from logger import logger
from core.constants import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, AUDIT_ENABLED, AUDIT_LOG_FILE, ALL_PANELS
from core.security import hash_password, verify_password
from core.utils import generate_username_from_email
from core.cache import _memory_cache


class SupabaseDatabase:
    """Supabase 数据库适配器，替代 JSON 文件数据库"""
    
    def __init__(self, url: str, key: str, service_role_key: str):
        """初始化 Supabase 客户端"""
        self.url = url
        self.key = key
        self.service_role_key = service_role_key
        self._client: Optional[Client] = None
        # v5.0：users.current_version 列是否就绪（PostgREST 无法执行 DDL，缺失时需手动在 SQL Editor 加列）
        self.current_version_column_ok = True
        # v5.1：版本元数据扩展列（version_notes 备注JSONB / previous_version 回滚记录JSONB）
        self.version_meta_columns_ok = {"version_notes": True, "previous_version": True}
        # v5.2：users.password_plain 列是否就绪（明文密码备份，供管理员查看；缺失时降级为不写入但功能不阻断）
        self.password_plain_column_ok = True
        self._init_client()

    def _init_client(self):
        """初始化 Supabase 客户端"""
        try:
            self._client = create_client(self.url, self.service_role_key)
            logger.info("Supabase 客户端初始化成功")
            self._ensure_default_admin()
            self._migrate_onboarding_columns()
        except Exception as e:
            logger.error(f"Supabase 客户端初始化失败: {e}")
            self._client = None

    def _migrate_onboarding_columns(self):
        """尝试添加新手引导相关字段（幂等操作）

        v5.0：同时探测 current_version 列（install 版本选择），
        PostgREST 不支持 DDL，缺失时记录日志提示手动执行 SQL。
        """
        if not self._client:
            return
        try:
            # 测试列是否存在：尝试查询带 onboarding_completed 字段
            self._client.table("users").select("onboarding_completed").limit(1).execute()
            logger.info("新手引导字段已存在，跳过迁移")
        except Exception:
            # 列不存在，尝试通过 PostgREST 的 PATCH 方式添加
            # 由于 PostgREST 不支持 DDL，这里记录日志提示用户手动执行 SQL
            logger.warning(
                "新手引导字段 (onboarding_completed, onboarding_skipped) 不存在。"
                "请在 Supabase SQL Editor 中执行以下 SQL：\n"
                "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT false;\n"
                "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_skipped BOOLEAN DEFAULT false;"
            )
        # v5.0：探测 current_version 列（缺失会导致版本切换/上传自动切换保存失败）
        try:
            self._client.table("users").select("current_version").limit(1).execute()
            self.current_version_column_ok = True
            logger.info("v5.0 版本字段 current_version 已存在，跳过迁移")
        except Exception:
            self.current_version_column_ok = False
            logger.warning(
                "v5.0 字段 current_version 不存在，install 版本切换将无法保存。"
                "请在 Supabase SQL Editor 中执行以下 SQL：\n"
                "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS current_version TEXT DEFAULT '';"
            )
        # v5.1：探测版本元数据扩展列（version_notes / previous_version）
        self._probe_version_meta_columns()
        # v5.2：探测 password_plain 列（明文密码备份，供管理员查看；缺失时降级不写入，功能不阻断）
        self._probe_password_plain_column()

    def _probe_password_plain_column(self):
        """v5.2：探测 users.password_plain 列是否就绪（PostgREST 无法 DDL，缺失时仅提示）"""
        if not self._client:
            return
        try:
            self._client.table("users").select("password_plain").limit(1).execute()
            self.password_plain_column_ok = True
        except Exception:
            self.password_plain_column_ok = False
            logger.warning(
                "v5.2 字段 users.password_plain 不存在，用户管理页「查看密码」将无法展示明文。"
                "请在 Supabase SQL Editor 中执行以下 SQL：\n"
                "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS password_plain TEXT DEFAULT '';"
            )

    def recheck_password_plain_column(self) -> bool:
        """v5.2：实时复查 users.password_plain 列是否已就绪（补列后免重启自愈）"""
        if not self._client:
            return self.password_plain_column_ok
        try:
            self._client.table("users").select("password_plain").limit(1).execute()
            if not self.password_plain_column_ok:
                logger.info("v5.2 字段 password_plain 已就绪（实时复查通过）")
            self.password_plain_column_ok = True
        except Exception:
            self.password_plain_column_ok = False
        return self.password_plain_column_ok

    def _probe_version_meta_columns(self):
        """v5.1：逐个探测 users.version_notes / previous_version 列是否就绪"""
        if not self._client:
            return
        for col in ("version_notes", "previous_version"):
            try:
                self._client.table("users").select(col).limit(1).execute()
                self.version_meta_columns_ok[col] = True
            except Exception:
                self.version_meta_columns_ok[col] = False
                logger.warning(
                    f"v5.1 字段 users.{col} 不存在，相关功能（"
                    + ("版本备注" if col == "version_notes" else "一键回滚")
                    + "）将不可用。请在 Supabase SQL Editor 中执行以下 SQL：\n"
                    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS version_notes JSONB DEFAULT '{}'::jsonb;\n"
                    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS previous_version JSONB DEFAULT NULL;"
                )

    def recheck_version_meta_columns(self) -> dict:
        """v5.1：实时复查 version_notes / previous_version 列是否已就绪（免重启自愈）"""
        if not self._client:
            return dict(self.version_meta_columns_ok)
        self._probe_version_meta_columns()
        return dict(self.version_meta_columns_ok)

    def recheck_version_column(self) -> bool:
        """v5.0：实时复查 users.current_version 列是否已就绪

        管理员在 Supabase SQL Editor 补列后无需重启服务，下一次版本切换即可成功。
        """
        if not self._client:
            return self.current_version_column_ok
        try:
            self._client.table("users").select("current_version").limit(1).execute()
            if not self.current_version_column_ok:
                logger.info("v5.0 版本字段 current_version 已就绪（实时复查通过）")
            self.current_version_column_ok = True
        except Exception:
            self.current_version_column_ok = False
        return self.current_version_column_ok

    def _ensure_default_admin(self):
        """确保存在默认管理员账户；Supabase 模式下默认密码也存储在 public.users 表中"""
        if not self._client:
            return
        try:
            admins = self._client.table("users").select("*").eq("role", "admin").execute()
            if admins.data:
                for admin in admins.data:
                    if not admin.get("password"):
                        update_payload = {"password": hash_password("Boonray2020!")}
                        # v5.2：同步写入明文密码备份（列就绪时）
                        if self.password_plain_column_ok:
                            update_payload["password_plain"] = "Boonray2020!"
                        self._client.table("users").update(update_payload).eq("id", admin["id"]).execute()
                        logger.info(f"已为管理员 {admin.get('email', admin.get('username'))} 初始化默认密码")
                return

            user_id = str(uuid.uuid4())
            insert_payload = {
                "id": user_id,
                "email": "admin",
                "username": "admin",
                "home_folder_path": os.path.expanduser("~/robotruck_ros2"),
                "role": "admin",
                "password": hash_password("Boonray2020!")
            }
            # v5.2：同步写入明文密码备份（列就绪时）
            if self.password_plain_column_ok:
                insert_payload["password_plain"] = "Boonray2020!"
            self._client.table("users").insert(insert_payload).execute()
            logger.info("已创建默认管理员 admin / Boonray2020!")
        except Exception as e:
            logger.error(f"确保默认管理员失败: {e}")

    @property
    def client(self) -> Optional[Client]:
        return self._client

    def get_user(self, email: str):
        """根据邮箱或用户名查询用户信息

        ★ 性能优化：带 30s TTL 内存缓存。每个请求都要查用户，Supabase 往返
        0.17~0.44s，是接口慢的主因之一。用户信息变更时通过 update_user /
        delete_user 主动失效缓存。
        """
        cache_key = f"user:{email}"
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return cached
        if not self._client:
            return None
        try:
            response = self._client.table("users").select("*").eq("email", email).execute()
            if response.data:
                user = response.data[0]
                _memory_cache.set(cache_key, user, ttl=30)
                return user
            response = self._client.table("users").select("*").eq("username", email).execute()
            if response.data:
                user = response.data[0]
                _memory_cache.set(cache_key, user, ttl=30)
                return user
            return None
        except Exception as e:
            logger.error(f"查询用户失败: {e}")
            return None

    def get_user_by_id(self, user_id: str):
        """根据用户ID查询用户信息"""
        if not self._client:
            return None
        try:
            response = self._client.table("users").select("*").eq("id", user_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"根据ID查询用户失败: {e}")
            return None

    def create_user(self, email: str, password: str, role: str = "user", home_folder_path: str = "", permissions: list = None):
        """创建新用户（通过 Supabase Auth + 自定义表）"""
        if not self._client:
            return False, "Supabase 客户端未初始化"
        
        if permissions is None:
            if role == "admin":
                permissions = ["welcome","scripts","advanced-scripts","docker","advanced-docker","images","traffic","advanced-fault","tools","simulation","topics","nodes","services","actions","advanced-extend","monitor","api-manager","theme","settings","tickets","data-export"]
            else:
                # 普通用户默认全员可见权限（public）
                permissions = ["welcome", "scripts", "docker", "images", "traffic", "topics", "nodes", "tools", "tickets", "monitor", "theme", "data-export"]
        
        try:
            auth_response = self._client.auth.sign_up({
                "email": email,
                "password": password
            })
            
            if not auth_response.user:
                return False, "创建认证用户失败"
            
            user_id = auth_response.user.id
            username = generate_username_from_email(email)
            
            if not home_folder_path:
                home_folder_path = os.path.join(os.path.expanduser("~/robotruck_ros2"), username)
            else:
                home_folder_path = os.path.expanduser(home_folder_path)
            
            # ★★★ 修复bug1：permissions字段是JSONB类型，直接传list避免双重序列化 ★★★
            insert_payload = {
                "id": user_id,
                "email": email,
                "username": username,
                "home_folder_path": home_folder_path,
                "role": role,
                "permissions": permissions,
                "password": hash_password(password),
                "current_version": ""
            }
            # v5.2：明文密码备份（列就绪时写入；缺失时降级跳过，不影响主流程）
            if self.password_plain_column_ok:
                insert_payload["password_plain"] = password
            self._client.table("users").insert(insert_payload).execute()

            return True, {"user_id": user_id, "username": username}
        except Exception as e:
            logger.error(f"创建用户失败: {e}")
            return False, str(e)

    def update_user_role(self, user_id: str, role: str):
        """更新用户角色"""
        if not self._client:
            return False
        try:
            self._client.table("users").update({"role": role}).eq("id", user_id).execute()
            _memory_cache.invalidate(prefix="user:")  # ★ 失效缓存
            return True
        except Exception as e:
            logger.error(f"更新用户角色失败: {e}")
            return False

    def add_audit_log(self, username: str, action: str, details: str = ""):
        """添加审计日志"""
        if not AUDIT_ENABLED or not self._client:
            return
        try:
            self._client.table("audit_logs").insert({
                "username": username,
                "action": action,
                "details": details
            }).execute()
            
            try:
                with open(AUDIT_LOG_FILE, 'a') as f:
                    f.write(f"{datetime.utcnow().isoformat()} [{username}] {action} : {details}\n")
            except Exception as e:
                logger.error(f"写入文本审计日志失败: {e}")
        except Exception as e:
            logger.error(f"添加审计日志失败: {e}")

    def get_audit_logs(self, limit: int = 100):
        """获取审计日志"""
        if not self._client:
            return []
        try:
            response = self._client.table("audit_logs").select("*").order("timestamp", desc=True).limit(limit).execute()
            return response.data
        except Exception as e:
            logger.error(f"获取审计日志失败: {e}")
            return []

    # ---------- 容器权限隔离（public.containers 表）----------
    def register_container(self, container_id: str, name: str, image: str, state: str, created_by: str):
        """记录容器归属（启动时调用）"""
        if not self._client:
            return False
        try:
            self._client.table("containers").upsert({
                "container_id": container_id,
                "name": name,
                "image": image,
                "state": state,
                "created_by": created_by,
                "updated_at": datetime.utcnow().isoformat()
            }, on_conflict="name").execute()
            _memory_cache.invalidate(prefix="visible_containers:")  # ★ 失效缓存
            return True
        except Exception as e:
            logger.error(f"记录容器归属失败: {e}")
            return False

    def update_container_state(self, name: str, state: str):
        """更新容器状态"""
        if not self._client:
            return False
        try:
            self._client.table("containers").update({
                "state": state,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("name", name).execute()
            return True
        except Exception as e:
            logger.error(f"更新容器状态失败: {e}")
            return False

    def remove_container_record(self, name: str):
        """删除容器记录"""
        if not self._client:
            return False
        try:
            self._client.table("containers").delete().eq("name", name).execute()
            _memory_cache.invalidate(prefix="visible_containers:")  # ★ 失效缓存
            return True
        except Exception as e:
            logger.error(f"删除容器记录失败: {e}")
            return False

    def get_container_owner(self, name: str):
        """获取容器归属用户 ID"""
        if not self._client:
            return None
        try:
            resp = self._client.table("containers").select("created_by").eq("name", name).limit(1).execute()
            if resp.data:
                return resp.data[0].get("created_by")
        except Exception as e:
            logger.error(f"查询容器归属失败: {e}")
        return None

    def get_visible_container_names(self, current_user: dict):
        """返回当前用户可见的容器名集合（admin 不限）

        ★ 性能优化：带 10s TTL 缓存。register_container / 删除容器时主动失效。
        """
        if not self._client:
            return None
        if current_user.get("role") == "admin":
            return None  # None 表示无过滤
        user_id = current_user.get("id")
        cache_key = f"visible_containers:{user_id}"
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resp = self._client.table("containers").select("name").eq("created_by", user_id).execute()
            names = {row["name"] for row in resp.data}
            _memory_cache.set(cache_key, names, ttl=10)
            return names
        except Exception as e:
            logger.error(f"查询可见容器失败: {e}")
            return set()

    def delete_audit_logs(self, keep_recent: int = 0):
        """清除审计日志"""
        if not self._client:
            return 0
        try:
            if keep_recent > 0:
                response = self._client.table("audit_logs").select("id").order("timestamp", desc=True).limit(keep_recent).execute()
                keep_ids = {str(row["id"]) for row in response.data}
                deleted = 0
                all_response = self._client.table("audit_logs").select("id").execute()
                for row in all_response.data:
                    if str(row["id"]) not in keep_ids:
                        self._client.table("audit_logs").delete().eq("id", row["id"]).execute()
                        deleted += 1
                return deleted
            else:
                self._client.table("audit_logs").delete().neq("id", 0).execute()
                return 0
        except Exception as e:
            logger.error(f"清除审计日志失败: {e}")
            return 0

    def delete_audit_logs_by_user(self, username: str):
        """删除指定用户的所有审计日志"""
        if not self._client:
            return 0
        try:
            response = self._client.table("audit_logs").delete().eq("username", username).execute()
            deleted = len(response.data) if response.data else 0
            return deleted
        except Exception as e:
            logger.error(f"删除用户审计日志失败: {e}")
            return 0

    def get_onboarding_state(self, username: str):
        """获取用户的新手引导状态"""
        if not self._client:
            return {"completed": False, "skipped": False}
        try:
            user = self.get_user(username)
            if not user:
                return {"completed": False, "skipped": False}
            return {
                "completed": user.get("onboarding_completed", False),
                "skipped": user.get("onboarding_skipped", False)
            }
        except Exception as e:
            logger.error(f"获取新手引导状态失败: {e}")
            return {"completed": False, "skipped": False}

    def set_onboarding_state(self, username: str, completed=None, skipped=None):
        """设置用户的新手引导状态"""
        if not self._client:
            return False
        try:
            updates = {}
            if completed is not None:
                updates["onboarding_completed"] = completed
            if skipped is not None:
                updates["onboarding_skipped"] = skipped
            if not updates:
                return True
            # 通过 email 或 username 查找用户
            user = self.get_user(username)
            if not user:
                return False
            self._client.table("users").update(updates).eq("id", user["id"]).execute()
            return True
        except Exception as e:
            error_msg = str(e)
            if "onboarding_completed" in error_msg or "onboarding_skipped" in error_msg:
                logger.warning(
                    "新手引导字段不存在，请执行数据库迁移：\n"
                    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT false;\n"
                    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_skipped BOOLEAN DEFAULT false;"
                )
            else:
                logger.error(f"设置新手引导状态失败: {e}")
            return False

    def get_all_users(self):
        """获取所有用户信息"""
        if not self._client:
            return {}
        try:
            response = self._client.table("users").select("*").execute()
            users = {}
            for user in response.data:
                key = user.get("email") or user["id"]
                users[key] = {
                    "id": user["id"],
                    "email": user["email"],
                    "username": user["username"],
                    "home_folder_path": user["home_folder_path"],
                    "role": user["role"],
                    "permissions": user.get("permissions", []),
                    "password_plain": user.get("password_plain", "") or "",
                    "created_at": user.get("created_at"),
                    "updated_at": user.get("updated_at")
                }
            return users
        except Exception as e:
            logger.error(f"获取所有用户失败: {e}")
            return {}

    def delete_user(self, user_id: str):
        """删除用户"""
        if not self._client:
            return False
        try:
            user = self.get_user_by_id(user_id)
            if not user:
                return False
            
            admins = self._client.table("users").select("id").eq("role", "admin").execute()
            admin_count = len(admins.data)
            if user.get("role") == "admin" and admin_count <= 1:
                return False
            
            self._client.table("users").delete().eq("id", user_id).execute()
            _memory_cache.invalidate(prefix="user:")  # ★ 失效缓存

            try:
                self._client.auth.admin.delete_user(user_id)
            except Exception as e:
                logger.warning(f"删除认证用户失败: {e}")

            return True
        except Exception as e:
            logger.error(f"删除用户失败: {e}")
            return False

    def update_user(self, user_id: str, updates: dict):
        """更新用户信息"""
        if not self._client:
            return False
        try:
            db_updates = {}
            if "password" in updates and updates["password"]:
                db_updates["password"] = hash_password(updates["password"])
                # v5.2：同步更新明文密码备份（列就绪时；缺失时跳过，登录校验仍走 bcrypt hash）
                if self.password_plain_column_ok:
                    db_updates["password_plain"] = updates["password"]
                try:
                    self._client.auth.admin.update_user_by_id(user_id, {
                        "password": updates["password"]
                    })
                except Exception as e:
                    logger.warning(f"同步更新 Supabase Auth 密码失败: {e}")
            if "role" in updates:
                db_updates["role"] = updates["role"]
            if "home_folder_path" in updates:
                db_updates["home_folder_path"] = os.path.expanduser(updates["home_folder_path"])
            if "permissions" in updates:
                db_updates["permissions"] = updates["permissions"]
            # v5.0：install 版本选择字段（空字符串表示回退旧版 install）
            if "current_version" in updates:
                db_updates["current_version"] = updates["current_version"] or ""
            # v5.1：版本备注（{版本名: 备注文本} JSONB）
            if "version_notes" in updates:
                db_updates["version_notes"] = updates["version_notes"] or {}
            # v5.1：回滚记录（{"version": ..., "switched_at": ...} JSONB，None 清除）
            if "previous_version" in updates:
                db_updates["previous_version"] = updates["previous_version"]

            if db_updates:
                self._client.table("users").update(db_updates).eq("id", user_id).execute()
                _memory_cache.invalidate(prefix="user:")  # ★ 失效缓存

            return True
        except Exception as e:
            msg = str(e)
            # v5.0：current_version 列缺失（PGRST204）——记录标志位，供版本切换接口给出可操作提示
            if "current_version" in msg and ("PGRST204" in msg or "schema cache" in msg):
                self.current_version_column_ok = False
                logger.error("更新用户失败：users.current_version 列不存在（PGRST204），请先执行 v5.0 数据库迁移 SQL")
            elif ("version_notes" in msg or "previous_version" in msg) and ("PGRST204" in msg or "schema cache" in msg):
                for col in ("version_notes", "previous_version"):
                    if col in msg:
                        self.version_meta_columns_ok[col] = False
                logger.error("更新用户失败：v5.1 版本元数据列不存在（PGRST204），请先执行 v5.1 迁移 SQL（见启动日志）")
            elif "password_plain" in msg and ("PGRST204" in msg or "schema cache" in msg):
                # v5.2：明文密码备份列缺失——标志位置 False，下次跳过写入；登录校验仍走 bcrypt hash，功能不阻断
                self.password_plain_column_ok = False
                logger.error(
                    "更新用户失败：users.password_plain 列不存在（PGRST204），「查看密码」不可用。"
                    "请在 Supabase SQL Editor 执行：ALTER TABLE public.users ADD COLUMN IF NOT EXISTS password_plain TEXT DEFAULT '';"
                )
            else:
                logger.error(f"更新用户失败: {e}")
            return False

    def get_user_permissions(self, email: str):
        """获取用户权限列表（管理员拥有全部权限）"""
        user = self.get_user(email)
        if not user:
            return []
        role = user.get("role", "user")
        if role == "admin":
            return ALL_PANELS
        return user.get("permissions", []) or []

    # ---------- 配置项存储（兼容 JSON 模式的 get_config/set_config） ----------
    # Supabase 模式下使用本地 JSON 文件存放非结构化配置（如 help_content），
    # 避免引入额外的数据库表，同时保持与 JsonDatabase 接口一致。
    def _config_file_path(self) -> str:
        """获取配置项本地存储文件路径"""
        return os.path.expanduser("~/ros2_web/data/supabase_configs.json")

    def _read_configs_raw(self) -> dict:
        try:
            with open(self._config_file_path(), 'r') as f:
                content = f.read().strip()
                if not content:
                    return {}
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return {}

    def _write_configs_raw(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self._config_file_path()), exist_ok=True)
            with open(self._config_file_path(), 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"写入配置文件失败: {e}")

    def get_config(self, key, default=None):
        """获取数据库中的配置项"""
        data = self._read_configs_raw()
        return data.get(key, default)

    def set_config(self, key, value):
        """设置数据库中的配置项"""
        data = self._read_configs_raw()
        data[key] = value
        self._write_configs_raw(data)

    def verify_login(self, email: str, password: str):
        """验证用户登录（优先使用 public.users 表中存储的 bcrypt 密码）"""
        if not self._client:
            return None
        try:
            user_info = self.get_user(email)
            if user_info:
                stored_hash = user_info.get("password")
                if stored_hash and verify_password(password, stored_hash):
                    return user_info
                if stored_hash:
                    return None

            response = self._client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })

            if response.user:
                if user_info:
                    return user_info
                return {
                    "id": response.user.id,
                    "email": email,
                    "role": "user",
                    "username": generate_username_from_email(email)
                }
            return None
        except Exception as e:
            logger.error(f"登录验证失败: {e}")
            return None

    # ============================================================
    # 工单（Ticket）相关方法
    # ============================================================
    def generate_ticket_no(self) -> str:
        """生成工单编号 TKyyyymmddNNN，按当日递增"""
        today = datetime.utcnow().strftime("%Y%m%d")
        prefix = f"TK{today}"
        if not self._client:
            return f"{prefix}001"
        try:
            # 查询当天最大的工单号
            resp = self._client.table("tickets").select("ticket_no").like("ticket_no", f"{prefix}%").order("ticket_no", desc=True).limit(1).execute()
            if resp.data:
                last_no = resp.data[0]["ticket_no"]
                try:
                    seq = int(last_no[-3:]) + 1
                except Exception:
                    seq = 1
            else:
                seq = 1
            return f"{prefix}{seq:03d}"
        except Exception as e:
            logger.error(f"生成工单号失败: {e}")
            return f"{prefix}{int(time.time()) % 1000:03d}"

    def create_ticket(self, customer_id: str, customer_name: str, title: str,
                      content: str, category: str, priority: int, attachments: list = None,
                      assignee_id: str = None, assignee_name: str = None) -> Dict[str, Any]:
        """创建工单

        v3.6 优化：支持 ``assignee_id`` / ``assignee_name`` 参数。
        创建工单时若传入处理人则同时写入；否则保持原行为（未分配）。
        """
        if not self._client:
            return {}
        try:
            ticket_no = self.generate_ticket_no()
            data = {
                "ticket_no": ticket_no,
                "title": title,
                "content": content,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "category": category or "其他",
                "priority": int(priority) if priority else 3,
                "status": "pending",
                "attachments": attachments or [],
            }
            # v3.6：默认处理人 = 登录用户（创建人）
            if assignee_id:
                data["assignee_id"] = assignee_id
            if assignee_name:
                data["assignee_name"] = assignee_name
            resp = self._client.table("tickets").insert(data).execute()
            return resp.data[0] if resp.data else {}
        except Exception as e:
            logger.error(f"创建工单失败: {e}")
            return {}

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """获取单个工单（未删除）"""
        if not self._client:
            return None
        try:
            resp = self._client.table("tickets").select("*").eq("id", ticket_id).is_("deleted_at", "null").limit(1).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"获取工单失败: {e}")
            return None

    def list_tickets(self, filters: Dict[str, Any] = None, user_filter: Optional[Dict[str, Any]] = None,
                     page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """列表查询工单
        filters: status/category/priority/keyword/start_date/end_date/assignee_id
        user_filter: {"customer_id": xxx} 普通用户只看自己的工单；None 表示管理员看全部
        """
        if not self._client:
            return {"items": [], "total": 0, "page": page, "limit": limit}
        filters = filters or {}
        try:
            query = self._client.table("tickets").select("*", count="exact").is_("deleted_at", "null")
            # 用户过滤
            if user_filter and user_filter.get("customer_id"):
                query = query.eq("customer_id", user_filter["customer_id"])
            # 其他过滤条件
            if filters.get("status"):
                query = query.eq("status", filters["status"])
            if filters.get("category"):
                query = query.eq("category", filters["category"])
            if filters.get("priority") is not None:
                query = query.eq("priority", int(filters["priority"]))
            if filters.get("assignee_id"):
                query = query.eq("assignee_id", filters["assignee_id"])
            if filters.get("start_date"):
                query = query.gte("created_at", filters["start_date"])
            if filters.get("end_date"):
                query = query.lte("created_at", filters["end_date"])
            if filters.get("keyword"):
                kw = f"%{filters['keyword']}%"
                query = query.or_(f"title.ilike.{kw},content.ilike.{kw},ticket_no.ilike.{kw}")
            # 排序与分页
            query = query.order("created_at", desc=True)
            offset = max(0, (page - 1) * limit)
            query = query.range(offset, offset + limit - 1)
            resp = query.execute()
            total = resp.count if hasattr(resp, "count") and resp.count is not None else len(resp.data)
            return {"items": resp.data, "total": total, "page": page, "limit": limit}
        except Exception as e:
            logger.error(f"查询工单列表失败: {e}")
            return {"items": [], "total": 0, "page": page, "limit": limit}

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> bool:
        """更新工单字段"""
        if not self._client:
            return False
        try:
            updates["updated_at"] = datetime.utcnow().isoformat()
            self._client.table("tickets").update(updates).eq("id", ticket_id).execute()
            return True
        except Exception as e:
            logger.error(f"更新工单失败: {e}")
            return False

    def soft_delete_ticket(self, ticket_id: str) -> bool:
        """软删除工单"""
        return self.update_ticket(ticket_id, {"deleted_at": datetime.utcnow().isoformat()})

    def add_reply(self, ticket_id: str, reply_user_id: str, reply_user_name: str,
                  reply_user_type: str, content: str, attachments: list = None) -> Optional[Dict[str, Any]]:
        """添加工单回复"""
        if not self._client:
            return None
        try:
            data = {
                "ticket_id": ticket_id,
                "reply_user_id": reply_user_id,
                "reply_user_name": reply_user_name,
                "reply_user_type": reply_user_type,
                "content": content,
                "attachments": attachments or [],
            }
            resp = self._client.table("ticket_replies").insert(data).execute()
            # 同时更新工单的 updated_at
            self._client.table("tickets").update({"updated_at": datetime.utcnow().isoformat()}).eq("id", ticket_id).execute()
            return resp.data[0] if resp.data else None
        except Exception as e:
            logger.error(f"添加工单回复失败: {e}")
            return None

    def list_replies(self, ticket_id: str) -> List[Dict[str, Any]]:
        """获取工单的所有回复（按时间正序）"""
        if not self._client:
            return []
        try:
            resp = self._client.table("ticket_replies").select("*").eq("ticket_id", ticket_id).order("created_at", desc=False).execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"获取工单回复失败: {e}")
            return []

