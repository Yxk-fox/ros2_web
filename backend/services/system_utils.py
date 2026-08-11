#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统工具服务
"""

import os
import re
import glob
import shutil
import subprocess

from logger import logger


class SystemUtils:
    """系统工具类，提供换源、安装包、证书切换、文件夹同步等操作"""
    @staticmethod
    def change_software_source(source_url):
        """切换 apt 软件源"""
        subprocess.run(["sudo", "cp", "/etc/apt/sources.list", "/etc/apt/sources.list.bak"])
        result = subprocess.run(["lsb_release", "-cs"], capture_output=True, text=True)
        codename = result.stdout.strip()
        new_content = f"""deb http://{source_url}/ubuntu/ {codename} main restricted universe multiverse
deb http://{source_url}/ubuntu/ {codename}-updates main restricted universe multiverse
deb http://{source_url}/ubuntu/ {codename}-backports main restricted universe multiverse
deb http://{source_url}/ubuntu/ {codename}-security main restricted universe multiverse
"""
        with tempfile.NamedTemporaryFile('w', delete=False) as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name
        subprocess.run(["sudo", "cp", tmp_path, "/etc/apt/sources.list"])
        os.unlink(tmp_path)
        subprocess.run(["sudo", "apt", "update"])
        return True, f"已切换至 {source_url} 源"

    @staticmethod
    def install_package(package):
        """安装 apt 软件包"""
        cmds = [["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", package]]
        logs = []
        for cmd in cmds:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            logs.append(proc.stdout + proc.stderr)
            if proc.returncode != 0:
                return False, "\n".join(logs)
        return True, "\n".join(logs)

    @staticmethod
    def uninstall_package(package):
        """卸载 apt 软件包"""
        proc = subprocess.run(["sudo", "apt", "remove", "-y", package], capture_output=True, text=True)
        return proc.returncode == 0, proc.stdout + proc.stderr

    @staticmethod
    def copy_certificates(src_dir, dst_dir):
        """复制证书目录

        跳过日志文件（.log / .params_log.log）等非证书文件，
        避免覆盖目标目录中由 root 创建的运行时日志导致 PermissionError。
        """
        if not os.path.isdir(src_dir):
            return False, f"源目录不存在: {src_dir}"
        os.makedirs(dst_dir, exist_ok=True)
        skipped = []
        for item in os.listdir(src_dir):
            # 跳过日志文件和隐藏的运行时文件
            if item.endswith('.log') or item.startswith('.'):
                skipped.append(item)
                continue
            src_item = os.path.join(src_dir, item)
            dst_item = os.path.join(dst_dir, item)
            try:
                if os.path.isdir(src_item):
                    if os.path.exists(dst_item):
                        shutil.rmtree(dst_item)
                    shutil.copytree(src_item, dst_item)
                else:
                    shutil.copy2(src_item, dst_item)
            except PermissionError as e:
                logger.warning(f"复制证书跳过无权限文件: {item} ({e})")
                skipped.append(item)
        msg = f"已切换证书: {src_dir} -> {dst_dir}"
        if skipped:
            msg += f"（跳过 {len(skipped)} 个文件: {', '.join(skipped)}）"
        return True, msg

    @staticmethod
    def sync_folder(src, dst):
        """同步文件夹（mock_truck/simulation_launches/control_launch）"""
        if not os.path.exists(src):
            return False, f"源路径不存在: {src}"
        os.makedirs(dst, exist_ok=True)
        
        def ignore_pycache(dir, files):
            return {'__pycache__', '.git', '.pyc', '.pyo', '.egg-info'}
        
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore_pycache)
        return True, f"同步成功: {src} -> {dst}"

    @staticmethod
    def sync_file(src, dst):
        """处理 sync_file 相关逻辑。同步单个文件"""
        if not os.path.isfile(src):
            return False, f"源文件不存在: {src}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True, f"同步成功: {src} -> {dst}"

    @staticmethod
    def clean_directory(dir_path, keep_patterns=None):
        """清空目录下所有文件和子目录

        v3.6 优化：支持 ``keep_patterns`` 参数，匹配上的文件名会被保留（不删除）。
        例如 ``keep_patterns=("*.pem",)`` 可在清空目录时保留证书文件。
        """
        if not os.path.isdir(dir_path):
            return False, f"目录不存在: {dir_path}"
        # 编译保留模式
        keep_matchers = []
        if keep_patterns:
            import fnmatch
            keep_matchers = [fnmatch.translate(p) for p in keep_patterns]
        for item in os.listdir(dir_path):
            # 命中保留模式则跳过
            if keep_matchers and any(re.match(m, item) for m in keep_matchers):
                continue
            item_path = os.path.join(dir_path, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        return True, f"已清空: {dir_path}"

    @staticmethod
    def switch_cloud_config(config_dir, new_ip):
        """切换云平台配置（修改 YAML 中的 IP 地址）"""
        yaml_files = glob.glob(os.path.join(config_dir, "*.yaml")) + glob.glob(os.path.join(config_dir, "*.yml"))
        modified = 0
        for yaml_path in yaml_files:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_lines = []
            in_guardian = False
            guardian_indent = None
            changed = False
            for line in lines:
                stripped = line.lstrip()
                if re.match(r'^guardian_cloud:\s*$', stripped):
                    in_guardian = True
                    guardian_indent = len(line) - len(stripped)
                    new_lines.append(line)
                    continue
                if in_guardian:
                    current_indent = len(line) - len(line.lstrip())
                    if stripped and current_indent <= guardian_indent:
                        in_guardian = False
                    else:
                        if 'udp_server_url:' in line:
                            new_line = re.sub(r'udp_server_url:\s*[\d\.]+', f'udp_server_url: {new_ip}', line)
                            if new_line != line:
                                changed = True
                            new_lines.append(new_line)
                            continue
                        if 'mqtt_url:' in line:
                            new_line = re.sub(r'mqtt_url:\s*[\d\.]+', f'mqtt_url: {new_ip}', line)
                            if new_line != line:
                                changed = True
                            new_lines.append(new_line)
                            continue
                        if 'server_url:' in line:
                            pattern = r"(server_url:\s*['\"])(https?://)[\d\.]+(:\d+/)?(['\"]?)"
                            replacement = rf"\g<1>https://{new_ip}:1443/\g<4>"
                            new_line = re.sub(pattern, replacement, line)
                            if new_line != line:
                                changed = True
                            new_lines.append(new_line)
                            continue
                new_lines.append(line)
            if changed:
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                modified += 1
        if modified > 0:
            return True, f"修改了 {modified} 个配置文件"
        # 未修改任何文件：可能 IP 已是目标地址（幂等操作视为成功）
        return True, f"配置文件无需修改（IP 可能已为 {new_ip}）"

    @staticmethod
    def get_cloud_ip_from_yaml(config_dir):
        """从 cloud.yaml 中解析当前的 udp_server_url IP 地址"""
        yaml_path = os.path.join(config_dir, "cloud.yaml")
        if not os.path.isfile(yaml_path):
            return None
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            m = re.search(r'udp_server_url:\s*([\d\.]+)', content)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

