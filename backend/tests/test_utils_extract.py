#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/utils.py 的 extract_versioned_install / _prune_backups 单元测试（v5.2 T-5.2-01）

通过临时目录构造各类压缩包结构，覆盖：
X/install、顶层即 install、顶层为 install 内容、非法结构、非法版本名、
同名替换备份、备份保留数量清理。
"""

import os
import tarfile
import zipfile

import pytest

from core.utils import extract_versioned_install, _prune_backups


# ============================================================
# 压缩包构造工具
# ============================================================

def make_zip(path, entries):
    """entries: {相对路径: 内容(bytes)}，目录以 '/' 结尾"""
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            if name.endswith("/"):
                # zipfile 目录条目可省略，成员路径已隐含目录
                continue
            zf.writestr(name, content)


def make_tar(path, entries, mode="w:gz"):
    with tarfile.open(path, mode) as tf:
        for name, content in entries.items():
            if name.endswith("/"):
                continue
            import io
            data = content.encode() if isinstance(content, str) else content
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


SETUP = "#!/bin/bash\n# mock setup\n"


# ============================================================
# 四种合法结构识别
# ============================================================

class TestExtractStructures:
    def test_zip_topdir_with_install(self, tmp_path):
        """结构 X/install/setup.bash → 版本名 = X"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"myver/install/setup.bash": SETUP})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "upload")
        assert version == "myver"
        assert os.path.isfile(ws / "myver" / "install" / "setup.bash")

    def test_zip_topdir_is_install_content(self, tmp_path):
        """结构 X/setup.bash（X 即 install 内容）→ 版本名 = 压缩包文件名，自动包一层"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"myver/setup.bash": SETUP, "myver/lib/libtest.so": b"\x7fELF"})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "upload_pkg")
        assert version == "upload_pkg"
        assert os.path.isfile(ws / "upload_pkg" / "install" / "setup.bash")
        assert os.path.isfile(ws / "upload_pkg" / "install" / "lib" / "libtest.so")

    def test_zip_top_install_dir(self, tmp_path):
        """结构 install/setup.bash → 版本名 = 压缩包文件名"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"install/setup.bash": SETUP})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "upload_pkg")
        assert version == "upload_pkg"
        assert os.path.isfile(ws / "upload_pkg" / "install" / "setup.bash")

    def test_zip_top_is_install_content(self, tmp_path):
        """结构 setup.bash 直接位于顶层 → 包一层 install/"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"setup.bash": SETUP, "share/pkg.xml": b"<pkg/>"})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "upload_pkg")
        assert version == "upload_pkg"
        assert os.path.isfile(ws / "upload_pkg" / "install" / "setup.bash")
        assert os.path.isfile(ws / "upload_pkg" / "install" / "share" / "pkg.xml")

    def test_tar_gz_topdir_with_install(self, tmp_path):
        """tar.gz 结构 X/install/ → 版本名 = X"""
        archive = tmp_path / "upload.tar.gz"
        make_tar(archive, {"tver/install/setup.bash": SETUP})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "upload")
        assert version == "tver"
        assert os.path.isfile(ws / "tver" / "install" / "setup.bash")

    def test_tar_top_install_dir(self, tmp_path):
        """tar 结构 install/ → 版本名 = 压缩包文件名"""
        archive = tmp_path / "upload.tar"
        make_tar(archive, {"install/setup.bash": SETUP}, mode="w")
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "tar_pkg")
        assert version == "tar_pkg"
        assert os.path.isfile(ws / "tar_pkg" / "install" / "setup.bash")

    def test_multi_top_entries_with_install(self, tmp_path):
        """顶层多条目且含 install/ 目录 → install 分支（版本名 = 压缩包文件名）"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"install/setup.bash": SETUP, "readme.txt": "hi"})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "multi_pkg")
        assert version == "multi_pkg"
        assert os.path.isfile(ws / "multi_pkg" / "install" / "setup.bash")

    def test_empty_fallback_version_name(self, tmp_path):
        """顶层即 install 内容且 fallback 名清洗后为空 → 兜底 install_version"""
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"setup.bash": SETUP})
        ws = tmp_path / "ws"
        ws.mkdir()
        version = extract_versioned_install(str(archive), str(ws), "...")
        assert version == "install_version"
        assert os.path.isfile(ws / "install_version" / "install" / "setup.bash")


