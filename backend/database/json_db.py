#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 文件数据库适配器
"""

import json
import os
import uuid
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

from logger import logger
from core.constants import DB_PATH, AUDIT_DB_PATH, AUDIT_ENABLED, AUDIT_LOG_FILE, ALL_PANELS
from core.security import hash_password, verify_password
from core.utils import generate_username_from_email


class JsonDatabase:
    """JSON 文件数据库管理类，用户数据与操作日志分开存储
    - 用户数据（users / configs）保存在 self.path
    - 操作日志（audit_logs）保存在 self.audit_path
    两份文件独立加锁、独立读写，互不阻塞。
    """
    DEFAULT_ADMIN_PASSWORD = "123456"
    MAX_AUDIT_LOGS = 10000

    def __init__(self, path, audit_path=None):
        """初始化数据库
        :param path: 用户数据文件路径（users, configs）
        :param audit_path: 操作日志文件路径；默认与 path 同目录下的 audit_logs.json
        """
        self.path = path
        self.audit_path = audit_path or os.path.join(os.path.dirname(path), "audit_logs.json")
        self.lock = threading.Lock()
        self.audit_lock = threading.Lock()
        self._init_db()
        self._migrate_legacy_audit_logs()

    def _default_admin(self):
        """构造默认管理员账户数据"""
        return {
            "id": str(uuid.uuid4()),
            "password": hash_password(self.DEFAULT_ADMIN_PASSWORD),
            # v5.2：明文密码备份（仅供管理员在用户管理页查看/重置时取用）
            "password_plain": self.DEFAULT_ADMIN_PASSWORD,
            "role": "admin",
            "permissions": ALL_PANELS,
            "created_at": datetime.utcnow().isoformat(),
            "onboarding_completed": False,
            "onboarding_skipped": False,
            "current_version": ""
        }

    def _init_db(self):
        """初始化用户数据与操作日志文件，确保默认管理员存在"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)

        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            default_data = {
                "users": {"admin": self._default_admin()},
                "configs": {}
            }
            with open(self.path, 'w') as f:
                json.dump(default_data, f, indent=2, ensure_ascii=False)
        else:
            data = self._read_users_raw()
            if not data.get("users"):
                data["users"] = {"admin": self._default_admin()}
                with open(self.path, 'w') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                # 为缺少字段的旧用户补充
                needs_write = False
                for email, info in data["users"].items():
                    if "id" not in info:
                        info["id"] = str(uuid.uuid4())
                        needs_write = True
                    if "onboarding_completed" not in info:
                        info["onboarding_completed"] = False
                        needs_write = True
                    if "onboarding_skipped" not in info:
                        info["onboarding_skipped"] = False
                        needs_write = True
                    # v5.0：为旧用户补充 install 版本选择字段
                    if "current_version" not in info:
                        info["current_version"] = ""
                        needs_write = True
                    # v5.2：为旧用户补充明文密码备份字段（无法反推 bcrypt，留空表示"未知，需重置"）
                    if "password_plain" not in info:
                        info["password_plain"] = ""
                        needs_write = True
                    # v5.1：为旧用户补充版本备注 / 回滚记录字段
                    if "version_notes" not in info:
                        info["version_notes"] = {}
                        needs_write = True
                    if "previous_version" not in info:
                        info["previous_version"] = None
                        needs_write = True
                    # 迁移：非管理员用户添加 data-export 权限
                    if info.get("role", "user") != "admin":
                        perms = info.get("permissions", [])
                        if "data-export" not in perms:
                            perms.append("data-export")
                            info["permissions"] = perms
                            needs_write = True
                if needs_write:
                    with open(self.path, 'w') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    logger.info("已为旧用户补充缺失字段及 data-export 权限")

        if not os.path.exists(self.audit_path) or os.path.getsize(self.audit_path) == 0:
            with open(self.audit_path, 'w') as f:
                json.dump([], f, indent=2, ensure_ascii=False)

    def _migrate_legacy_audit_logs(self):
        """将旧版 data.json 中遗留的 audit_logs 迁移到独立的操作日志文件"""
        try:
            with open(self.path, 'r') as f:
                content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
        except Exception:
            return
        legacy_logs = data.get("audit_logs")
        if not isinstance(legacy_logs, list) or not legacy_logs:
            return
        with self.audit_lock:
            existing = self._read_audit_logs_raw()
            existing.extend(legacy_logs)
            if len(existing) > self.MAX_AUDIT_LOGS:
                existing = existing[-self.MAX_AUDIT_LOGS:]
            self._write_audit_logs_raw(existing)
        data.pop("audit_logs", None)
        with self.lock:
            with open(self.path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"已迁移 {len(legacy_logs)} 条历史操作日志到独立文件: {self.audit_path}")

    def _read_users_raw(self):
        """读取用户数据文件（不加锁，供内部调用）"""
        try:
            with open(self.path, 'r') as f:
                content = f.read().strip()
                if not content:
                    logger.warning(f"用户数据文件为空: {self.path}")
                    return {"users": {}, "configs": {}}
                data = json.loads(content)
                if not isinstance(data, dict):
                    return {"users": {}, "configs": {}}
                data.setdefault("users", {})
                data.setdefault("configs", {})
                return data
        except json.JSONDecodeError as e:
            logger.error(f"用户数据文件解析失败，使用默认数据: {self.path}, 错误: {e}")
            return {"users": {}, "configs": {}}
        except Exception as e:
            logger.error(f"读取用户数据文件失败: {self.path}, 错误: {e}")
            return {"users": {}, "configs": {}}

    def _read(self):
        """线程安全地读取用户数据"""
        with self.lock:
            return self._read_users_raw()

    def _write(self, data):
        """线程安全地写入用户数据"""
        with self.lock:
            with open(self.path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def _read_audit_logs_raw(self):
        """读取操作日志文件（不加锁，供内部调用）"""
        try:
            with open(self.audit_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
                return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as e:
            logger.error(f"操作日志文件解析失败: {self.audit_path}, 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"读取操作日志文件失败: {self.audit_path}, 错误: {e}")
            return []

    def _write_audit_logs_raw(self, logs):
        """写入操作日志文件（不加锁，供内部调用）"""
        with open(self.audit_path, 'w') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

    def get_user(self, username):
        """根据用户名或邮箱查询用户信息（与 Supabase 适配器行为对齐）

        users 字典以 email 为键；target_user 前端传的是 username，
        因此先按键查，再按 username 字段查。
        """
        data = self._read()
        user = data.get("users", {}).get(username)
        if user:
            return user
        for info in data.get("users", {}).values():
            if info.get("username") == username:
                return info
        return None

    def get_user_by_id(self, user_id: str):
        """根据用户ID查询用户信息"""
        data = self._read()
        for email, info in data.get("users", {}).items():
            if info.get("id") == user_id:
                result = {**info, "email": email}
                return result
        return None

    def create_user(self, username, password, role="user", home_folder_path="", permissions=None):
        """管理员创建新用户

        permissions: 可选，None 时按角色使用默认权限（与 API 端点传参兼容）
        """
        data = self._read()
        if username in data.get("users", {}):
            return False, "用户名已存在"
        # 默认权限：普通用户仅 public 权限，管理员全部权限
        if role == "admin":
            default_perms = ["welcome","scripts","advanced-scripts","docker","advanced-docker","images","traffic","advanced-fault","tools","simulation","topics","nodes","services","actions","advanced-extend","monitor","api-manager","theme","settings","tickets","data-export"]
        else:
            default_perms = ["welcome", "scripts", "docker", "images", "traffic", "topics", "nodes", "tools", "tickets", "monitor", "theme", "data-export"]
        data.setdefault("users", {})[username] = {
            "id": str(uuid.uuid4()),
            "username": generate_username_from_email(username),
            "password": hash_password(password),
            # v5.2：明文密码备份（供管理员在用户管理页查看；bcrypt 仍为登录校验依据）
            "password_plain": password,
            "role": role,
            "created_at": datetime.utcnow().isoformat(),
            "permissions": permissions if permissions else default_perms,
            "onboarding_completed": False,
            "onboarding_skipped": False,
            "current_version": "",
            # 与 Supabase 适配器对齐：存储工作目录（缺失会导致用户端点报"用户工作目录未配置"）
            "home_folder_path": home_folder_path or ""
        }
        self._write(data)
        return True, {"username": username}

    def update_user_role(self, username, role):
        """更新用户角色"""
        data = self._read()
        if username not in data.get("users", {}):
            return False
        data["users"][username]["role"] = role
        self._write(data)
        return True

    def add_audit_log(self, username, action, details=""):
        """添加审计日志条目"""
        if not AUDIT_ENABLED:
            return
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "username": username,
            "action": action,
            "details": details
        }
        with self.audit_lock:
            logs = self._read_audit_logs_raw()
            logs.append(log_entry)
            if len(logs) > self.MAX_AUDIT_LOGS:
                logs = logs[-self.MAX_AUDIT_LOGS:]
            self._write_audit_logs_raw(logs)
        try:
            with open(AUDIT_LOG_FILE, 'a') as f:
                f.write(f"{log_entry['timestamp']} [{username}] {action} : {details}\n")
        except Exception as e:
            logger.error(f"写入文本审计日志失败: {e}")

    def get_audit_logs(self, limit=100):
        """管理员获取审计日志"""
        with self.audit_lock:
            logs = self._read_audit_logs_raw()
        return logs[-limit:] if limit > 0 else logs

    def delete_audit_logs(self, keep_recent=0):
        """管理员清除审计日志"""
        with self.audit_lock:
            logs = self._read_audit_logs_raw()
            if keep_recent > 0:
                new_logs = logs[-keep_recent:]
            else:
                new_logs = []
            self._write_audit_logs_raw(new_logs)
            deleted_count = len(logs) - len(new_logs)
        return deleted_count

    def delete_audit_logs_by_user(self, username):
        """删除指定用户的所有审计日志"""
        with self.audit_lock:
            logs = self._read_audit_logs_raw()
            new_logs = [log for log in logs if log.get("username") != username]
            deleted_count = len(logs) - len(new_logs)
            self._write_audit_logs_raw(new_logs)
        return deleted_count

    def get_onboarding_state(self, username):
        """获取用户的新手引导状态"""
        data = self._read()
        user = data.get("users", {}).get(username)
        if not user:
            return {"completed": False, "skipped": False}
        return {
            "completed": user.get("onboarding_completed", False),
            "skipped": user.get("onboarding_skipped", False)
        }

    def set_onboarding_state(self, username, completed=None, skipped=None):
        """设置用户的新手引导状态"""
        data = self._read()
        user = data.get("users", {}).get(username)
        if not user:
            return False
        if completed is not None:
            user["onboarding_completed"] = completed
        if skipped is not None:
            user["onboarding_skipped"] = skipped
        self._write(data)
        return True

    # ---------- 容器权限隔离（JSON 模式空实现，仅 admin 可用）----------
    def register_container(self, container_id, name, image, state, created_by):
        return False

    def update_container_state(self, name, state):
        return False

    def remove_container_record(self, name):
        return False

    def get_container_owner(self, name):
        return None

    def get_visible_container_names(self, current_user):
        return None  # JSON 模式不做过滤

    def get_config(self, key, default=None):
        """获取数据库中的配置项"""
        data = self._read()
        return data.get("configs", {}).get(key, default)

    def set_config(self, key, value):
        """设置数据库中的配置项"""
        data = self._read()
        data.setdefault("configs", {})[key] = value
        self._write(data)

    def get_all_users(self):
        """获取所有用户信息"""
        data = self._read()
        users = data.get("users", {})
        # 为每个用户补充 email 和 id 字段，与 Supabase 格式保持一致
        result = {}
        for email, info in users.items():
            result[email] = {
                **info,
                "email": email,
                "username": email.split("@")[0] if "@" in email else email,
            }
        return result

    def delete_user(self, user_id):
        """管理员删除用户（支持 user_id 或 email）"""
        data = self._read()
        users = data.get("users", {})
        
        # 先尝试按 id 查找，再尝试按 email 查找
        target_email = None
        for email, info in users.items():
            if info.get("id") == user_id or email == user_id:
                target_email = email
                break
        
        if target_email is None:
            return False
        
        admins = [u for u, info in users.items() if info.get("role") == "admin"]
        if target_email in admins and len(admins) <= 1:
            return False
        del data["users"][target_email]
        self._write(data)
        return True

    def update_user(self, user_id, updates):
        """管理员更新用户信息（支持 user_id 或 email）"""
        data = self._read()
        users = data.get("users", {})
        
        # 先尝试按 id 查找，再尝试按 email 查找
        target_email = None
        for email, info in users.items():
            if info.get("id") == user_id or email == user_id:
                target_email = email
                break
        
        if target_email is None:
            return False
        user = users[target_email]
        if "password" in updates:
            user["password"] = hash_password(updates["password"])
            # v5.2：同步更新明文密码备份，供管理员查看
            user["password_plain"] = updates["password"]
        if "role" in updates:
            user["role"] = updates["role"]
        if "permissions" in updates:
            user["permissions"] = updates["permissions"]
        # v5.0：install 版本选择字段
        if "current_version" in updates:
            user["current_version"] = updates["current_version"] or ""
        # v5.1：版本备注 / 回滚记录字段
        if "version_notes" in updates:
            user["version_notes"] = updates["version_notes"] or {}
        if "previous_version" in updates:
            user["previous_version"] = updates["previous_version"]
        self._write(data)
        return True

    def get_user_permissions(self, username):
        """获取用户权限列表（管理员拥有全部权限）"""
        user = self.get_user(username)
        if not user:
            return []
        role = user.get("role", "user")
        if role == "admin":
            return ALL_PANELS
        return user.get("permissions", []) or []

    def verify_login(self, username: str, password: str):
        """验证用户登录"""
        user = self.get_user(username)
        if user and verify_password(password, user["password"]):
            return user
        return None

    # ============================================================
    # 工单（Ticket）相关方法 —— JSON 兼容实现（数据存于独立 JSON 文件）
    # ============================================================
    def _ticket_db_path(self):
        """工单 JSON 文件路径"""
        return os.path.join(os.path.dirname(self.path), "tickets.json")

    def _load_tickets_data(self) -> Dict[str, Any]:
        """加载工单数据 {tickets: [], replies: []}"""
        path = self._ticket_db_path()
        if not os.path.exists(path):
            return {"tickets": [], "replies": []}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"tickets": [], "replies": []}

    def _save_tickets_data(self, data: Dict[str, Any]):
        """保存工单数据"""
        path = self._ticket_db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def generate_ticket_no(self) -> str:
        """生成工单编号 TKyyyymmddNNN"""
        today = datetime.utcnow().strftime("%Y%m%d")
        prefix = f"TK{today}"
        data = self._load_tickets_data()
        max_seq = 0
        for t in data.get("tickets", []):
            no = t.get("ticket_no", "")
            if no.startswith(prefix):
                try:
                    seq = int(no[-3:])
                    if seq > max_seq:
                        max_seq = seq
                except Exception:
                    pass
        return f"{prefix}{max_seq + 1:03d}"

    def create_ticket(self, customer_id: str, customer_name: str, title: str,
                      content: str, category: str, priority: int, attachments: list = None,
                      assignee_id: str = None, assignee_name: str = None) -> Dict[str, Any]:
        """创建工单

        v3.6 优化：支持 ``assignee_id`` / ``assignee_name`` 参数。
        默认处理人 = 登录用户（创建人）。
        """
        data = self._load_tickets_data()
        ticket_no = self.generate_ticket_no()
        ticket = {
            "id": str(uuid.uuid4()),
            "ticket_no": ticket_no,
            "title": title,
            "content": content,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "category": category or "其他",
            "priority": int(priority) if priority else 3,
            "status": "pending",
            # v3.6：默认处理人 = 登录用户（创建人）
            "assignee_id": assignee_id or customer_id,
            "assignee_name": assignee_name or customer_name,
            "resolved_at": None,
            "closed_at": None,
            "attachments": attachments or [],
            "deleted_at": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        data.setdefault("tickets", []).append(ticket)
        self._save_tickets_data(data)
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """获取单个工单（未删除）"""
        data = self._load_tickets_data()
        for t in data.get("tickets", []):
            if t.get("id") == ticket_id and not t.get("deleted_at"):
                return t
        return None

    def list_tickets(self, filters: Dict[str, Any] = None, user_filter: Optional[Dict[str, Any]] = None,
                     page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """列表查询工单"""
        filters = filters or {}
        data = self._load_tickets_data()
        items = [t for t in data.get("tickets", []) if not t.get("deleted_at")]
        # 用户过滤
        if user_filter and user_filter.get("customer_id"):
            items = [t for t in items if t.get("customer_id") == user_filter["customer_id"]]
        # 其他过滤
        if filters.get("status"):
            items = [t for t in items if t.get("status") == filters["status"]]
        if filters.get("category"):
            items = [t for t in items if t.get("category") == filters["category"]]
        if filters.get("priority") is not None:
            items = [t for t in items if t.get("priority") == int(filters["priority"])]
        if filters.get("assignee_id"):
            items = [t for t in items if t.get("assignee_id") == filters["assignee_id"]]
        if filters.get("start_date"):
            items = [t for t in items if t.get("created_at", "") >= filters["start_date"]]
        if filters.get("end_date"):
            items = [t for t in items if t.get("created_at", "") <= filters["end_date"]]
        if filters.get("keyword"):
            kw = filters["keyword"].lower()
            items = [t for t in items if kw in t.get("title", "").lower()
                     or kw in t.get("content", "").lower()
                     or kw in t.get("ticket_no", "").lower()]
        # 排序
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        total = len(items)
        offset = max(0, (page - 1) * limit)
        items_page = items[offset:offset + limit]
        return {"items": items_page, "total": total, "page": page, "limit": limit}

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> bool:
        """更新工单字段"""
        data = self._load_tickets_data()
        for t in data.get("tickets", []):
            if t.get("id") == ticket_id:
                t.update(updates)
                t["updated_at"] = datetime.utcnow().isoformat()
                self._save_tickets_data(data)
                return True
        return False

    def soft_delete_ticket(self, ticket_id: str) -> bool:
        """软删除工单"""
        return self.update_ticket(ticket_id, {"deleted_at": datetime.utcnow().isoformat()})

    def add_reply(self, ticket_id: str, reply_user_id: str, reply_user_name: str,
                  reply_user_type: str, content: str, attachments: list = None) -> Optional[Dict[str, Any]]:
        """添加工单回复"""
        data = self._load_tickets_data()
        reply = {
            "id": int(time.time() * 1000),
            "ticket_id": ticket_id,
            "reply_user_id": reply_user_id,
            "reply_user_name": reply_user_name,
            "reply_user_type": reply_user_type,
            "content": content,
            "attachments": attachments or [],
            "created_at": datetime.utcnow().isoformat(),
        }
        data.setdefault("replies", []).append(reply)
        # 更新工单的 updated_at
        for t in data.get("tickets", []):
            if t.get("id") == ticket_id:
                t["updated_at"] = datetime.utcnow().isoformat()
                break
        self._save_tickets_data(data)
        return reply

    def list_replies(self, ticket_id: str) -> List[Dict[str, Any]]:
        """获取工单的所有回复（按时间正序）"""
        data = self._load_tickets_data()
        replies = [r for r in data.get("replies", []) if r.get("ticket_id") == ticket_id]
        replies.sort(key=lambda x: x.get("created_at", ""))
        return replies