#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/workspace.py 单元测试（v5.2 T-5.2-01）

覆盖：版本目录名校验/清洗、备份目录识别、版本解析（含旧版回退）、
版本列表扫描、备份列表扫描、目录大小计算与缓存。
"""

import os
import time
import types

import pytest
from fastapi import HTTPException

import core.workspace as ws_mod
import database as database_pkg
from core.constants import ROS2_DEFAULT
from core.workspace import (
    VERSION_RESERVED_NAMES,
    is_valid_version_name,
    is_version_backup_entry,
    sanitize_version_name,
    list_user_versions,
    list_version_backups,
    resolve_versioned_install,
    get_admin_install_dir,
    get_user_workspace_paths,
    validate_user_path,
    create_user_workspace,
    queue_version_size_computation,
    invalidate_version_size_cache,
    _compute_dir_size,
    _version_size_cache_key,
)
from core.cache import _memory_cache


# ============================================================
# 版本目录名校验 / 清洗
# ============================================================

class TestVersionName:
    def test_valid_names(self):
        assert is_valid_version_name("v1.0")
        assert is_valid_version_name("test_install20260904_x86_ros2_5.0")
        assert is_valid_version_name("a b c")  # 空格不禁止（sanitize 阶段处理）

    def test_invalid_empty_or_none(self):
        assert not is_valid_version_name("")
        assert not is_valid_version_name(None)

    def test_invalid_reserved_names(self):
        for name in VERSION_RESERVED_NAMES:
            assert not is_valid_version_name(name), name

    def test_invalid_hidden(self):
        assert not is_valid_version_name(".hidden")

    def test_invalid_path_chars(self):
        for bad in ("a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"):
            assert not is_valid_version_name(bad), bad

    def test_sanitize_replaces_separators(self):
        assert sanitize_version_name("a/b\\c d") == "a_b_c_d"

    def test_sanitize_strips_dots_and_none(self):
        assert sanitize_version_name("..name..") == "name"
        assert sanitize_version_name(None) == ""
        assert sanitize_version_name("  ") == ""

    def test_sanitize_length_limit(self):
        assert len(sanitize_version_name("x" * 500)) == 120


# ============================================================
# 备份目录识别
# ============================================================

class TestBackupEntry:
    def test_backup_patterns(self):
        assert is_version_backup_entry("v1.deleted.20260901")
        assert is_version_backup_entry("v1.bak.20260901_120000")
        assert is_version_backup_entry("test.replaced.20260901120000")

    def test_non_backup_entries(self):
        assert not is_version_backup_entry("v1")
        assert not is_version_backup_entry("v1.bak")          # 无时间戳
        assert not is_version_backup_entry("v1.deleted.abc")  # 非数字时间戳
        assert not is_version_backup_entry("install")


# ============================================================
# resolve_versioned_install 解析优先级
# ============================================================

class TestResolveVersionedInstall:
    def test_version_dir_exists(self, ws_home):
        r = resolve_versioned_install(str(ws_home), "v1")
        assert r["is_versioned"] is True
        assert r["current_version"] == "v1"
        assert r["install_dir"] == str(ws_home / "v1" / "install")
        assert r["version_dir"] == str(ws_home / "v1")

    def test_fallback_to_legacy_when_version_missing(self, ws_home):
        # 旧版 install 存在 + 版本目录缺失 → 回退旧版
        (ws_home / "install").mkdir()
        r = resolve_versioned_install(str(ws_home), "nonexistent")
        assert r["is_versioned"] is False
        assert r["current_version"] is None
        assert r["install_dir"] == str(ws_home / "install")

    def test_version_dir_missing_no_legacy(self, ws_home):
        # 版本目录缺失且无旧版 → 仍指向版本路径（等待上传）
        r = resolve_versioned_install(str(ws_home), "waiting_upload")
        assert r["is_versioned"] is True
        assert r["current_version"] == "waiting_upload"
        assert r["install_dir"] == str(ws_home / "waiting_upload" / "install")

    def test_empty_version_uses_legacy(self, ws_home):
        (ws_home / "install").mkdir()
        for empty in ("", "   ", None):
            r = resolve_versioned_install(str(ws_home), empty)
            assert r["is_versioned"] is False
            assert r["install_dir"] == str(ws_home / "install")

    def test_invalid_version_name_falls_back(self, ws_home):
        (ws_home / "install").mkdir()
        r = resolve_versioned_install(str(ws_home), "Docker")  # 保留名
        assert r["is_versioned"] is False
        assert r["install_dir"] == str(ws_home / "install")

    def test_nonexistent_home(self, tmp_path):
        r = resolve_versioned_install(str(tmp_path / "nope"), "v1")
        assert r["is_versioned"] is True  # 无旧版 → 指向版本路径
        assert r["current_version"] == "v1"


# ============================================================
# list_user_versions 扫描
# ============================================================

class TestListUserVersions:
    def _build_home(self, tmp_path):
        home = tmp_path / "ws"
        # 合法版本
        (home / "alpha" / "install" / "setup.bash").parent.mkdir(parents=True)
        (home / "alpha" / "install" / "setup.bash").write_text("")
        (home / "beta" / "install").mkdir(parents=True)  # 无 setup.bash，仍是版本
        # 应排除的目录
        (home / "Docker").mkdir()
        (home / "bags").mkdir()
        (home / "install").mkdir()                       # 旧版 install 非版本
        (home / "v9.deleted.20260901" / "install").mkdir(parents=True)  # 备份
        (home / "v9.bak.20260901" / "install").mkdir(parents=True)      # 备份
        (home / ".hidden" / "install").mkdir(parents=True)
        (home / "install.bak.20260901").mkdir()
        (home / "_upload_tmp" / "install").mkdir(parents=True)
        (home / "noinstall").mkdir()                     # 无 install 子目录
        return home

    def test_scan_filters_and_sort(self, tmp_path):
        home = self._build_home(tmp_path)
        versions = list_user_versions(str(home))
        assert [v["version"] for v in versions] == ["alpha", "beta"]
        by_name = {v["version"]: v for v in versions}
        assert by_name["alpha"]["has_setup_bash"] is True
        assert by_name["beta"]["has_setup_bash"] is False
        assert by_name["alpha"]["mtime"] is not None
        assert by_name["alpha"]["size_bytes"] is None  # 未计算时为 None

    def test_scan_nonexistent_home(self, tmp_path):
        assert list_user_versions(str(tmp_path / "nope")) == []
        assert list_user_versions("") == []


# ============================================================
# list_version_backups 扫描
# ============================================================

class TestListVersionBackups:
    def test_scan_backups(self, tmp_path):
        home = tmp_path / "ws"
        (home / "v1.deleted.20260901_000000" / "install").mkdir(parents=True)
        (home / "v2.bak.20260902_000000" / "install").mkdir(parents=True)
        (home / "v3.replaced.20260903_000000" / "install").mkdir(parents=True)
        (home / "v4").mkdir()  # 非备份
        backups = list_version_backups(str(home))
        assert len(backups) == 3
        by_entry = {b["entry"]: b for b in backups}
        assert by_entry["v1.deleted.20260901_000000"]["type"] == "deleted"
        assert by_entry["v1.deleted.20260901_000000"]["origin"] == "v1"
        assert by_entry["v1.deleted.20260901_000000"]["timestamp"] == "20260901_000000"
        assert by_entry["v2.bak.20260902_000000"]["type"] == "bak"
        assert by_entry["v3.replaced.20260903_000000"]["type"] == "replaced"

    def test_empty_home(self, tmp_path):
        home = tmp_path / "ws"
        home.mkdir()
        assert list_version_backups(str(home)) == []


# ============================================================
# 目录大小计算 + 缓存
# ============================================================

class TestDirSize:
    def test_compute_dir_size(self, tmp_path):
        d = tmp_path / "tree"
        d.mkdir()
        (d / "a.bin").write_bytes(b"x" * 100)
        sub = d / "sub"
        sub.mkdir()
        (sub / "b.bin").write_bytes(b"x" * 50)
        assert _compute_dir_size(str(d)) == 150

    def test_queue_computation_fills_cache(self, tmp_path, monkeypatch):
        """queue_version_size_computation 后台补算 —— 将 Thread 替换为同步执行以确定性验证"""
        home = tmp_path / "ws"
        install = home / "v1" / "install"
        install.mkdir(parents=True)
        (install / "setup.bash").write_bytes(b"x" * 42)

        import core.workspace as ws_mod

        class _SyncThread:
            def __init__(self, target=None, **kwargs):
                self._target = target

            def start(self):
                if self._target:
                    self._target()

        monkeypatch.setattr(ws_mod.threading, "Thread", _SyncThread)
        queue_version_size_computation(str(home), [{"version": "v1"}])
        cached = _memory_cache.get(_version_size_cache_key(str(home), "v1"))
        assert cached == 42

    def test_invalidate_cache(self, tmp_path):
        home = tmp_path / "ws"
        key = _version_size_cache_key(str(home), "v1")
        _memory_cache.set(key, 123, ttl=60)
        invalidate_version_size_cache(str(home), "v1")
        assert _memory_cache.get(key) is None

        _memory_cache.set(key, 456, ttl=60)
        _memory_cache.set(_version_size_cache_key(str(home), "v2"), 789, ttl=60)
        invalidate_version_size_cache(str(home))  # 全部失效
        assert _memory_cache.get(key) is None
        assert _memory_cache.get(_version_size_cache_key(str(home), "v2")) is None


# ============================================================
# get_user_workspace_paths（普通用户路径，不依赖 db）
# ============================================================

class TestWorkspacePaths:
    def test_user_versioned_paths(self, ws_home):
        user = {"role": "user", "home_folder_path": str(ws_home), "current_version": "v1"}
        paths = get_user_workspace_paths(user)
        assert paths["is_versioned"] is True
        assert paths["current_version"] == "v1"
        assert paths["host_install"] == str(ws_home / "v1" / "install")
        assert paths["launch_dir"].startswith(paths["host_install"])
        assert [v["version"] for v in paths["versions"]] == ["v1"]
        assert paths["scripts_dir"] == str(ws_home / "Docker" / "scripts")
        assert paths["bag_storage"] == str(ws_home / "Docker" / "bags")

    def test_user_legacy_fallback(self, ws_home):
        (ws_home / "install").mkdir()
        user = {"role": "user", "home_folder_path": str(ws_home), "current_version": ""}
        paths = get_user_workspace_paths(user)
        assert paths["is_versioned"] is False
        assert paths["current_version"] is None
        assert paths["host_install"] == str(ws_home / "install")

    def test_non_admin_ignores_target_user(self, ws_home):
        user = {"role": "user", "home_folder_path": str(ws_home), "current_version": "v1"}
        paths = get_user_workspace_paths(user, target_user="someone_else")
        assert paths["host_install"] == str(ws_home / "v1" / "install")

    def test_user_without_home_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            get_user_workspace_paths({"role": "user", "home_folder_path": "", "current_version": ""})
        assert e.value.status_code == 403


# ============================================================
# validate_user_path 路径遍历保护
# ============================================================

class TestValidateUserPath:
    def test_inside_root_ok(self, tmp_path):
        user = {"role": "user", "home_folder_path": str(tmp_path)}
        assert validate_user_path(str(tmp_path / "sub" / "file.txt"), user) is True

    def test_escape_root_forbidden(self, tmp_path):
        from fastapi import HTTPException
        user = {"role": "user", "home_folder_path": str(tmp_path / "ws")}
        (tmp_path / "ws").mkdir()
        with pytest.raises(HTTPException) as e:
            validate_user_path(str(tmp_path / "other" / "secret"), user)
        assert e.value.status_code == 403

    def test_traversal_attack_forbidden(self, tmp_path):
        from fastapi import HTTPException
        user = {"role": "user", "home_folder_path": str(tmp_path / "ws")}
        (tmp_path / "ws").mkdir()
        with pytest.raises(HTTPException):
            validate_user_path(str(tmp_path / "ws" / ".." / "escape"), user)

    def test_admin_global_pass(self):
        admin = {"role": "admin"}
        assert validate_user_path("/any/path", admin) is True

    def test_user_without_home_forbidden(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            validate_user_path("/some/path", {"role": "user", "home_folder_path": ""})
        assert e.value.status_code == 403


# ============================================================
# 扫描异常分支（listdir / stat OSError 静默降级）
# ============================================================

class TestScanErrorPaths:
    def test_listdir_error_returns_empty(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        home.mkdir()

        def boom(p):
            raise PermissionError("denied")

        monkeypatch.setattr(ws_mod.os, "listdir", boom)
        assert list_user_versions(str(home)) == []
        assert list_version_backups(str(home)) == []

    def test_stat_error_mtime_none(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        (home / "alpha" / "install" / "setup.bash").parent.mkdir(parents=True)
        (home / "alpha" / "install" / "setup.bash").write_text("")
        backup_entry = home / "v1.deleted.20260901_000000"
        backup_entry.mkdir()
        version_dir = home / "alpha"

        real_stat = os.stat

        def fake_stat(p, *a, **k):
            # 只对 mtime 探测目标抛错；isdir/isfile 的 stat 探测正常放行
            if str(p) in (str(version_dir), str(backup_entry)):
                raise OSError("gone")
            return real_stat(p, *a, **k)

        monkeypatch.setattr(ws_mod.os, "stat", fake_stat)
        versions = list_user_versions(str(home))
        assert [v["version"] for v in versions] == ["alpha"]
        assert versions[0]["mtime"] is None
        backups = list_version_backups(str(home))
        assert backups[0]["mtime"] is None

    def test_backups_nonexistent_home(self, tmp_path):
        assert list_version_backups(str(tmp_path / "nope")) == []
        assert list_version_backups("") == []


# ============================================================
# queue_version_size_computation 边界分支
# ============================================================

class _NoStartThread:
    """记录 start 调用但不执行（用于断言线程未启动）"""

    started = 0

    def __init__(self, target=None, **kwargs):
        self._target = target

    def start(self):
        _NoStartThread.started += 1


class _SyncRunThread:
    """同步执行 target（用于确定性地验证 worker 逻辑）"""

    def __init__(self, target=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class _BoomThread:
    def __init__(self, target=None, **kwargs):
        pass

    def start(self):
        raise RuntimeError("cannot start thread")


class TestQueueEdgeCases:
    def test_invalid_home_noop(self, tmp_path):
        queue_version_size_computation("", [{"version": "v1"}])
        queue_version_size_computation(str(tmp_path / "nope"), [{"version": "v1"}])

    def test_invalid_entries_and_empty_pending(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        home.mkdir()
        _NoStartThread.started = 0
        monkeypatch.setattr(ws_mod, "threading",
                            types.SimpleNamespace(Thread=_NoStartThread))
        # 版本名为空 / 条目无 version 键 → 全部跳过，pending 为空不起线程
        queue_version_size_computation(str(home), [{"version": ""}, {"other": 1}])
        assert _NoStartThread.started == 0

    def test_cached_version_not_requeued(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        (home / "v1" / "install").mkdir(parents=True)
        _memory_cache.set(_version_size_cache_key(str(home), "v1"), 1, ttl=60)
        _NoStartThread.started = 0
        monkeypatch.setattr(ws_mod, "threading",
                            types.SimpleNamespace(Thread=_NoStartThread))
        queue_version_size_computation(str(home), [{"version": "v1"}])
        assert _NoStartThread.started == 0  # 已缓存，无需补算

    def test_worker_dir_missing_skipped(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        home.mkdir()
        monkeypatch.setattr(ws_mod, "threading",
                            types.SimpleNamespace(Thread=_SyncRunThread))
        # pending 中的目录已消失 → worker 内 continue，不抛异常不写缓存
        queue_version_size_computation(str(home), [{"version": "ghost"}])
        assert _memory_cache.get(_version_size_cache_key(str(home), "ghost")) is None

    def test_worker_exception_swallowed(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        (home / "v1" / "install").mkdir(parents=True)
        monkeypatch.setattr(ws_mod, "threading",
                            types.SimpleNamespace(Thread=_SyncRunThread))

        def boom(path):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(ws_mod, "_compute_dir_size", boom)
        queue_version_size_computation(str(home), [{"version": "v1"}])  # 不应抛出

    def test_thread_start_failure_swallowed(self, tmp_path, monkeypatch):
        home = tmp_path / "ws"
        (home / "v1" / "install").mkdir(parents=True)
        monkeypatch.setattr(ws_mod, "threading",
                            types.SimpleNamespace(Thread=_BoomThread))
        queue_version_size_computation(str(home), [{"version": "v1"}])  # 不应抛出

    def test_invalidate_empty_home_noop(self):
        invalidate_version_size_cache("")
        invalidate_version_size_cache(None)


# ============================================================
# get_admin_install_dir（依赖 database.db，monkeypatch 注入假 db）
# ============================================================

def _install_fake_db(monkeypatch, users_by_name):
    """向 database 包注入假 db 单例（workspace 函数内 from database import db 生效）"""
    fake = types.SimpleNamespace(
        get_user=lambda name: users_by_name.get(name),
        get_user_by_id=lambda uid: None,
    )
    monkeypatch.setattr(database_pkg, "db", fake, raising=False)
    return fake


class TestAdminInstallDir:
    def test_resolves_admin_current_version(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        (base / "v1" / "install").mkdir(parents=True)
        monkeypatch.setitem(ROS2_DEFAULT, "host_ws", str(base))
        _install_fake_db(monkeypatch, {"admin": {"current_version": "v1"}})
        assert get_admin_install_dir() == str(base / "v1" / "install")

    def test_admin_without_version_uses_legacy(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setitem(ROS2_DEFAULT, "host_ws", str(base))
        _install_fake_db(monkeypatch, {"admin": {"current_version": ""}})
        assert get_admin_install_dir() == str(base / "install")

    def test_db_error_falls_back_to_legacy(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setitem(ROS2_DEFAULT, "host_ws", str(base))

        def boom(name):
            raise RuntimeError("db down")

        monkeypatch.setattr(database_pkg, "db",
                            types.SimpleNamespace(get_user=boom, get_user_by_id=boom),
                            raising=False)
        assert get_admin_install_dir() == str(base / "install")


# ============================================================
# validate_user_path：管理员 + target_user 分支
# ============================================================

class TestValidateUserPathAdminTarget:
    def test_admin_target_user_inside_ok(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        _install_fake_db(monkeypatch, {"alice": {"home_folder_path": str(ws)}})
        admin = {"role": "admin", "home_folder_path": ""}
        assert validate_user_path(str(ws / "file.txt"), admin, target_user="alice") is True

    def test_admin_target_user_escape_forbidden(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        _install_fake_db(monkeypatch, {"alice": {"home_folder_path": str(ws)}})
        admin = {"role": "admin", "home_folder_path": ""}
        with pytest.raises(HTTPException) as e:
            validate_user_path(str(tmp_path / "outside"), admin, target_user="alice")
        assert e.value.status_code == 403

    def test_admin_target_user_without_home_forbidden(self, monkeypatch):
        _install_fake_db(monkeypatch, {"alice": {"home_folder_path": ""}})
        admin = {"role": "admin", "home_folder_path": ""}
        with pytest.raises(HTTPException) as e:
            validate_user_path("/any", admin, target_user="alice")
        assert e.value.status_code == 403


# ============================================================
# get_user_workspace_paths：管理员分支
# ============================================================

class TestWorkspacePathsAdmin:
    def _patch_ros_default(self, monkeypatch, base):
        host_install = base / "install"
        rel = os.path.join("simulation_launches", "share", "simulation_launches")
        for key, val in {
            "host_ws": str(base),
            "host_install": str(host_install),
            "launch_dir": str(host_install / rel / "launch"),
            "config_dir": str(host_install / rel / "config"),
            "scripts_dir": str(base / "Docker" / "scripts"),
            "logs_dir": str(base / "Docker" / "logs"),
            "bag_storage": str(base / "Docker" / "bags"),
            "backup_dir": str(base / "Docker" / "bk"),
            "container_install": "/opt/ros2_ws/install",
            "container_bag_path": "/root/bags",
            "container_bag_path_alt": "/bags",
        }.items():
            monkeypatch.setitem(ROS2_DEFAULT, key, val)
        return rel

    def test_admin_global_paths_versioned(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        (base / "v1" / "install" / "setup.bash").parent.mkdir(parents=True)
        (base / "v1" / "install" / "setup.bash").write_text("")
        rel = self._patch_ros_default(monkeypatch, base)
        admin = {"role": "admin", "current_version": "v1", "home_folder_path": str(tmp_path)}
        paths = get_user_workspace_paths(admin)
        assert paths["is_versioned"] is True
        assert paths["current_version"] == "v1"
        assert paths["host_ws"] == str(base)
        assert paths["host_install"] == str(base / "v1" / "install")
        assert paths["launch_dir"] == str(base / "v1" / "install" / rel / "launch")
        assert paths["config_dir"].startswith(paths["host_install"])
        assert paths["bk_backups_dir"] == str(base / "Docker" / "bk" / ".bk_backups")
        assert [v["version"] for v in paths["versions"]] == ["v1"]

    def test_admin_global_paths_legacy(self, tmp_path, monkeypatch):
        base = tmp_path / "base"
        (base / "install").mkdir(parents=True)
        self._patch_ros_default(monkeypatch, base)
        admin = {"role": "admin", "current_version": "", "home_folder_path": str(tmp_path)}
        paths = get_user_workspace_paths(admin)
        assert paths["is_versioned"] is False
        assert paths["host_install"] == str(base / "install")

    def test_admin_target_user_uses_target_workspace(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        install = ws / "vA" / "install"
        install.mkdir(parents=True)
        (install / "setup.bash").write_text("")
        self._patch_ros_default(monkeypatch, tmp_path / "base")
        _install_fake_db(monkeypatch, {
            "alice": {"role": "user", "home_folder_path": str(ws), "current_version": "vA"},
        })
        admin = {"role": "admin", "current_version": "v1", "home_folder_path": ""}
        paths = get_user_workspace_paths(admin, target_user="alice")
        assert paths["host_ws"] == str(ws)
        assert paths["host_install"] == str(ws / "vA" / "install")
        assert paths["target_user"] == "alice"

    def test_admin_target_not_found_404(self, tmp_path, monkeypatch):
        """目标用户不存在 + admin 自身无 home → 404（回退 effective_user=admin 后无目录）"""
        self._patch_ros_default(monkeypatch, tmp_path / "base")
        _install_fake_db(monkeypatch, {})  # ghost 用户不存在
        admin = {"role": "admin", "current_version": "v1", "home_folder_path": ""}
        with pytest.raises(HTTPException) as e:
            get_user_workspace_paths(admin, target_user="ghost")
        assert e.value.status_code == 404

    def test_admin_target_user_no_home_403(self, tmp_path, monkeypatch):
        """目标用户存在但 home 为空（普通用户）→ 403 用户工作目录未配置"""
        self._patch_ros_default(monkeypatch, tmp_path / "base")
        _install_fake_db(monkeypatch, {
            "bob": {"role": "user", "home_folder_path": "", "current_version": ""},
        })
        admin = {"role": "admin", "home_folder_path": ""}
        with pytest.raises(HTTPException) as e:
            get_user_workspace_paths(admin, target_user="bob")
        assert e.value.status_code == 403


# ============================================================
# create_user_workspace（Template 复制 / 空目录兜底）
# ============================================================

class TestCreateUserWorkspace:
    def _redirect_home(self, monkeypatch, base):
        real_expanduser = os.path.expanduser

        def fake_expanduser(p):
            if p == "~/robotruck_ros2":
                return str(base)
            if p == "~/robotruck_ros2/Template":
                return str(base / "Template")
            return real_expanduser(p)

        monkeypatch.setattr(ws_mod.os.path, "expanduser", fake_expanduser)
        monkeypatch.setattr(ws_mod.subprocess, "run", lambda *a, **k: None)  # 跳过 chown

    def test_create_from_template(self, tmp_path, monkeypatch):
        base = tmp_path / "robotruck_ros2"
        template = base / "Template" / "scripts"
        template.mkdir(parents=True)
        (template / "run.sh").write_text("#!/bin/bash\n")
        self._redirect_home(monkeypatch, base)

        user_home = create_user_workspace("alice")
        assert user_home == str(base / "alice")
        assert os.path.isfile(base / "alice" / "Docker" / "scripts" / "run.sh")

    def test_existing_docker_not_overwritten(self, tmp_path, monkeypatch):
        base = tmp_path / "robotruck_ros2"
        template = base / "Template"
        template.mkdir(parents=True)
        (template / "from_template.txt").write_text("template")
        self._redirect_home(monkeypatch, base)
        docker_dir = base / "alice" / "Docker"
        docker_dir.mkdir(parents=True)
        (docker_dir / "user_data.txt").write_text("user")

        create_user_workspace("alice")
        assert os.path.isfile(docker_dir / "user_data.txt")       # 用户数据保留
        assert not os.path.exists(docker_dir / "from_template.txt")  # 未被模板覆盖

    def test_fallback_empty_dirs_without_template(self, tmp_path, monkeypatch):
        base = tmp_path / "robotruck_ros2"
        base.mkdir(parents=True)  # 无 Template
        self._redirect_home(monkeypatch, base)

        user_home = create_user_workspace("bob")
        docker_dir = base / "bob" / "Docker"
        for sub in ("bags", "bk", "logs", "scripts"):
            assert os.path.isdir(docker_dir / sub), sub
        assert os.path.isdir(user_home)