# ============================================================
# 非法结构 / 格式
# ============================================================

class TestExtractErrors:
    def test_not_an_archive(self, tmp_path):
        plain = tmp_path / "plain.txt"
        plain.write_text("just text")
        with pytest.raises(ValueError, match="不支持的压缩包格式"):
            extract_versioned_install(str(plain), str(tmp_path / "ws"), "x")

    def test_empty_archive(self, tmp_path):
        archive = tmp_path / "empty.zip"
        make_zip(archive, {})
        with pytest.raises(ValueError, match="压缩包为空"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")

    def test_only_hidden_entries(self, tmp_path):
        archive = tmp_path / "hidden.zip"
        make_zip(archive, {".DS_Store": b"junk"})
        with pytest.raises(ValueError, match="压缩包为空"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")

    def test_topdir_without_install(self, tmp_path):
        archive = tmp_path / "noinstall.zip"
        make_zip(archive, {"foo/readme.txt": "hi"})
        with pytest.raises(ValueError, match="未找到 install 目录或 setup.bash"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")

    def test_multi_top_without_install(self, tmp_path):
        archive = tmp_path / "multi.zip"
        make_zip(archive, {"a/readme.txt": "1", "b/readme.txt": "2"})
        with pytest.raises(ValueError, match="未找到 install 目录或 setup.bash"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")

    def test_reserved_topdir_name(self, tmp_path):
        """顶层目录为保留名（如 Docker）→ 无效版本名拒绝"""
        archive = tmp_path / "reserved.zip"
        make_zip(archive, {"Docker/install/setup.bash": SETUP})
        with pytest.raises(ValueError, match="无效的版本目录名"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")

    def test_install_without_setup_bash(self, tmp_path):
        """X/install/ 结构被识别，但解压后 install 内缺 setup.bash → 校验失败"""
        archive = tmp_path / "nosetup.zip"
        make_zip(archive, {"v1/install/share/pkg.xml": b"<pkg/>"})
        with pytest.raises(ValueError, match="缺少 setup.bash"):
            extract_versioned_install(str(archive), str(tmp_path / "ws"), "x")


# ============================================================
# 同名替换备份
# ============================================================

class TestReplaceBackup:
    def test_same_name_replaced_with_backup(self, tmp_path):
        archive = tmp_path / "upload.zip"
        make_zip(archive, {"v1/install/setup.bash": SETUP + "# new\n"})
        ws = tmp_path / "ws"
        old_install = ws / "v1" / "install"
        old_install.mkdir(parents=True)
        (old_install / "setup.bash").write_text("# old version\n")
        (old_install / "marker.txt").write_text("old")

        version = extract_versioned_install(str(archive), str(ws), "upload")
        assert version == "v1"
        # 新内容就位
        assert "new" in (ws / "v1" / "install" / "setup.bash").read_text()
        # 旧目录整体进入 .replaced.<时间戳> 备份
        backups = [e for e in os.listdir(ws) if e.startswith("v1.replaced.")]
        assert len(backups) == 1
        assert os.path.isfile(ws / backups[0] / "install" / "marker.txt")


# ============================================================
# _prune_backups 保留数量
# ============================================================

class TestPruneBackups:
    def test_keep_latest_two(self, tmp_path):
        parent = tmp_path / "ws"
        for ts in ("20260101_000000", "20260102_000000", "20260103_000000"):
            (parent / f"v1.replaced.{ts}").mkdir(parents=True)
        (parent / "unrelated").mkdir()

        _prune_backups("v1.replaced.", str(parent), keep=2)

        remain = sorted(e for e in os.listdir(parent) if e.startswith("v1.replaced."))
        assert remain == ["v1.replaced.20260102_000000", "v1.replaced.20260103_000000"]
        assert os.path.isdir(parent / "unrelated")  # 非备份目录不受影响

    def test_nonexistent_parent_no_error(self, tmp_path):
        _prune_backups("x.", str(tmp_path / "nope"), keep=2)  # 不应抛异常
