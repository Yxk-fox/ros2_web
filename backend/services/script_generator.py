#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS2 启动脚本生成器
基于模板 + 固定端口映射 + 索引管理 + 角色配额
"""

import os
import re
import glob
import subprocess

from logger import logger
from core.constants import CONFIG


class ROS2ScriptGenerator:
    """ROS2 启动脚本生成器，扫描 launch 文件并生成 Docker 启动脚本"""

    # 配额常量
    ADMIN_QUOTA = CONFIG.get("vehicle_limits", {}).get("admin_quota", 10)
    USER_QUOTA = CONFIG.get("vehicle_limits", {}).get("user_quota", 5)
    GLOBAL_MAX = CONFIG.get("vehicle_limits", {}).get("global_max", 25)
    BASE_VNC_PORT = CONFIG.get("vehicle_limits", {}).get("base_vnc_port", 5900)
    BASE_WEB_PORT = CONFIG.get("vehicle_limits", {}).get("base_web_port", 6080)

    # 模板文件名（存放在全局 bk 目录，避免被脚本清空逻辑误删）
    TEMPLATE_NAME = "start_docker_template.sh"

    def __init__(self, cfg, user_paths=None, user_role="user"):
        self.cfg = cfg
        self.user_paths = user_paths or {}
        self.user_role = user_role
        # 模板始终从管理员全局 bk 目录读取
        admin_bk = os.path.expanduser("~/robotruck_ros2/Docker/bk")
        self.template_path = os.path.join(admin_bk, self.TEMPLATE_NAME)

    # ================================================================
    # 索引管理
    # ================================================================

    @staticmethod
    def _extract_used_indices_from_dir(scripts_dir):
        """从指定目录的脚本中提取已使用的车辆索引

        兼容两种脚本格式：
        1. 新脚本：通过 ``# VEHICLE_INDEX=N`` 注释行标记索引
        2. 旧脚本：无标记行，从 ``ROS_DOMAIN_ID=N`` 反推索引（N-1），
           或从 ``DISPLAY=:N`` 反推索引（N-1）
        """
        used = set()
        if not os.path.isdir(scripts_dir):
            return used
        for fname in os.listdir(scripts_dir):
            if not fname.startswith("start_docker_") or not fname.endswith(".sh"):
                continue
            if fname == ROS2ScriptGenerator.TEMPLATE_NAME:
                continue
            fpath = os.path.join(scripts_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()

                # 优先：新脚本的 VEHICLE_INDEX 标记
                m = re.search(r"#\s*VEHICLE_INDEX\s*=\s*(\d+)", content)
                if m:
                    used.add(int(m.group(1)))
                    continue

                # 兼容旧脚本：从 ROS_DOMAIN_ID=N 反推索引 = N - 1
                m = re.search(r"ROS_DOMAIN_ID\s*=\s*(\d+)", content)
                if m:
                    domain_id = int(m.group(1))
                    if 1 <= domain_id <= ROS2ScriptGenerator.GLOBAL_MAX:
                        used.add(domain_id - 1)
                        continue

                # 兜底：从 DISPLAY=:N 反推索引 = N - 1
                m = re.search(r"DISPLAY\s*=\s*:(\d+)", content)
                if m:
                    display_num = int(m.group(1))
                    if 1 <= display_num <= ROS2ScriptGenerator.GLOBAL_MAX:
                        used.add(display_num - 1)
            except Exception:
                pass
        return used

    @classmethod
    def get_all_used_indices(cls, base_ws="~/robotruck_ros2"):
        """扫描所有工作空间，返回全局已使用的索引集合

        包含两个来源：
        1. 脚本文件中的索引标记（VEHICLE_INDEX / ROS_DOMAIN_ID / DISPLAY）
        2. 运行中 Docker 容器实际占用的端口反推的索引（兼容旧脚本动态端口）
        """
        base = os.path.expanduser(base_ws)
        used = set()

        # 管理员全局空间
        admin_scripts = os.path.join(base, "Docker", "scripts")
        used.update(cls._extract_used_indices_from_dir(admin_scripts))

        # 各用户空间
        if os.path.isdir(base):
            for entry in os.listdir(base):
                user_scripts = os.path.join(base, entry, "Docker", "scripts")
                if os.path.isdir(user_scripts):
                    used.update(cls._extract_used_indices_from_dir(user_scripts))

        # 检测运行中容器实际占用的端口，反推索引
        used.update(cls._get_indices_from_running_containers())

        # 检测宿主机进程实际占用的端口（如 TigerVNC、gnome-remote-desktop 等）
        # 这些端口不会被 Docker 容器扫描发现，但会导致 docker -p 绑定失败
        used.update(cls._get_indices_from_host_port_check())

        return used

    @classmethod
    def _get_indices_from_running_containers(cls):
        """扫描运行中 Docker 容器的端口映射，反推已占用的索引

        旧脚本使用动态端口（find_free_port），其运行时占用的端口
        与索引无关，可能导致新脚本按固定映射分配的端口与之冲突。
        此方法检测 5900-5924 / 6080-6104 范围内被占用的端口，
        反推索引并标记为已用。
        """
        used = set()
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return used
            for name in result.stdout.strip().split("\n"):
                if not name.startswith("ros2_"):
                    continue
                port_result = subprocess.run(
                    ["docker", "port", name],
                    capture_output=True, text=True, timeout=5
                )
                for line in port_result.stdout.split("\n"):
                    # 格式: 5901/tcp -> 0.0.0.0:5904
                    m = re.search(r"0\.0\.0\.0:(\d+)", line)
                    if not m:
                        continue
                    host_port = int(m.group(1))
                    # VNC 端口范围 5900-5924
                    if cls.BASE_VNC_PORT <= host_port < cls.BASE_VNC_PORT + cls.GLOBAL_MAX:
                        used.add(host_port - cls.BASE_VNC_PORT)
                    # Web 端口范围 6080-6104
                    if cls.BASE_WEB_PORT <= host_port < cls.BASE_WEB_PORT + cls.GLOBAL_MAX:
                        used.add(host_port - cls.BASE_WEB_PORT)
        except Exception:
            pass
        return used

    @classmethod
    def _get_indices_from_host_port_check(cls):
        """实测宿主机端口可用性，反推被宿主机进程占用的索引

        Docker 容器扫描只能发现 ``ros2_`` 前缀容器的端口映射，无法察觉
        宿主机本机进程（如 TigerVNC、gnome-remote-desktop）占用的端口。
        此方法对每个候选索引对应的 VNC/Web 端口执行 ``socket.bind`` 实测，
        与 ``docker run -p 0.0.0.0:port`` 的绑定行为一致，能准确识别冲突。

        被占用的端口对应的索引会被加入"已用"集合，分配器自动跳过。
        """
        used = set()
        import socket
        for idx in range(cls.GLOBAL_MAX):
            for base in (cls.BASE_VNC_PORT, cls.BASE_WEB_PORT):
                port = base + idx
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    # 与 docker -p 0.0.0.0:port 行为一致：绑定所有网卡
                    sock.bind(("0.0.0.0", port))
                except OSError:
                    # 端口被宿主机进程或 Docker 代理占用，标记索引为已用
                    used.add(idx)
                    break
                finally:
                    sock.close()
        return used

    @classmethod
    def allocate_indices(cls, count, base_ws="~/robotruck_ros2"):
        """分配 count 个最小可用索引，返回列表"""
        used = cls.get_all_used_indices(base_ws)
        allocated = []
        idx = 0
        while len(allocated) < count and idx < cls.GLOBAL_MAX:
            if idx not in used:
                allocated.append(idx)
                used.add(idx)
            idx += 1
        return allocated

    # ================================================================
    # 配额管理
    # ================================================================

    @classmethod
    def _count_scripts_in_dir(cls, scripts_dir):
        """统计目录中的启动脚本数量（排除模板和批量脚本）"""
        if not os.path.isdir(scripts_dir):
            return 0
        count = 0
        for fname in os.listdir(scripts_dir):
            if fname.startswith("start_docker_") and fname.endswith(".sh"):
                if fname == cls.TEMPLATE_NAME:
                    continue
                count += 1
        return count

    @classmethod
    def get_global_script_count(cls, base_ws="~/robotruck_ros2"):
        """统计全局所有工作空间的脚本总数"""
        base = os.path.expanduser(base_ws)
        total = 0
        admin_scripts = os.path.join(base, "Docker", "scripts")
        total += cls._count_scripts_in_dir(admin_scripts)
        if os.path.isdir(base):
            for entry in os.listdir(base):
                user_scripts = os.path.join(base, entry, "Docker", "scripts")
                if os.path.isdir(user_scripts):
                    total += cls._count_scripts_in_dir(user_scripts)
        return total

    @classmethod
    def check_quota(cls, scripts_dir, user_role, new_count):
        """检查配额，返回 (allowed: bool, message: str)"""
        current_count = cls._count_scripts_in_dir(scripts_dir)
        global_count = cls.get_global_script_count()

        # 检查角色配额
        role_quota = cls.ADMIN_QUOTA if user_role == "admin" else cls.USER_QUOTA
        if current_count + new_count > role_quota:
            role_name = "管理员" if user_role == "admin" else "普通用户"
            return False, f"[{role_name}] 当前已有 {current_count} 辆车，新增 {new_count} 辆后将超出上限（最多 {role_quota} 辆），请删除部分脚本后再生成"

        # 检查全局配额
        if global_count + new_count > cls.GLOBAL_MAX:
            return False, f"[全局] 当前已有 {global_count} 辆车，新增 {new_count} 辆后将超出全局上限 {cls.GLOBAL_MAX} 辆"

        return True, ""

    # ================================================================
    # 端口计算
    # ================================================================

    @classmethod
    def calc_ports(cls, index):
        """根据车辆索引计算固定端口"""
        return {
            "vnc_port": cls.BASE_VNC_PORT + index,
            "web_port": cls.BASE_WEB_PORT + index,
        }

    @staticmethod
    def _owner_from_host_ws(host_ws):
        """从宿主机工作空间路径推导容器名 owner 段

        admin 全局路径 (~/robotruck_ros2) 返回 'admin'，
        普通用户路径 (~/robotruck_ros2/ke_yunxiao) 返回末段 'ke_yunxiao'。
        用于容器名派生，保证不同用户同名 launch 不会产生同名容器。
        """
        base = os.path.basename(os.path.normpath(host_ws))
        if base == "robotruck_ros2":
            return "admin"
        # sanitize：仅保留字母数字下划线，避免容器名非法字符
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', base)
        return safe or "user"

    # ================================================================
    # 模板替换
    # ================================================================

    def _read_template(self):
        """读取模板文件内容"""
        if not os.path.isfile(self.template_path):
            raise RuntimeError(f"模板文件不存在: {self.template_path}")
        with open(self.template_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _replace_placeholders(template, replacements):
        """替换模板中的占位符"""
        result = template
        for key, value in replacements.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result

    # ================================================================
    # 主流程
    # ================================================================

    def get_launch_files(self):
        """获取 launch 文件列表"""
        launch_dir = self.cfg["launch_dir"]
        if not os.path.isdir(launch_dir):
            raise RuntimeError(f"ROS2 launch 目录不存在: {launch_dir}")
        files = []
        for f in os.listdir(launch_dir):
            if not f.endswith('.py'):
                continue
            base = f[:-3]
            safe_base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
            files.append((base, f, safe_base))
        if not files:
            raise RuntimeError(f"未在 {launch_dir} 中找到任何 .py launch 文件")
        return files

    def generate(self, port_conflicts=None):
        """主生成流程：扫描 launch 文件 → 配额检查 → 索引分配 → 生成脚本"""
        launch_files = self.get_launch_files()
        scripts_dir = self.cfg["scripts_dir"]
        os.makedirs(scripts_dir, exist_ok=True)
        os.makedirs(self.cfg["logs_dir"], exist_ok=True)
        os.makedirs(self.cfg["bag_storage"], exist_ok=True)

        # 配额检查
        allowed, msg = self.check_quota(scripts_dir, self.user_role, len(launch_files))
        if not allowed:
            raise RuntimeError(msg)

        # 清空旧脚本
        for f in os.listdir(scripts_dir):
            if f.startswith("start_docker_") and f.endswith(".sh"):
                if f == self.TEMPLATE_NAME:
                    continue
                os.remove(os.path.join(scripts_dir, f))

        # 分配索引
        indices = self.allocate_indices(len(launch_files))
        if len(indices) < len(launch_files):
            raise RuntimeError(f"可用索引不足：需要 {len(launch_files)} 个，仅剩 {len(indices)} 个（全局上限 {self.GLOBAL_MAX}）")

        # 确保模板文件存在
        if not os.path.isfile(self.template_path):
            raise RuntimeError(f"模板文件不存在: {self.template_path}，请先创建模板文件")

        identifiers = []
        port_warnings = []

        for idx, (base, py_file, safe_base) in enumerate(launch_files):
            vehicle_index = indices[idx]
            self._write_start_script(base, py_file, safe_base, vehicle_index)
            identifiers.append(base)

        self._write_batch_start(identifiers)
        self._write_batch_stop()
        return identifiers, port_warnings

    def _write_start_script(self, base, py_file, safe_base, vehicle_index):
        """基于模板生成单个启动脚本"""
        script_path = os.path.join(self.cfg["scripts_dir"], f"start_docker_ros2_{safe_base}.sh")
        # 容器名带 owner 段，避免不同用户同名 launch 产生同名容器互相顶替
        owner = self._owner_from_host_ws(self.cfg["host_ws"])
        container_name = f"ros2_{owner}_{safe_base}"

        ports = self.calc_ports(vehicle_index)
        display_num = vehicle_index + 1
        ros_domain_id = vehicle_index + 1

        host_install = self.cfg["host_install"]
        container_install = self.cfg["container_install"]
        logs_dir = self.cfg["logs_dir"]
        bag_storage = self.cfg["bag_storage"]
        container_bag_path = self.cfg.get("container_bag_path", "/home/nvidia/data/.boonray/bagfiles")
        container_bag_path_alt = self.cfg.get("container_bag_path_alt", "/home/boonray/.boonray/bagfiles")
        default_host_install = self.cfg.get("default_host_install", "")
        docker_image = self.cfg.get("docker_image", "ros2_humble_image:v1")

        replacements = {
            "VEHICLE_INDEX": vehicle_index,
            "VEHICLE_NAME": base,
            "CONTAINER_NAME": container_name,
            "LAUNCH_FILE": py_file,
            "DISPLAY_NUM": display_num,
            "ROS_DOMAIN_ID": ros_domain_id,
            "VNC_PORT": ports["vnc_port"],
            "WEB_PORT": ports["web_port"],
            "HOST_INSTALL": host_install,
            "CONTAINER_INSTALL": container_install,
            "HOST_LOGS_DIR": logs_dir,
            "HOST_BAGS_DIR": bag_storage,
            "CONTAINER_BAG_PATH": container_bag_path,
            "CONTAINER_BAG_PATH_ALT": container_bag_path_alt,
            "DEFAULT_HOST_INSTALL": default_host_install,
            "DOCKER_IMAGE": docker_image,
        }

        template = self._read_template()
        content = self._replace_placeholders(template, replacements)

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(content)
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

        return script_path

    # ================================================================
    # 批量启动 / 停止脚本
    # ================================================================

    def _write_batch_start(self, identifiers):
        """生成批量启动脚本"""
        path = os.path.join(self.cfg["scripts_dir"], "batch_start_ros2.sh")
        host_install = self.cfg["host_install"]
        content = f'''#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"; cd "$SCRIPT_DIR"
scripts=($(ls start_docker_ros2_*.sh 2>/dev/null | sed 's/start_docker_ros2_\\(.*\\)\\.sh/\\1/'))
if [ ! -d "{host_install}" ]; then echo "❌ 挂载目录缺失: {host_install}，请先上传安装包"; exit 1; fi
echo "将启动 ${{#scripts[@]}} 辆ROS2车: ${{scripts[@]}}"
read -p "继续? (y/N) " c; [[ ! "$c" =~ [Yy] ]] && exit 0
s=0; f=0
for id in ${{scripts[@]}}; do
    echo "🚀 启动: $id"
    ./start_docker_ros2_$id.sh && ((s++)) || ((f++))
    sleep 2
done
echo "✅成功:$s ❌失败:$f"
'''
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, os.stat(path).st_mode | 0o111)

    def _write_batch_stop(self):
        """生成批量停止脚本"""
        path = os.path.join(self.cfg["scripts_dir"], "batch_stop_ros2.sh")
        content = '''#!/bin/bash
containers=$(docker ps -a --format "{{.Names}}" | grep -E '^ros2_' | sort -V)
[ -z "$containers" ] && { echo "无ROS2容器"; exit 0; }
echo "$containers" | while read name; do
    docker stop -t 10 "$name" >/dev/null 2>&1 && echo "✅ $name" || { docker kill "$name" >/dev/null 2>&1 && echo "⚠️ $name (强制终止)"; }
done
'''
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, os.stat(path).st_mode | 0o111)