#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户工作空间管理模块

v5.0：install 目录版本化管理
- 版本目录结构：<工作空间>/<版本名>/install/（如 ~/robotruck_ros2/test_install20260904_x86_ros2_5.0/install）
- 用户可在首页切换版本，选择持久化于用户表 current_version 字段
- 未选择版本时回退旧版 <工作空间>/install 路径，保证存量环境兼容
"""

import os
import re
import shutil
import subprocess
import threading
from fastapi import HTTPException

from logger import logger
from core.constants import ROS2_DEFAULT
from core.cache import _memory_cache

# ============================================================
# v5.0 版本目录管理
# ============================================================

# 工作空间下的保留目录名：这些目录不是版本目录，扫描/命名时需排除
VERSION_RESERVED_NAMES = {"Docker", "Template", "install", "bags", "logs", "scripts", "bk"}

# 版本目录相关的备份/临时文件前缀（非版本目录）
_VERSION_SKIP_PREFIXES = ("install.bak", "install.deleted", "install.replaced", "_upload_", ".")

# 备份目录后缀模式：<名称>.deleted.<时间戳> / <名称>.bak.<时间戳>（删除版本/旧版时的自动备份）
# 时间戳兼容两种格式：纯数字（%Y%m%d%H%M%S，api.py 删除版本）与含下划线（%Y%m%d_%H%M%S，utils.py 同名替换）
_VERSION_BACKUP_RE = re.compile(r'\.(deleted|bak|replaced)\.[\d_]{8,}$')


def is_version_backup_entry(entry: str) -> bool:
    """判断工作空间下的目录名是否为删除/替换产生的备份目录（非可用版本）"""
    return bool(_VERSION_BACKUP_RE.search(entry))


def sanitize_version_name(name: str) -> str:
    """清理版本目录名：去除路径分隔符与空白（防路径穿越），限制长度"""
    name = (name or "").strip()
    name = re.sub(r'[\\/\s]+', '_', name)
    name = name.strip('.').strip()
    return name[:120]


def is_valid_version_name(version: str) -> bool:
    """校验版本目录名：非空、非保留名、不含路径分隔符等危险字符、不以点开头"""
    if not version or version in VERSION_RESERVED_NAMES:
        return False
    if version.startswith('.'):
        return False
    # 禁止路径分隔符与控制字符
    return bool(re.fullmatch(r'[^/\\:*?"<>|\x00-\x1f]+', version))


def list_user_versions(home_folder_path: str):
    """扫描工作空间下的所有版本目录（包含 install/ 子目录的目录）

    v5.1：附带元数据 —— mtime（目录 stat，廉价）与 size_bytes（缓存命中才有，
    未计算时为 None，由 queue_version_size_computation 后台补算）。

    :return: [{"version": 目录名, "has_setup_bash": bool, "mtime": float|None,
               "size_bytes": int|None}, ...] 按目录名排序
    """
    versions = []
    home = os.path.expanduser(home_folder_path) if home_folder_path else ""
    if not home or not os.path.isdir(home):
        return versions
    try:
        entries = sorted(os.listdir(home))
    except Exception:
        return versions
    for entry in entries:
        if entry.startswith(_VERSION_SKIP_PREFIXES) or entry in VERSION_RESERVED_NAMES:
            continue
        if is_version_backup_entry(entry):
            continue
        vinstall = os.path.join(home, entry, "install")
        if os.path.isdir(vinstall):
            mtime = None
            try:
                mtime = os.stat(os.path.join(home, entry)).st_mtime
            except OSError:
                pass
            versions.append({
                "version": entry,
                "has_setup_bash": os.path.isfile(os.path.join(vinstall, "setup.bash")),
                "mtime": mtime,
                "size_bytes": _memory_cache.get(_version_size_cache_key(home, entry)),
            })
    return versions


def _version_size_cache_key(home: str, version: str) -> str:
    return f"version_size:{home}:{version}"


def invalidate_version_size_cache(home_folder_path: str, version: str = None):
    """版本目录大小缓存失效（上传/删除/恢复版本后调用）"""
    home = os.path.expanduser(home_folder_path) if home_folder_path else ""
    if not home:
        return
    if version is None:
        _memory_cache.invalidate(prefix=f"version_size:{home}:")
    else:
        _memory_cache.invalidate(prefix=_version_size_cache_key(home, version))


def _compute_dir_size(path: str) -> int:
    """递归累计目录大小（字节）。符号链接不跟随、不计入。"""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def queue_version_size_computation(home_folder_path: str, versions):
    """v5.1：后台线程补算版本目录大小（计算结果写缓存，TTL 10 分钟）

    只计算尚未缓存（size_bytes 为 None）的版本，避免重复扫描大目录。
    目录较大时扫描耗时数秒，故异步执行不阻塞接口；前端首次显示"—"，
    后续请求命中缓存即可拿到数值。
    """
    home = os.path.expanduser(home_folder_path) if home_folder_path else ""
    if not home or not os.path.isdir(home):
        return
    pending = []
    for v in versions or []:
        name = v.get("version")
        if not name:
            continue
        if _memory_cache.get(_version_size_cache_key(home, name)) is None:
            pending.append(name)
    if not pending:
        return

    def _worker():
        for name in pending:
            vdir = os.path.join(home, name)
            if not os.path.isdir(vdir):
                continue
            try:
                size = _compute_dir_size(vdir)
                _memory_cache.set(_version_size_cache_key(home, name), size, ttl=600)
            except Exception as e:
                logger.warning(f"计算版本目录大小失败: {vdir}: {e}")

    try:
        threading.Thread(target=_worker, daemon=True, name="version-size-calc").start()
    except Exception as e:
        logger.warning(f"启动版本大小计算线程失败: {e}")


def list_version_backups(home_folder_path: str):
    """v5.1：扫描工作空间下的版本备份目录（.deleted/.bak/.replaced.<时间戳>）

    :return: [{"entry": 目录名, "type": deleted|bak|replaced, "origin": 原版本名,
               "timestamp": 时间戳字符串, "mtime": float|None, "size_bytes": int|None}, ...]
             按目录名倒序（新备份在前）
    """
    backups = []
    home = os.path.expanduser(home_folder_path) if home_folder_path else ""
    if not home or not os.path.isdir(home):
        return backups
    try:
        entries = sorted(os.listdir(home), reverse=True)
    except Exception:
        return backups
    for entry in entries:
        m = _VERSION_BACKUP_RE.search(entry)
        if not m:
            continue
        origin = entry[:m.start()]
        mtime = None
        try:
            mtime = os.stat(os.path.join(home, entry)).st_mtime
        except OSError:
            pass
        backups.append({
            "entry": entry,
            "type": m.group(1),
            "origin": origin,
            "timestamp": entry.rsplit(".", 1)[-1],
            "mtime": mtime,
            "size_bytes": _memory_cache.get(_version_size_cache_key(home, entry)),
        })
    return backups


def resolve_versioned_install(home_folder_path: str, current_version: str) -> dict:
    """根据用户选择的版本解析 install 目录（含旧版回退）

    解析优先级：
    1. current_version 非空且 <home>/<version>/install 存在 → 版本目录
    2. 旧版 <home>/install 存在 → 旧版路径（current_version 置空，保证存量兼容）
    3. current_version 非空但目录缺失且无旧版 → 仍指向版本路径（等待上传）
    4. 兜底 → 旧版路径

    :return: {"current_version": str|None, "install_dir": str, "version_dir": str, "is_versioned": bool}
    """
    home = os.path.expanduser(home_folder_path) if home_folder_path else ""
    legacy_install = os.path.join(home, "install")
    legacy_exists = os.path.isdir(legacy_install)
    version = (current_version or "").strip()

    if version and is_valid_version_name(version):
        version_dir = os.path.join(home, version)
        vinstall = os.path.join(version_dir, "install")
        if os.path.isdir(vinstall) or not legacy_exists:
            return {
                "current_version": version,
                "install_dir": vinstall,
                "version_dir": version_dir,
                "is_versioned": True,
            }

    return {
        "current_version": None,
        "install_dir": legacy_install,
        "version_dir": home,
        "is_versioned": False,
    }


def get_admin_install_dir() -> str:
    """获取管理员全局当前生效的 install 目录（版本感知）

    供宿主机 ROS2 命令、脚本生成默认补全源、pp_controller 复制源等场景使用。
    """
    version = ""
    try:
        from database import db
        admin = db.get_user("admin")
        if admin:
            version = admin.get("current_version") or ""
    except Exception:
        pass
    return resolve_versioned_install(ROS2_DEFAULT["host_ws"], version)["install_dir"]

def validate_user_path(requested_path: str, user_info: dict, target_user: str = None):
    """路径遍历保护：验证用户请求的路径是否在其工作目录下
    
    :param requested_path: 请求的路径
    :param user_info: 当前登录用户信息
    :param target_user: 管理员切换到目标用户操作时使用
    """
    # 管理员无target_user时全局操作，直接放行
    if user_info.get("role") == "admin" and not target_user:
        return True
    
    # 如果是管理员操作目标用户空间，先获取目标用户信息
    check_user = user_info
    if target_user and user_info.get("role") == "admin":
        from database import db
        target_user_obj = db.get_user(target_user) or db.get_user_by_id(target_user)
        if target_user_obj:
            check_user = target_user_obj
    
    user_root = check_user.get("home_folder_path")
    if not user_root:
        raise HTTPException(403, "用户工作目录未配置")
    
    # 管理员操作全局路径时（非用户空间内的默认路径），允许
    if user_info.get("role") == "admin" and user_root is None:
        return True
    
    # 展开 ~ 为实际家目录，避免 realpath 将 ~ 当作字面字符导致路径校验异常
    real_request_path = os.path.realpath(os.path.expanduser(requested_path))
    real_user_root = os.path.realpath(os.path.expanduser(user_root))
    
    if not real_request_path.startswith(real_user_root + os.sep) and real_request_path != real_user_root:
        logger.warning(f"路径校验失败: request={real_request_path}, user_root={real_user_root}, user={check_user.get('email')}, target_user={target_user}")
        raise HTTPException(403, "无权访问其他用户资源")
    
    return True

def get_user_workspace_paths(current_user: dict, target_user: str = None):
    """获取用户工作目录下的各子目录路径。

    :param current_user: 当前登录用户信息
    :param target_user: 管理员可指定查看的目标用户
    
    v5.0：install 目录版本化 —— 依据用户记录的 current_version 字段解析
    <工作空间>/<版本目录>/install，未选择版本时回退旧版 <工作空间>/install。
    返回值新增：current_version / version_dir / is_versioned / versions
    """
    # 管理员可指定查看其他用户的工作空间
    effective_user = current_user
    if target_user and current_user.get("role") == "admin":
        from database import db
        user = db.get_user(target_user) or db.get_user_by_id(target_user)
        if user:
            effective_user = user
    
    if effective_user.get("role") == "admin" and not target_user:
        # 管理员全局操作（未指定target_user）时使用全局默认路径（版本感知）
        home_ws = ROS2_DEFAULT["host_ws"]
        resolved = resolve_versioned_install(home_ws, effective_user.get("current_version") or "")
        install_dir = resolved["install_dir"]
        # 依据默认配置推导 launch/config 相对后缀，保持自定义配置兼容
        try:
            _launch_rel = os.path.relpath(ROS2_DEFAULT["launch_dir"], ROS2_DEFAULT["host_install"])
        except ValueError:
            _launch_rel = os.path.join("simulation_launches", "share", "simulation_launches", "launch")
        try:
            _config_rel = os.path.relpath(ROS2_DEFAULT["config_dir"], ROS2_DEFAULT["host_install"])
        except ValueError:
            _config_rel = os.path.join("simulation_launches", "share", "simulation_launches", "config")
        result = {
            "scripts_dir": ROS2_DEFAULT["scripts_dir"],
            "logs_dir": ROS2_DEFAULT["logs_dir"],
            "bag_storage": ROS2_DEFAULT["bag_storage"],
            "backup_dir": ROS2_DEFAULT["backup_dir"],
            "launch_dir": os.path.join(install_dir, _launch_rel),
            "host_ws": home_ws,
            "host_install": install_dir,
            "container_install": ROS2_DEFAULT["container_install"],
            "container_bag_path": ROS2_DEFAULT["container_bag_path"],
            "container_bag_path_alt": ROS2_DEFAULT["container_bag_path_alt"],
            "config_dir": os.path.join(install_dir, _config_rel),
            "bk_backups_dir": os.path.join(ROS2_DEFAULT["backup_dir"], ".bk_backups"),
            "target_user": target_user,
            # v5.0 版本信息
            "current_version": resolved["current_version"],
            "version_dir": resolved["version_dir"],
            "is_versioned": resolved["is_versioned"],
            "versions": list_user_versions(home_ws),
        }
        return result
    
    home_folder_path = effective_user.get("home_folder_path")
    if not home_folder_path:
        if effective_user.get("role") == "admin" and target_user:
            raise HTTPException(404, f"目标用户 {target_user} 的工作目录不存在")
        raise HTTPException(403, "用户工作目录未配置")
    
    # 展开 ~ 为实际家目录，确保后续路径拼接和校验正确
    home_folder_path = os.path.expanduser(home_folder_path)
    
    # ★★★ 用户隔离：所有用户（包括管理员操作其他用户空间时）使用该用户的隔离工作目录 ★★★
    # v5.0：版本感知解析 install 目录
    resolved = resolve_versioned_install(home_folder_path, effective_user.get("current_version") or "")
    user_install = resolved["install_dir"]
    return {
        "scripts_dir": os.path.join(home_folder_path, "Docker", "scripts"),
        "logs_dir": os.path.join(home_folder_path, "Docker", "logs"),
        "bag_storage": os.path.join(home_folder_path, "Docker", "bags"),
        "backup_dir": os.path.join(home_folder_path, "Docker", "bk"),
        "launch_dir": os.path.join(user_install, "simulation_launches", "share", "simulation_launches", "launch"),
        "host_ws": home_folder_path,
        "host_install": user_install,
        "container_install": ROS2_DEFAULT["container_install"],
        "container_bag_path": ROS2_DEFAULT["container_bag_path"],
        "container_bag_path_alt": ROS2_DEFAULT["container_bag_path_alt"],
        "config_dir": os.path.join(user_install, "simulation_launches", "share", "simulation_launches", "config"),
        "bk_backups_dir": os.path.join(home_folder_path, "Docker", "bk", ".bk_backups"),
        "target_user": target_user,
        # v5.0 版本信息
        "current_version": resolved["current_version"],
        "version_dir": resolved["version_dir"],
        "is_versioned": resolved["is_versioned"],
        "versions": list_user_versions(home_folder_path),
    }

def create_user_workspace(username: str) -> str:
    """创建用户工作目录和基础Docker运行环境

    使用 ``~/robotruck_ros2/Template`` 这个纯净模板复制到用户空间下并改名为 ``Docker``，
    避免直接复制管理员 ``Docker/bk``（其中含管理员生成的车辆 .py/.yaml 文件）造成污染。
    """
    base_path = os.path.expanduser("~/robotruck_ros2")
    user_home = os.path.join(base_path, username)
    docker_dir = os.path.join(user_home, "Docker")
    template_dir = os.path.expanduser("~/robotruck_ros2/Template")

    try:
        os.makedirs(user_home, exist_ok=True)

        if os.path.isdir(template_dir):
            # 从纯净 Template 复制并改名为 Docker（仅在不存在时初始化，避免覆盖已有用户数据）
            if not os.path.exists(docker_dir):
                shutil.copytree(template_dir, docker_dir)
                logger.info(f"已从纯净模板初始化 Docker 目录: {template_dir} -> {docker_dir}")
        else:
            # 兜底：Template 不存在时退回原有逻辑，仅创建空目录
            subdirs = ["bags", "bk", "logs", "scripts"]
            os.makedirs(docker_dir, exist_ok=True)
            for subdir in subdirs:
                os.makedirs(os.path.join(docker_dir, subdir), exist_ok=True)
            logger.warning(f"Template 目录不存在: {template_dir}，回退到空目录初始化")

        os.chmod(user_home, 0o755)
        if os.path.isdir(docker_dir):
            os.chmod(docker_dir, 0o755)

        try:
            subprocess.run(["chown", "-R", "fox:fox", user_home], capture_output=True)
        except Exception:
            pass

        logger.info(f"已创建用户工作目录: {user_home}")
        return user_home
    except Exception as e:
        logger.error(f"创建用户工作目录失败: {e}")
        raise HTTPException(500, f"创建用户工作目录失败: {e}")
