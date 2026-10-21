#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest 全局夹具（v5.2 单元测试底座）

职责：
1. 将 backend/ 注入 sys.path，测试内可直接 `from core.xxx import ...`
2. 阻止 database/__init__.py 的模块级 db 初始化（会连真实 Supabase）
3. 提供内存版 FakeSupabaseClient，使 SupabaseDatabase 适配器可离线跑契约测试
4. 提供 json / supabase 双适配器统一夹具 `db`（接口契约测试用）
5. bcrypt 哈希打桩（rounds=12 单次 ~0.3s，打桩后全量测试 60s 内跑完）
"""

import os
import sys
import types
import uuid as _uuid

import pytest

# ---------- 1. sys.path 注入 ----------
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ---------- 2. 阻止 database 包的模块级网络初始化 ----------
# database/__init__.py 会在 import 时执行 init_database()：
# 当前 config.json 为 supabase 模式，会真实连接 Supabase（网络依赖）。
# 测试仅需要 json_db / supabase_db 子模块，故预注册一个不含业务代码的空包。
if "database" not in sys.modules:
    _pkg = types.ModuleType("database")
    _pkg.__path__ = [os.path.join(BACKEND_DIR, "database")]
    _pkg.__package__ = "database"
    sys.modules["database"] = _pkg

# ---------- 3. 共享缓存自动清理（避免用例间串扰） ----------
# Supabase 适配器的 get_user / get_visible_container_names 带 TTL 内存缓存，
# 缓存键不含实例信息，跨用例残留会导致假数据命中。
@pytest.fixture(autouse=True)
def _clear_shared_cache():
    from core.cache import _memory_cache
    _memory_cache.invalidate()
    yield
    _memory_cache.invalidate()


# ============================================================
# 内存版 Supabase 假客户端（链式 API 与 supabase-py 对齐）
# ============================================================

class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeTable:
    """模拟 supabase-py 的 table().select/insert/update/delete().eq().execute() 链"""

    # 各表插入时的 DDL 默认列（模拟数据库默认值）
    _INSERT_DEFAULTS = {
        "audit_logs": lambda: {"id": str(_uuid.uuid4()),
                               "timestamp": __import__("datetime").datetime.utcnow().isoformat()},
    }

    def __init__(self, store: dict, name: str):
        self._store = store
        self._name = name
        self._op = None
        self._filters = []
        self._payload = None
        self._order = None
        self._limit_n = None

    def select(self, *cols):
        self._op = "select"
        return self

    def insert(self, data):
        self._op = "insert"
        self._payload = data
        return self

    def update(self, data):
        self._op = "update"
        self._payload = data
        return self

    def upsert(self, data, on_conflict=None):
        self._op = "upsert"
        self._payload = data
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def _match(self, row):
        for kind, col, val in self._filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "neq" and row.get(col) == val:
                return False
        return True

    def execute(self):
        rows = self._store.setdefault(self._name, [])

        if self._op in ("insert", "upsert"):
            item = dict(self._payload)
            defaults = self._INSERT_DEFAULTS.get(self._name)
            if defaults:
                for k, v in defaults().items():
                    item.setdefault(k, v)
            if "id" not in item:
                item["id"] = str(_uuid.uuid4())
            rows.append(item)
            return FakeResponse([item])

        selected = [r for r in rows if self._match(r)]

        if self._op == "update":
            for r in selected:
                r.update(self._payload)
            return FakeResponse(selected)

        if self._op == "delete":
            for r in selected:
                rows.remove(r)
            return FakeResponse(selected)

        # select
        if self._order:
            col, desc = self._order
            selected = sorted(selected, key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit_n is not None:
            selected = selected[:self._limit_n]
        return FakeResponse(selected)


class _FakeAuthAdmin:
    def __init__(self, client):
        self._client = client

    def delete_user(self, user_id):
        self._client.deleted_auth_users.add(user_id)

    def update_user_by_id(self, user_id, data):
        pass


class _FakeAuth:
    """模拟 supabase.auth：sign_up 对重复邮箱抛错（与真实 Supabase Auth 行为一致）"""

    def __init__(self, client):
        self._client = client
        self.admin = _FakeAuthAdmin(client)

    def sign_up(self, credentials):
        email = credentials.get("email", "")
        if email in self._client.signed_up_emails:
            raise ValueError("User already registered")
        self._client.signed_up_emails.add(email)
        import types as _t
        user = _t.SimpleNamespace(id=str(_uuid.uuid4()))
        return _t.SimpleNamespace(user=user)


class FakeSupabaseClient:
    def __init__(self):
        self.store = {"users": [], "audit_logs": [], "containers": []}
        self.signed_up_emails = set()
        self.deleted_auth_users = set()
        self.auth = _FakeAuth(self)

    def table(self, name) -> FakeTable:
        return FakeTable(self.store, name)


# ============================================================
# 双适配器统一夹具（接口契约测试）
# ============================================================

def _patch_fast_hash(monkeypatch, module):
    """将适配器模块内的 bcrypt 哈希替换为可逆假哈希（提速 + 可断言）"""
    monkeypatch.setattr(module, "hash_password", lambda p: f"hashed:{p}")
    monkeypatch.setattr(module, "verify_password",
                        lambda plain, hashed: hashed == f"hashed:{plain}")


def _make_json_db(tmp_path, monkeypatch):
    import database.json_db as jdb
    _patch_fast_hash(monkeypatch, jdb)
    # 文本审计日志重定向到临时目录，避免污染真实 audit.log
    monkeypatch.setattr(jdb, "AUDIT_LOG_FILE", str(tmp_path / "audit_text.log"))
    return jdb.JsonDatabase(str(tmp_path / "data.json"), str(tmp_path / "audit_logs.json"))


def _make_supabase_db(tmp_path, monkeypatch):
    import database.supabase_db as sdb
    _patch_fast_hash(monkeypatch, sdb)
    monkeypatch.setattr(sdb, "AUDIT_LOG_FILE", str(tmp_path / "audit_text.log"))
    # 绕过 __init__（会 create_client 连网），手工装配与真实初始化等价的状态
    adapter = sdb.SupabaseDatabase.__new__(sdb.SupabaseDatabase)
    adapter.url = "http://fake.local"
    adapter.key = "anon-key"
    adapter.service_role_key = "service-key"
    adapter._client = FakeSupabaseClient()
    adapter.current_version_column_ok = True
    adapter.version_meta_columns_ok = {"version_notes": True, "previous_version": True}
    # v5.2：users.password_plain 列就绪标记（真实 __init__ 会探测，mock 直接置 True）
    adapter.password_plain_column_ok = True
    # 复刻 _ensure_default_admin 的行为：无管理员时插入默认 admin
    adapter._client.table("users").insert({
        "id": str(_uuid.uuid4()),
        "email": "admin",
        "username": "admin",
        "home_folder_path": str(tmp_path / "ws"),
        "role": "admin",
        "password": "hashed:Boonray2020!",
        "current_version": "",
        "onboarding_completed": False,
        "onboarding_skipped": False,
        "permissions": [],
    }).execute()
    # Supabase 模式的 configs 存本地 JSON，重定向到临时文件避免污染真实配置
    adapter._config_file_path = lambda: str(tmp_path / "configs.json")
    return adapter


@pytest.fixture(params=["json", "supabase"])
def db(request, tmp_path, monkeypatch):
    """接口契约测试夹具：同一用例集分别在 JsonDatabase 与（假客户端驱动的）
    SupabaseDatabase 上执行"""
    if request.param == "json":
        return _make_json_db(tmp_path, monkeypatch)
    return _make_supabase_db(tmp_path, monkeypatch)


@pytest.fixture
def ws_home(tmp_path):
    """构造一个用户工作空间目录（含一个合法版本 v1/install/setup.bash）"""
    home = tmp_path / "ws"
    install = home / "v1" / "install"
    install.mkdir(parents=True)
    (install / "setup.bash").write_text("#!/bin/bash\n")
    return home
