#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker 容器管理服务
"""

import os
import subprocess

from logger import logger
from core.security import sanitize_command
from core.constants import DOCKER_PREFIX


class DockerManager:
    """Docker 容器管理类，封装容器/镜像的增删改查和命令执行"""
    @staticmethod
    def run_cmd(cmd, timeout=30):
        """执行系统命令并返回 (返回码, 标准输出, 标准错误)"""
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "命令超时"
        except Exception as e:
            return -1, "", str(e)

    @classmethod
    def list_containers(cls, running_only=True, filter_name=None, filter_image=None):
        """列出 Docker 容器（filter_name 支持前缀匹配与 ! 前缀排除）"""
        fmt = "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}"
        cmd = DOCKER_PREFIX.split() + ["docker", "ps"] + ([] if running_only else ["-a"]) + ["--format", fmt]
        rc, out, _ = cls.run_cmd(cmd)
        if rc != 0:
            return []
        containers = []
        for line in out.split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 4:
                name, status, image, created = parts[0], parts[1], parts[2], parts[3]
                if filter_name:
                    if filter_name.startswith('!'):
                        # ★★★ 修复：按名称排除（旧逻辑按镜像排除时，镜像为未打标签ID的
                        # ros2 容器会被错误归入"其他容器"）
                        if name.startswith(filter_name[1:]):
                            continue
                    elif not name.startswith(filter_name):
                        continue
                if filter_image:
                    if filter_image.startswith('!'):
                        exclude_image = filter_image[1:]
                        if exclude_image in image:
                            continue
                    else:
                        if filter_image not in image:
                            continue
                containers.append({"name": name, "status": status, "image": image, "created": created})
        return containers

    @classmethod
    def list_containers_detailed(cls, running_only=True, filter_name=None, filter_image=None):
        """单次 docker ps 批量获取容器详情（ID/名称/状态/镜像/创建时间/云IP label）

        ★★★ 性能优化：合并原先 list_containers + 单独的 ID/label 查询两次子进程调用为一次，
        避免每次容器列表刷新执行多个 docker 子进程。
        """
        fmt = "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}\t{{.Label \"ros2.cloud_ip\"}}"
        cmd = DOCKER_PREFIX.split() + ["docker", "ps"] + ([] if running_only else ["-a"]) + ["--format", fmt]
        rc, out, err = cls.run_cmd(cmd)
        if rc != 0:
            logger.warning(f"docker ps 批量获取容器详情失败: {err[:200]}")
            return []
        containers = []
        for line in out.split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) < 5:
                continue
            cid, name, status, image, created = parts[0], parts[1], parts[2], parts[3], parts[4]
            cloud_ip = parts[5] if len(parts) >= 6 and parts[5] and parts[5] != "<no value>" else ""
            if filter_name:
                if filter_name.startswith('!'):
                    if name.startswith(filter_name[1:]):
                        continue
                elif not name.startswith(filter_name):
                    continue
            if filter_image:
                if filter_image.startswith('!'):
                    if filter_image[1:] in image:
                        continue
                elif filter_image not in image:
                    continue
            containers.append({
                "id": cid[:12],
                "name": name,
                "status": status,
                "image": image,
                "created": created,
                "cloud_ip": cloud_ip,
            })
        return containers

    @classmethod
    def _docker(cls, *args):
        """构造 docker 命令前缀（含 sudo 判断）"""
        return DOCKER_PREFIX.split() + ["docker"] + list(args)

    @classmethod
    def stop_container(cls, name):
        """停止 Docker 容器"""
        return cls.run_cmd(cls._docker("kill", name))

    @classmethod
    def stop_all_ros2_containers(cls, container_names=None):
        """停止 ros2_ 前缀的运行中容器
        - container_names=None: 停止所有 ros2_ 前缀容器（管理员行为）
        - container_names=[...]: 仅停止指定名称的容器中仍在运行的（普通用户隔离）
        """
        if container_names is None:
            containers = cls.list_containers(running_only=True, filter_name="ros2_")
        else:
            # 普通用户：仅停止自己创建且仍在运行的 ros2_ 容器
            all_running = cls.list_containers(running_only=True, filter_name="ros2_")
            target_set = set(container_names)
            containers = [c for c in all_running if c["name"] in target_set]
        if not containers:
            return []

        # 并行停止所有容器 - 使用 docker kill 快速停止
        container_names = [c["name"] for c in containers]
        cmd = cls._docker("kill") + container_names
        rc, out, err = cls.run_cmd(cmd, timeout=30)

        results = []
        if rc == 0:
            # 全部成功
            for name in container_names:
                results.append((name, True, ""))
        else:
            # 部分失败，需要检查每个容器状态
            for name in container_names:
                rc_check, _, _ = cls.run_cmd(cls._docker("inspect", "-f", "{{.State.Running}}", name))
                is_running = rc_check == 0 and "true" in _
                results.append((name, not is_running, err if not is_running else ""))

        return results

    @classmethod
    def get_container_info(cls, name, format_str):
        """获取容器指定格式的信息"""
        cmd = cls._docker("inspect", "--format", format_str, name)
        rc, out, _ = cls.run_cmd(cmd)
        return out if rc == 0 else None

    @classmethod
    def update_resources(cls, name, cpus=None, memory_gb=None):
        """动态更新容器 CPU 和内存限制"""
        cmd = cls._docker("update")
        if cpus is not None:
            cmd.extend(["--cpus", str(cpus)])
        if memory_gb is not None:
            cmd.extend(["--memory", f"{memory_gb}g"])
        cmd.append(name)
        return cls.run_cmd(cmd)

    @classmethod
    def exec_command(cls, name, command, detach=False, timeout=15):
        """在容器内执行命令（支持后台模式，默认超时15秒）"""
        try:
            command = sanitize_command(command)
        except ValueError as e:
            return -1, "", str(e)
        if detach:
            cmd = cls._docker("exec", "-d", name, "bash", "-c", command)
        else:
            cmd = cls._docker("exec", name, "bash", "-c", command)
        return cls.run_cmd(cmd, timeout=timeout)

    @classmethod
    def list_images(cls):
        """列出 Docker 镜像"""
        rc, out, _ = cls.run_cmd(cls._docker("images", "--format", "{{.Repository}}:{{.Tag}}"))
        if rc != 0:
            return []
        return sorted(set([img for img in out.split() if img and not img.startswith('<none>')]))

    @classmethod
    def load_image(cls, tar_path):
        """加载 Docker 镜像"""
        if not os.path.isfile(tar_path):
            return -1, "", "文件不存在"
        if not tar_path.endswith('.tar') and not tar_path.endswith('.tgz'):
            return -1, "", "仅支持 .tar 或 .tgz 文件"
        size = os.path.getsize(tar_path)
        if size > 10 * 1024**3:
            return -1, "", "文件大小超过 10GB 限制"
        # 大镜像导入耗时较长（GB 级可能需要数分钟），超时放宽到 10 分钟，
        # 避免默认 30 秒超时导致导入被中断
        return cls.run_cmd(cls._docker("load", "-i", tar_path), timeout=600)

    @classmethod
    def remove_image(cls, image_name):
        """删除本地 Docker 镜像"""
        return cls.run_cmd(cls._docker("rmi", image_name))

