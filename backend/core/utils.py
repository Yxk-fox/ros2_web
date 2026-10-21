#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具函数模块
"""

import os
import re
import json
import glob
import shutil
import socket
import subprocess
import time
import zipfile
import tarfile
import tempfile
from typing import List, Optional, Dict, Any
from pathlib import Path

import psutil
import docker

from logger import logger
from core.constants import (
    ROS2_DEFAULT, INSTALL_DIR, SETUP_BASH, LAUNCH_DIR, DOCKER_PREFIX,
    WHITELIST_FILE, DEFAULT_WHITELIST, CONFIG, ROS2_WS
)

def expand_path(path: str) -> str:
    """展开路径中的 ~ 和环境变量"""
    return os.path.expanduser(path)

def generate_username_from_email(email: str) -> str:
    """从邮箱地址提取用户名（@ 之前的部分，点号替换为下划线）"""
    name = email.split('@')[0] if '@' in email else email
    return name.replace('.', '_')

def extract_numbers(name: str) -> str:
    """从字符串末尾提取数字"""
    match = re.search(r'\d+$', name)
    return match.group() if match else name

def extract_letters_and_numbers(name: str):
    """从标识中提取字母和数字部分。
    支持两种格式：
    - 标识格式: hytz3788 -> ('hytz', '3788')
    - SN格式: hytz_3788 -> ('hytz', '3788')
    """
    # 先检查是否为 SN 格式（包含下划线）
    if '_' in name:
        parts = name.split('_', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    # 否则尝试标识格式
    match = re.fullmatch(r'([A-Za-z]+)(\d+)', name)
    if match:
        return match.groups()
    return name, ""

def generate_files(root_dir: str, user_input: str, log_callback, sim_dir: str = None, mock_dir: str = None):
    """根据 SN 标识生成 ROS2 配置文件

    命名规则（SN 直接作为文件名后缀，不再提取数字部分）：
      - launch: {SN}.py
      - cloud:  cloud_{SN}.yaml
      - device: device_{SN}.yaml (复制 device.yaml)
      - project: project_{SN}.yaml (复制 project.yaml)
      - truck:  truck{SN}.yaml (注意: truck 与 SN 之间无下划线)
      - mock_truck yaml: mock_truck_{SN}.yaml
      - mock_truck launch: mock_truck_{SN}.py

    同时更新 simulation_launch.py 中的 KEY_* 常量，
    以及 mock_truck_launch.py 中的 default_config_name。
    cloud.yaml 中 device_sn 字段会被设置为 SN 本身。
    """
    log_callback("开始生成配置文件...\n")
    sn = user_input.strip()
    if not sn:
        log_callback("错误: SN 为空\n")
        return
    # device_sn 直接使用 SN（用户输入即为 SN，如 mhw_299）
    device_sn = sn
    log_callback(f"生成的 device_sn: {device_sn}\n")
    # 支持自定义 sim_dir 和 mock_dir，默认从 root_dir 构造（兼容旧逻辑）
    if sim_dir is None:
        sim_dir = os.path.join(root_dir, "simulation_launches")
    if mock_dir is None:
        mock_dir = os.path.join(root_dir, "mock_truck")
    sim_launch_dir = os.path.join(sim_dir, "launch")
    sim_config_dir = os.path.join(sim_dir, "config")
    mock_config_dir = os.path.join(mock_dir, "config")
    mock_launch_dir = os.path.join(mock_dir, "launch")
    sim_launch_template = os.path.join(sim_launch_dir, "simulation_launch.py")
    cloud_template = os.path.join(sim_config_dir, "cloud.yaml")
    device_template = os.path.join(sim_config_dir, "device.yaml")
    project_template = os.path.join(sim_config_dir, "project.yaml")
    truck_template = os.path.join(sim_config_dir, "truck.yaml")
    mock_yaml_template = os.path.join(mock_config_dir, "mock_truck.yaml")
    mock_launch_template = os.path.join(mock_launch_dir, "mock_truck_launch.py")
    sim_launch_target = os.path.join(sim_launch_dir, f"{sn}.py")
    cloud_target = os.path.join(sim_config_dir, f"cloud_{sn}.yaml")
    device_target = os.path.join(sim_config_dir, f"device_{sn}.yaml")
    project_target = os.path.join(sim_config_dir, f"project_{sn}.yaml")
    truck_target = os.path.join(sim_config_dir, f"truck{sn}.yaml")
    mock_yaml_target = os.path.join(mock_config_dir, f"mock_truck_{sn}.yaml")
    mock_launch_target = os.path.join(mock_launch_dir, f"mock_truck_{sn}.py")
    missing = []
    for name, path in [("simulation_launch.py", sim_launch_template),
                       ("cloud.yaml", cloud_template),
                       ("device.yaml", device_template),
                       ("project.yaml", project_template),
                       ("truck.yaml", truck_template),
                       ("mock_truck.yaml", mock_yaml_template),
                       ("mock_truck_launch.py", mock_launch_template)]:
        if not os.path.isfile(path):
            missing.append(f"{name} 不存在: {path}")
    if missing:
        log_callback("错误：缺少以下模板文件：\n" + "\n".join(missing) + "\n")
        return False
    # 1. 生成 simulation_launch_{SN}.py 并替换 KEY_* 常量
    try:
        with open(sim_launch_template, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = re.sub(r"(KEY_CLOUD_CONF\s*=\s*)'cloud\.yaml'", rf"\1'cloud_{sn}.yaml'", content)
        new_content = re.sub(r"(KEY_DEVICE_CONF\s*=\s*)'device\.yaml'", rf"\1'device_{sn}.yaml'", new_content)
        new_content = re.sub(r"(KEY_MINING_AREA_CONF\s*=\s*)'project\.yaml'", rf"\1'project_{sn}.yaml'", new_content)
        new_content = re.sub(r"(KEY_TRUCK_CONF\s*=\s*)'truck\.yaml'", rf"\1'truck{sn}.yaml'", new_content)
        with open(sim_launch_target, "w", encoding="utf-8") as f:
            f.write(new_content)
        log_callback(f"✓ 生成 {sim_launch_target}\n")
    except Exception as e:
        log_callback(f"✗ 生成 simulation_launch.py 失败: {e}\n")
    # 2. 生成 cloud_{SN}.yaml，替换 device_sn
    try:
        with open(cloud_template, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if re.match(r'^\s*device_sn:', line):
                indent = re.match(r'^(\s*)', line).group(1)
                new_lines.append(f"{indent}device_sn: '{device_sn}'\n")
            else:
                new_lines.append(line)
        with open(cloud_target, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        log_callback(f"✓ 生成 {cloud_target}\n")
    except Exception as e:
        log_callback(f"✗ 生成 cloud.yaml 失败: {e}\n")
    # 3. 复制 device.yaml -> device_{SN}.yaml
    try:
        shutil.copy2(device_template, device_target)
        log_callback(f"✓ 复制device.yaml生成 {device_target}\n")
    except Exception as e:
        log_callback(f"✗ 复制 device.yaml 失败: {e}\n")
    # 4. 复制 project.yaml -> project_{SN}.yaml
    try:
        shutil.copy2(project_template, project_target)
        log_callback(f"✓ 复制project.yaml生成 {project_target}\n")
    except Exception as e:
        log_callback(f"✗ 复制 project.yaml 失败: {e}\n")
    # 5. 复制 truck.yaml -> truck{SN}.yaml (注意: truck 与 SN 之间无下划线)
    try:
        shutil.copy2(truck_template, truck_target)
        log_callback(f"✓ 复制truck.yaml生成 {truck_target}\n")
    except Exception as e:
        log_callback(f"✗ 复制 truck.yaml 失败: {e}\n")
    # 6. 复制 mock_truck.yaml -> mock_truck_{SN}.yaml
    try:
        shutil.copy2(mock_yaml_template, mock_yaml_target)
        log_callback(f"✓ 复制mock_truck.yaml生成 {mock_yaml_target}\n")
    except Exception as e:
        log_callback(f"✗ 复制 mock_truck.yaml 失败: {e}\n")
    # 7. 生成 mock_truck_{SN}.py，替换 default_config_name
    try:
        with open(mock_launch_template, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = re.sub(r"(default_config_name\s*=\s*)'mock_truck\.yaml'", rf"\1'mock_truck_{sn}.yaml'", content)
        with open(mock_launch_target, "w", encoding="utf-8") as f:
            f.write(new_content)
        log_callback(f"✓ 生成 {mock_launch_target}\n")
    except Exception as e:
        log_callback(f"✗ 生成 mock_truck_launch.py 失败: {e}\n")
    log_callback("\n生成完成！\n")
    return True

def run_ros2_cmd(cmd: List[str], timeout: int = 10) -> tuple:
    """在宿主机上执行 ROS2 命令

    v5.0：宿主机环境跟随管理员当前选择的版本（版本感知的 setup.bash）
    """
    env = os.environ.copy()
    setup_bash = SETUP_BASH
    try:
        # 优先使用管理员当前生效版本的 setup.bash；解析失败时回退默认配置
        from core.workspace import get_admin_install_dir
        active_setup = os.path.join(get_admin_install_dir(), "setup.bash")
        if os.path.isfile(active_setup):
            setup_bash = active_setup
    except Exception:
        pass
    if os.path.exists(setup_bash):
        full_cmd = f"source {setup_bash} && " + " ".join(cmd)
        shell_cmd = ["bash", "-c", full_cmd]
    else:
        shell_cmd = cmd
    try:
        proc = subprocess.run(shell_cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)

def run_ros2_cmd_in_container(container_id: str, cmd: List[str], timeout: int = 15) -> tuple:
    """在指定容器内执行 ROS2 命令"""
    from services.docker_manager import DockerManager
    container_install = ROS2_DEFAULT["container_install"]
    source_cmd = f"source {container_install}/setup.bash && " + " ".join(cmd)
    full_cmd = f"bash -c '{source_cmd}'"
    return DockerManager.exec_command(container_id, full_cmd, timeout=timeout)

def load_whitelist():
    """加载容器名称白名单前缀"""
    try:
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, 'r') as f:
                data = json.load(f)
                prefixes = data.get("prefixes", DEFAULT_WHITELIST)
                return prefixes if isinstance(prefixes, list) else DEFAULT_WHITELIST
    except:
        pass
    return DEFAULT_WHITELIST

def parse_size(size_str):
    """解析 Docker 镜像大小字符串为字节数"""
    if not size_str:
        return 0
    size_str = size_str.strip().upper()
    match = re.match(r'([\d.]+)\s*([KMGT]?B?)', size_str)
    if not match:
        return 0
    num = float(match.group(1))
    unit = match.group(2)
    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    if unit.startswith('K'): unit = 'KB'
    elif unit.startswith('M'): unit = 'MB'
    elif unit.startswith('G'): unit = 'GB'
    elif unit.startswith('T'): unit = 'TB'
    else: unit = 'B'
    return int(num * multipliers.get(unit, 1))


def error_response(status_code: int, message: str):
    """统一错误响应格式"""
    from fastapi import HTTPException
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


async def broadcast_log(log_type: str, data: str):
    """向所有 WebSocket 客户端广播日志消息"""
    import json
    import time
    from core.constants import ws_clients
    msg = json.dumps({"type": "log", "log_type": log_type, "data": data, "timestamp": time.time()})
    for client in ws_clients[:]:
        try:
            await client.send_text(msg)
        except:
            if client in ws_clients:
                ws_clients.remove(client)


def get_used_ports():
    """获取当前宿主机已占用的 TCP 端口集合（set）"""
    used = set()
    for conn in psutil.net_connections(kind='inet'):
        if conn.laddr:
            used.add(conn.laddr.port)
    return used


def find_free_port(start_port: int = 8875, used_ports=None, step: int = 1):
    """从 start_port 开始查找第一个可用端口
    
    Args:
        start_port: 起始端口号
        used_ports: 已占用端口列表（可选，用于避免与已知端口冲突）
        step: 端口递增步长
    """
    used_set = set(used_ports) if used_ports else set()
    port = start_port
    while port < 65535:
        if port not in used_set:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(('0.0.0.0', port))
                sock.close()
                return port
            except OSError:
                port += step
            finally:
                sock.close()
        else:
            port += step
    return None


def build_dir_tree(path: str, max_depth: int = 2):
    """构建目录树结构用于前端展示"""
    if not os.path.isdir(path):
        return None

    def _build(current_path: str, current_depth: int):
        if current_depth > max_depth:
            return {"name": os.path.basename(current_path), "path": current_path, "type": "directory", "children": []}
        result = {"name": os.path.basename(current_path) or current_path, "path": current_path, "type": "directory", "children": []}
        try:
            entries = sorted(os.listdir(current_path))
        except PermissionError:
            return result
        for entry in entries:
            entry_path = os.path.join(current_path, entry)
            if os.path.isdir(entry_path):
                child = _build(entry_path, current_depth + 1)
                result["children"].append(child)
            else:
                result["children"].append({"name": entry, "path": entry_path, "type": "file"})
        return result

    return _build(path, 1)


def extract_and_flatten(tmp_path: str, host_install: str):
    """解压压缩包并扁平化：若压缩包内仅有一个顶层目录，则提取该目录内容"""
    os.makedirs(host_install, exist_ok=True)

    if zipfile.is_zipfile(tmp_path):
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            members = zf.namelist()
            top_dirs = set()
            for m in members:
                parts = m.split('/')
                if parts[0]:
                    top_dirs.add(parts[0])
            if len(top_dirs) == 1 and any(m.endswith('/') and m.count('/') == 1 for m in members):
                # 单一顶层目录 → 扁平化
                top = list(top_dirs)[0]
                with tempfile.TemporaryDirectory() as tmpdir:
                    zf.extractall(tmpdir)
                    src_dir = os.path.join(tmpdir, top)
                    for item in os.listdir(src_dir):
                        s = os.path.join(src_dir, item)
                        d = os.path.join(host_install, item)
                        if os.path.isdir(s):
                            shutil.copytree(s, d, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s, d)
            else:
                zf.extractall(host_install)
    elif tarfile.is_tarfile(tmp_path):
        with tarfile.open(tmp_path, 'r') as tf:
            members = tf.getnames()
            top_dirs = set()
            for m in members:
                parts = m.split('/')
                if parts[0]:
                    top_dirs.add(parts[0])
            if len(top_dirs) == 1 and any(m.endswith('/') and m.count('/') == 1 for m in members):
                top = list(top_dirs)[0]
                with tempfile.TemporaryDirectory() as tmpdir:
                    tf.extractall(tmpdir)
                    src_dir = os.path.join(tmpdir, top)
                    for item in os.listdir(src_dir):
                        s = os.path.join(src_dir, item)
                        d = os.path.join(host_install, item)
                        if os.path.isdir(s):
                            shutil.copytree(s, d, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s, d)
            else:
                tf.extractall(host_install)
    else:
        raise ValueError("不支持的压缩包格式，仅支持 zip / tar / tar.gz")


def extract_versioned_install(tmp_path: str, host_ws: str, fallback_version: str) -> str:
    """v5.0 版本化解压：将压缩包解压为 <host_ws>/<版本名>/install/ 目录结构

    版本名来源（按优先级）：
    1. 压缩包顶层唯一目录且其内包含 install/ → 顶层目录名（如 test_install20260904_x86_ros2_5.0）
    2. 顶层唯一目录且其内直接为 install 内容（含 setup.bash）→ 压缩包文件名
    3. 顶层直接为 install/ → 压缩包文件名
    4. 顶层直接为 install 内容（含 setup.bash）→ 压缩包文件名，自动包一层 install/

    同名版本已存在时，旧目录备份为 <host_ws>/<版本名>.replaced.<时间戳>（最多保留2个）

    :return: 实际生效的版本名
    :raises ValueError: 压缩包内无法识别 install 结构
    """
    from core.workspace import sanitize_version_name, is_valid_version_name, VERSION_RESERVED_NAMES

    # 先完整解压到临时目录，识别结构后再落位
    with tempfile.TemporaryDirectory(prefix="vinstall_") as extract_dir:
        if zipfile.is_zipfile(tmp_path):
            with zipfile.ZipFile(tmp_path, 'r') as zf:
                zf.extractall(extract_dir)
        elif tarfile.is_tarfile(tmp_path):
            with tarfile.open(tmp_path, 'r') as tf:
                tf.extractall(extract_dir)
        else:
            raise ValueError("不支持的压缩包格式，仅支持 zip / tar / tar.gz")

        top_entries = [e for e in os.listdir(extract_dir) if not e.startswith('.')]
        if not top_entries:
            raise ValueError("压缩包为空")

        src_install = None          # 指向 install 目录本身
        wrap_src = False            # True 表示 src_install 为 install 内容需包裹
        version_name = None

        def _looks_like_install(d: str) -> bool:
            return os.path.isfile(os.path.join(d, "setup.bash"))

        if len(top_entries) == 1 and os.path.isdir(os.path.join(extract_dir, top_entries[0])):
            top = top_entries[0]
            top_dir = os.path.join(extract_dir, top)
            inner_install = os.path.join(top_dir, "install")
            if os.path.isdir(inner_install):
                # 结构：X/install/... → 版本名 = X
                version_name = top
                src_install = inner_install
            elif _looks_like_install(top_dir):
                # 结构：X/setup.bash（X 即 install 内容）→ 版本名 = 压缩包文件名
                version_name = fallback_version
                src_install = top_dir
                wrap_src = True
            else:
                raise ValueError(f"压缩包顶层目录 {top} 内未找到 install 目录或 setup.bash，无法识别安装结构")
        elif "install" in top_entries and os.path.isdir(os.path.join(extract_dir, "install")):
            # 结构：install/... → 版本名 = 压缩包文件名
            version_name = fallback_version
            src_install = os.path.join(extract_dir, "install")
        elif _looks_like_install(extract_dir):
            # 结构：setup.bash 直接位于顶层 → 版本名 = 压缩包文件名，包一层 install/
            version_name = fallback_version
            src_install = extract_dir
            wrap_src = True
        else:
            raise ValueError("压缩包内未找到 install 目录或 setup.bash，无法识别安装结构")

        version_name = sanitize_version_name(version_name)
        if not version_name:
            version_name = sanitize_version_name(fallback_version) or "install_version"
        if not is_valid_version_name(version_name) or version_name in VERSION_RESERVED_NAMES:
            raise ValueError(f"无效的版本目录名: {version_name}")

        version_dir = os.path.join(os.path.expanduser(host_ws), version_name)
        dest_install = os.path.join(version_dir, "install")

        # 同名版本已存在 → 备份旧版本目录（保留最近2个 .replaced.*）
        if os.path.exists(version_dir):
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = f"{version_dir}.replaced.{ts}"
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            shutil.move(version_dir, backup_dir)
            _prune_backups(f"{version_name}.replaced.", os.path.dirname(backup_dir), keep=2)

        os.makedirs(version_dir, exist_ok=True)
        if wrap_src:
            shutil.copytree(src_install, dest_install)
        else:
            shutil.move(src_install, dest_install)

        # 校验 setup.bash 是否存在
        if not os.path.isfile(os.path.join(dest_install, "setup.bash")):
            raise ValueError("解压后的 install 目录中缺少 setup.bash，请确认压缩包内容")

        return version_name


def _prune_backups(prefix: str, parent_dir: str, keep: int = 2):
    """清理指定前缀的备份目录，仅保留最近 keep 个"""
    try:
        backups = sorted(
            [e for e in os.listdir(parent_dir) if e.startswith(prefix)],
            reverse=True,
        )
        for old in backups[keep:]:
            old_path = os.path.join(parent_dir, old)
            if os.path.isdir(old_path):
                shutil.rmtree(old_path, ignore_errors=True)
    except Exception:
        pass


def _safe_copy2(src: str, dst: str):
    """安全复制：先尝试 unlink 目标文件再复制，避免 ETXTBSY (Errno 26) 错误"""
    if os.path.exists(dst):
        try:
            os.unlink(dst)
        except OSError:
            pass
    shutil.copy2(src, dst)


def _normalize_rviz_config(config_path: str):
    """规范化 RVIZ 配置文件路径"""
    if not config_path or not os.path.isfile(config_path):
        return None
    return os.path.abspath(config_path)


def _resolve_rviz_config(container_id: str, container_user: str):
    """在容器中查找 simu.rviz 配置文件路径"""
    from services.docker_manager import DockerManager
    # 查找容器内 install 目录下的 simu.rviz
    rc, out, _ = DockerManager.run_cmd(DockerManager._docker(
        "exec", "-u", container_user, container_id, "bash", "-c",
        "find /home/boonray/install -name 'simu.rviz' -type f 2>/dev/null | head -1"
    ))
    if rc == 0 and out.strip():
        return out.strip()
    # 回退到项目 data 目录
    data_rviz = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "simu.rviz")
    if os.path.isfile(data_rviz):
        return data_rviz
    return None


def _maximize_rviz(container_id: str, container_user: str, display_num: str, wait_seconds: int = 8):
    """在容器中最大化 RVIZ 窗口"""
    import time
    from services.docker_manager import DockerManager
    time.sleep(wait_seconds)
    DockerManager.run_cmd(DockerManager._docker(
        "exec", "-u", container_user, "-e", f"DISPLAY={display_num}", container_id,
        "bash", "-c", "wmctrl -r 'RViz' -b add,maximized_vert,maximized_horz 2>/dev/null || true"
    ))

