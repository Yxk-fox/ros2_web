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
    ADMIN_QUOTA = CONFIG.get("vehicle_limits", {}).get("admin_quota", 55)
    USER_QUOTA = CONFIG.get("vehicle_limits", {}).get("user_quota", 26)
    GLOBAL_MAX = CONFIG.get("vehicle_limits", {}).get("global_max", 300)
    BASE_VNC_PORT = CONFIG.get("vehicle_limits", {}).get("base_vnc_port", 5900)
    BASE_WEB_PORT = CONFIG.get("vehicle_limits", {}).get("base_web_port", 6080)

    # 不计入车辆配额的 launch 基名（核心仿真 launch，每个工作空间固定一个，
    # 独立于车辆脚本存在）。总数上限 16 个脚本位 = 15 辆车 + 1 个 simulation_launch。
    QUOTA_EXEMPT_BASES = {"simulation_launch"}

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
    # 脚本元信息解析（v5.1 多版本共存）
    # ================================================================

    @staticmethod
    def _parse_script_meta(fpath):
        """解析脚本内的标记行，返回 {"index": int|None, "version": str|None, "launch": str|None}

        - index: ``# VEHICLE_INDEX=N``（旧脚本退回 ROS_DOMAIN_ID / DISPLAY 反推）
        - version: ``# SCRIPT_VERSION=版本名``（无标记 = 旧版 install 脚本）
        - launch: ``# SCRIPT_LAUNCH=launch基名``（旧脚本退回按文件名解析）
        """
        meta = {}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return meta
        m = re.search(r"#\s*VEHICLE_INDEX\s*=\s*(\d+)", content)
        if m:
            meta["index"] = int(m.group(1))
        else:
            m = re.search(r"ROS_DOMAIN_ID\s*=\s*(\d+)", content)
            if m and 1 <= int(m.group(1)) <= ROS2ScriptGenerator.GLOBAL_MAX:
                meta["index"] = int(m.group(1)) - 1
            else:
                m = re.search(r"DISPLAY\s*=\s*:(\d+)", content)
                if m and 1 <= int(m.group(1)) <= ROS2ScriptGenerator.GLOBAL_MAX:
                    meta["index"] = int(m.group(1)) - 1
        m = re.search(r"#\s*SCRIPT_VERSION\s*=\s*(\S*)", content)
        if m:
            meta["version"] = m.group(1)
        m = re.search(r"#\s*SCRIPT_LAUNCH\s*=\s*(\S+)", content)
        if m:
            meta["launch"] = m.group(1)
        return meta

    @staticmethod
    def _version_tag(version):
        """版本名 → 文件名/容器名安全标签（保留字母数字和 . _ -）"""
        tag = re.sub(r'[^a-zA-Z0-9._-]', '_', version or '')
        return tag.strip('._-') or "legacy"

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
        此方法检测 5900-5922 / 6080-6104 范围内被占用的端口，
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
                    # VNC 端口范围 5900-5949
                    if cls.BASE_VNC_PORT <= host_port < cls.BASE_VNC_PORT + cls.GLOBAL_MAX:
                        used.add(host_port - cls.BASE_VNC_PORT)
                    # Web 端口范围 6080-6129
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
    def _count_scripts_in_dir(cls, scripts_dir, version=None):
        """统计目录中的启动脚本数量（排除模板、批量脚本和配额豁免的脚本）

        v5.1 多版本共存：version 参数控制统计口径
        - None: 统计全部版本脚本（全局配额用）
        - "": 仅统计旧版 install 脚本（无 SCRIPT_VERSION 标记）
        - "X": 仅统计 SCRIPT_VERSION=X 的脚本

        豁免脚本（如 simulation_launch）由 QUOTA_EXEMPT_BASES 中的 launch 生成，
        不占用车辆配额；豁免判定优先读脚本内 SCRIPT_LAUNCH 标记，旧脚本退回按文件名解析。
        """
        if not os.path.isdir(scripts_dir):
            return 0
        count = 0
        for fname in os.listdir(scripts_dir):
            if not (fname.startswith("start_docker_") and fname.endswith(".sh")):
                continue
            if fname == cls.TEMPLATE_NAME:
                continue
            fpath = os.path.join(scripts_dir, fname)
            meta = cls._parse_script_meta(fpath)
            launch = meta.get("launch")
            if not launch:
                # 旧脚本无标记：按文件名回退解析基名（去掉可能的版本后缀）
                base = fname[len("start_docker_ros2_"):-len(".sh")]
                launch = base.rsplit("__", 1)[0] if "__" in base else base
            if launch in cls.QUOTA_EXEMPT_BASES:
                continue
            if version is None or (meta.get("version") or "") == version:
                count += 1
        return count

    @classmethod
    def remove_version_scripts(cls, scripts_dir, version=""):
        """删除指定版本的启动脚本（v5.1：删版本时联动清理；version="" 表示旧版脚本）

        :return: 删除的脚本数量
        """
        if not os.path.isdir(scripts_dir):
            return 0
        removed = 0
        for fname in os.listdir(scripts_dir):
            if not (fname.startswith("start_docker_ros2_") and fname.endswith(".sh")):
                continue
            if fname == cls.TEMPLATE_NAME:
                continue
            fpath = os.path.join(scripts_dir, fname)
            if (cls._parse_script_meta(fpath).get("version") or "") == (version or ""):
                try:
                    os.remove(fpath)
                    removed += 1
                except OSError as e:
                    logger.warning(f"删除版本脚本失败: {fpath}: {e}")
        return removed

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
    def check_quota(cls, scripts_dir, user_role, new_count, version="", replaced_count=0):
        """检查配额，返回 (allowed: bool, message: str)

        v5.1：角色配额按当前版本计数（多版本共存时其他版本脚本不占本版本配额，
        但全局配额仍统计全部版本）。replaced_count 为本次生成将被替换掉的
        同版本脚本数（重新生成场景不重复计数）。
        """
        current_count = cls._count_scripts_in_dir(scripts_dir, version=version)
        effective_count = max(0, current_count - replaced_count)
        global_count = max(0, cls.get_global_script_count() - replaced_count)

        # 检查角色配额
        role_quota = cls.ADMIN_QUOTA if user_role == "admin" else cls.USER_QUOTA
        if effective_count + new_count > role_quota:
            role_name = "管理员" if user_role == "admin" else "普通用户"
            ver_label = f"版本 {version}" if version else "旧版 install"
            return False, f"[{role_name}] {ver_label} 当前已有 {effective_count} 辆车，新增 {new_count} 辆后将超出上限（最多 {role_quota} 辆），请删除部分脚本后再生成"

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

    @staticmethod
    def _natural_key(text):
        """自然排序 key：按数字段比较，使 fz_c5 < fz_c9 < fz_c50 < fz_c65"""
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split(r'(\d+)', text)]

    def get_launch_files(self):
        """获取 launch 文件列表（自然序；核心仿真 launch 不生成车辆脚本）"""
        launch_dir = self.cfg["launch_dir"]
        if not os.path.isdir(launch_dir):
            raise RuntimeError(f"ROS2 launch 目录不存在: {launch_dir}")
        files = []
        for f in os.listdir(launch_dir):
            if not f.endswith('.py'):
                continue
            base = f[:-3]
            if base in self.QUOTA_EXEMPT_BASES:
                continue
            safe_base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
            files.append((base, f, safe_base))
        files.sort(key=lambda lf: self._natural_key(lf[0]))
        if not files:
            raise RuntimeError(f"未在 {launch_dir} 中找到任何 .py launch 文件")
        return files

    def generate(self, port_conflicts=None, version=None, progress_cb=None):
        """主生成流程：扫描 launch 文件 → 配额检查 → 索引分配 → 生成脚本

        v5.1 多版本共存：
        - version: 目标 install 版本（None/"" 表示旧版 install 路径）
        - 仅清理当前版本的旧脚本，其他版本脚本原样保留（含旧版脚本）
        - progress_cb(percent, message): 异步联动任务进度回调（0~100）
        """
        def _report(pct, msg):
            if progress_cb:
                try:
                    progress_cb(pct, msg)
                except Exception:
                    pass

        _report(5, "扫描 launch 文件…")
        launch_files = self.get_launch_files()
        scripts_dir = self.cfg["scripts_dir"]
        os.makedirs(scripts_dir, exist_ok=True)
        os.makedirs(self.cfg["logs_dir"], exist_ok=True)
        os.makedirs(self.cfg["bag_storage"], exist_ok=True)

        # 配额检查（豁免的 launch 文件不计入新增数量；扣除将被替换的同版本脚本）
        _report(15, f"发现 {len(launch_files)} 个 launch 文件，检查配额…")
        billable = [lf for lf in launch_files if lf[0] not in self.QUOTA_EXEMPT_BASES]
        replaced = self._count_scripts_in_dir(scripts_dir, version=version or "")
        allowed, msg = self.check_quota(scripts_dir, self.user_role, len(billable),
                                        version=version or "", replaced_count=replaced)
        if not allowed:
            raise RuntimeError(msg)

        # v5.1：仅清理当前版本的旧脚本（其他版本脚本原样保留）
        _report(35, "清理当前版本旧脚本…")
        self.remove_version_scripts(scripts_dir, version or "")

        # 分配索引
        _report(45, "分配端口索引…")
        indices = self.allocate_indices(len(launch_files))
        if len(indices) < len(launch_files):
            raise RuntimeError(f"可用索引不足：需要 {len(launch_files)} 个，仅剩 {len(indices)} 个（全局上限 {self.GLOBAL_MAX} 个）")

        # 确保模板文件存在
        if not os.path.isfile(self.template_path):
            raise RuntimeError(f"模板文件不存在: {self.template_path}，请先创建模板文件")

        identifiers = []
        port_warnings = []

        for idx, (base, py_file, safe_base) in enumerate(launch_files):
            vehicle_index = indices[idx]
            self._write_start_script(base, py_file, safe_base, vehicle_index, version)
            identifiers.append(base)
            _report(50 + int(40 * (idx + 1) / len(launch_files)),
                    f"生成启动脚本（{idx + 1}/{len(launch_files)}）: {base}")

        _report(95, "生成批量启动/停止脚本…")
        self._write_batch_start(identifiers)
        self._write_batch_stop()
        _report(100, "脚本生成完成")
        return identifiers, port_warnings

    def _write_start_script(self, base, py_file, safe_base, vehicle_index, version=None):
        """基于模板生成单个启动脚本

        v5.1 多版本共存：
        - 脚本名带版本后缀: start_docker_ros2_{launch}__{版本标签}.sh（旧版 install 无后缀）
        - 容器名带版本段: ros2_{owner}_{版本标签}_{launch}（避免不同版本同名 launch 容器互杀）
        - 注入 SCRIPT_VERSION / SCRIPT_LAUNCH 标记行，供配额统计与版本清理识别
        """
        vtag = self._version_tag(version) if version else ""
        if version:
            script_path = os.path.join(self.cfg["scripts_dir"], f"start_docker_ros2_{safe_base}__{vtag}.sh")
        else:
            script_path = os.path.join(self.cfg["scripts_dir"], f"start_docker_ros2_{safe_base}.sh")
        # 容器名带 owner 段，避免不同用户同名 launch 产生同名容器互相顶替
        owner = self._owner_from_host_ws(self.cfg["host_ws"])
        if version:
            container_name = f"ros2_{owner}_{vtag}_{safe_base}"
        else:
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

        # v5.1：注入版本标记行（shebang 之后），供配额统计/版本清理/多版本识别
        markers = f"# SCRIPT_VERSION={version or ''}\n# SCRIPT_LAUNCH={base}\n"
        shebang = "#!/bin/bash\n"
        if content.startswith(shebang):
            content = shebang + markers + content[len(shebang):]
        else:
            content = markers + content

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