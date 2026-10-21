#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库适配器接口契约测试（v5.2 T-5.2-01）

同一用例集分别跑：
- JsonDatabase（真实实现，临时目录文件）
- SupabaseDatabase（真实适配器逻辑 + 内存版 FakeSupabaseClient）

覆盖用户 CRUD、登录验证、install 版本字段、新手引导、审计日志、配置项、
末位管理员保护等双库共有契约。
"""

import pytest

from core.constants import ALL_PANELS


# ============================================================
# 默认管理员
# ============================================================

class TestDefaultAdmin:
    def test_admin_exists(self, db):
        user = db.get_user("admin")
        assert user is not None
        assert user["role"] == "admin"


# ============================================================
# 用户创建与查询
# ============================================================

class TestCreateAndGetUser:
    def test_create_user_success(self, db, tmp_path):
        ok, info = db.create_user("u1@test.com", "pw123456",
                                  role="user", home_folder_path=str(tmp_path / "ws"))
        assert ok is True
        user = db.get_user("u1@test.com")
        assert user is not None
        assert user["role"] == "user"
        assert user["current_version"] == ""
        assert user["home_folder_path"] == str(tmp_path / "ws")

    def test_get_user_by_username(self, db):
        ok, _ = db.create_user("alice@test.com", "pw", role="user")
        assert ok
        user = db.get_user("alice")  # username = alice（邮箱 @ 前段）
        assert user is not None
        # 注：JsonDatabase 的 get_user 返回体不含 email 键，仅 username
        assert user.get("username") == "alice"

    def test_get_user_by_id(self, db):
        ok, _ = db.create_user("idcheck@test.com", "pw", role="user")
        created = db.get_user("idcheck@test.com")
        found = db.get_user_by_id(created["id"])
        assert found is not None
        assert found["id"] == created["id"]

    def test_get_user_not_found(self, db):
        assert db.get_user("ghost@test.com") is None
        assert db.get_user_by_id("00000000-0000-0000-0000-000000000000") is None

    def test_duplicate_create_fails(self, db):
        ok1, _ = db.create_user("dup@test.com", "pw", role="user")
        ok2, err2 = db.create_user("dup@test.com", "pw", role="user")
        assert ok1 is True
        assert ok2 is False
        assert err2  # 错误信息非空


# ============================================================
# 登录验证
# ============================================================

class TestVerifyLogin:
    def test_login_success(self, db):
        ok, _ = db.create_user("login@test.com", "correct_pw", role="user")
        assert ok
        user = db.verify_login("login@test.com", "correct_pw")
        assert user is not None
        assert user["role"] == "user"

    def test_login_wrong_password(self, db):
        ok, _ = db.create_user("login2@test.com", "correct_pw", role="user")
        assert ok
        assert db.verify_login("login2@test.com", "wrong_pw") is None

    def test_login_unknown_user(self, db):
        assert db.verify_login("nobody@test.com", "whatever") is None


# ============================================================
# 用户更新（含 v5.0/v5.1 版本字段）
# ============================================================

class TestUpdateUser:
    def test_update_version_fields(self, db):
        ok, _ = db.create_user("ver@test.com", "pw", role="user")
        user = db.get_user("ver@test.com")
        assert ok

        notes = {"v2": "测试备注"}
        prev = {"version": "v1", "switched_at": "2026-09-27T00:00:00"}
        assert db.update_user(user["id"], {
            "current_version": "v2",
            "version_notes": notes,
            "previous_version": prev,
        }) is True

        updated = db.get_user("ver@test.com")
        assert updated["current_version"] == "v2"
        assert updated["version_notes"] == notes
        assert updated["previous_version"] == prev

    def test_update_role_and_password(self, db):
        ok, _ = db.create_user("role@test.com", "old_pw", role="user")
        user = db.get_user("role@test.com")
        assert ok

        assert db.update_user(user["id"], {"role": "admin", "password": "new_pw"}) is True
        updated = db.get_user("role@test.com")
        assert updated["role"] == "admin"

    def test_update_nonexistent_user(self, db, request):
        """不存在的用户更新不应抛异常。

        行为差异（适配器现状，记录在案）：
        - JsonDatabase：逐条查找，未命中返回 False
        - SupabaseDatabase：PostgREST 的 no-op update 不报错，返回 True
        """
        adapter = request.node.callspec.params["db"]
        result = db.update_user("00000000-0000-0000-0000-000000000000",
                                {"role": "user"})
        assert isinstance(result, bool)
        if adapter == "json":
            assert result is False
        else:
            assert result is True


# ============================================================
# 删除用户与末位管理员保护
# ============================================================

class TestDeleteUser:
    def test_delete_last_admin_forbidden(self, db):
        admin = db.get_user("admin")
        assert db.delete_user(admin["id"]) is False
        assert db.get_user("admin") is not None

    def test_delete_normal_user(self, db):
        ok, _ = db.create_user("del@test.com", "pw", role="user")
        user = db.get_user("del@test.com")
        assert ok
        assert db.delete_user(user["id"]) is True
        assert db.get_user("del@test.com") is None

    def test_delete_admin_allowed_when_multiple(self, db):
        ok, _ = db.create_user("admin2@test.com", "pw", role="admin")
        assert ok
        second = db.get_user("admin2@test.com")
        first = db.get_user("admin")
        assert db.delete_user(second["id"]) is True
        assert db.get_user("admin") is not None  # 首个 admin 仍在
        _ = first


# ============================================================
# 权限
# ============================================================

class TestPermissions:
    def test_admin_gets_all_panels(self, db):
        assert db.get_user_permissions("admin") == ALL_PANELS

    def test_user_default_permissions(self, db):
        ok, _ = db.create_user("perm@test.com", "pw", role="user")
        assert ok
        perms = db.get_user_permissions("perm@test.com")
        assert isinstance(perms, list)
        assert len(perms) > 0
        assert set(perms) <= set(ALL_PANELS)

    def test_unknown_user_no_permissions(self, db):
        assert db.get_user_permissions("ghost@test.com") == []


# ============================================================
# 新手引导状态
# ============================================================

class TestOnboarding:
    def test_default_state(self, db):
        ok, _ = db.create_user("onb@test.com", "pw", role="user")
        assert ok
        state = db.get_onboarding_state("onb@test.com")
        assert state == {"completed": False, "skipped": False}

    def test_set_and_get(self, db):
        ok, _ = db.create_user("onb2@test.com", "pw", role="user")
        assert ok
        assert db.set_onboarding_state("onb2@test.com", completed=True, skipped=False) is True
        state = db.get_onboarding_state("onb2@test.com")
        assert state["completed"] is True
        assert state["skipped"] is False

    def test_set_nonexistent_user(self, db):
        assert db.set_onboarding_state("ghost@test.com", completed=True) is False


# ============================================================
# 审计日志
# ============================================================

class TestAuditLogs:
    def test_add_and_get(self, db):
        db.add_audit_log("admin", "test_action", "测试详情")
        logs = db.get_audit_logs(limit=10)
        matched = [l for l in logs if l.get("action") == "test_action"]
        assert len(matched) == 1
        assert matched[0]["username"] == "admin"
        assert matched[0]["details"] == "测试详情"

    def test_get_limit(self, db):
        for i in range(5):
            db.add_audit_log("admin", f"bulk_{i}", "")
        logs = db.get_audit_logs(limit=3)
        assert len(logs) == 3


# ============================================================
# 配置项
# ============================================================

class TestConfigs:
    def test_set_and_get(self, db):
        db.set_config("contract_key", {"a": 1})
        assert db.get_config("contract_key") == {"a": 1}

    def test_missing_returns_default(self, db):
        assert db.get_config("no_such_key") is None
        assert db.get_config("no_such_key", "fallback") == "fallback"
