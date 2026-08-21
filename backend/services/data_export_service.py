#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出服务模块
@File    :  data_export_service.py
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  hdmap 提取 + ros2 bag 录制业务逻辑，仅依赖 core/services/database 层
            遵循 README「解耦开发规范」第 1 条：业务逻辑放 services/
"""

import os
import re
import time
import threading
from datetime import datetime

from logger import logger
from services.docker_manager import DockerManager
from core.workspace import get_user_workspace_paths


_bag_sessions: dict = {}
_bag_sessions_lock = threading.Lock()


class DataExportService:
    """数据导出服务：hdmap 提取 + ros2 bag 录制"""

    BAG_RECORD_CMD = "source /home/boonray/install/setup.bash && cd /home/boonray && nohup ros2 bag record -s mcap --all > /tmp/bag_record.log 2>&1 &"
    HDMAP_BASE = "/home/boonray/resource_data"
    CONTAINER_BAG_PATH = "/home/boonray"

    @classmethod
    def _get_bag_storage(cls, current_user: dict, target_user: str = None) -> str:
        paths = get_user_workspace_paths(current_user, target_user=target_user)
        bag_storage = paths["bag_storage"]
        os.makedirs(bag_storage, exist_ok=True)
        return bag_storage

    @classmethod
    def _sanitize_sn(cls, sn: str) -> str:
        sn = re.sub(r'[^a-zA-Z0-9_\-]', '', sn)
        if not sn:
            raise ValueError("SN 不合法")
        return sn

    @classmethod
    def _ensure_ros2_container(cls, container_name: str) -> None:
        containers = DockerManager.list_containers(running_only=True, filter_name=container_name)
        found = [c for c in containers if c["name"] == container_name]
        if not found:
            all_containers = DockerManager.list_containers(running_only=False, filter_name=container_name)
            if any(c["name"] == container_name for c in all_containers):
                raise ValueError(f"容器 '{container_name}' 存在但未运行，请先启动容器")
            raise ValueError(f"容器 '{container_name}' 不存在")

        image = found[0].get("image", "")
        if "ros2" not in image.lower() and "humble" not in image.lower() and "foxy" not in image.lower():
            raise ValueError(f"容器 '{container_name}' 不是 ROS2 容器")

    @classmethod
    def extract_hdmap(cls, container_name: str, sn: str,
                      current_user: dict, target_user: str = None) -> dict:
        logger.info(f"开始提取地图: container={container_name}, sn={sn}, user={current_user.get('username')}")

        cls._ensure_ros2_container(container_name)
        sn = cls._sanitize_sn(sn)

        bag_storage = cls._get_bag_storage(current_user, target_user)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tar_name = f"hdmap_{sn}_{timestamp}.tar.gz"
        host_tar_path = os.path.join(bag_storage, tar_name)

        container_hdmap_dir = f"{cls.HDMAP_BASE}/{sn}/hdmap"
        container_tar_path = f"/tmp/{tar_name}"

        cmd_parts = [
            "cd", container_hdmap_dir,
            "&&", "tar", "-czf", container_tar_path, "--", "./*.pb.bin"
        ]
        exec_cmd = " ".join(cmd_parts)

        logger.debug(f"容器内打包命令: {exec_cmd}")
        rc, out, err = DockerManager.exec_command(container_name, exec_cmd, timeout=120)
        if rc != 0:
            logger.error(f"容器内打包失败: rc={rc}, out={out}, err={err}")
            raise RuntimeError(f"容器内打包失败: {err or out or '未知错误'}")

        logger.info(f"容器内打包成功，开始拷贝到宿主机: {container_tar_path} -> {host_tar_path}")
        copy_cmd = DockerManager._docker("cp", f"{container_name}:{container_tar_path}", host_tar_path)
        rc, out, err = DockerManager.run_cmd(copy_cmd, timeout=60)
        if rc != 0:
            logger.error(f"拷贝失败: rc={rc}, err={err}")
            raise RuntimeError(f"拷贝到宿主机失败: {err or out or '未知错误'}")

        try:
            DockerManager.exec_command(container_name, f"rm -f {container_tar_path}", timeout=10)
        except Exception:
            pass

        file_size = os.path.getsize(host_tar_path) if os.path.isfile(host_tar_path) else 0
        logger.info(f"地图提取完成: {host_tar_path}, size={file_size}")

        return {
            "success": True,
            "message": "地图提取成功",
            "file_path": host_tar_path,
            "file_name": tar_name,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2),
        }

    @classmethod
    def _list_sn_dirs(cls, container_name: str) -> list:
        cls._ensure_ros2_container(container_name)
        cmd = f"ls -d {cls.HDMAP_BASE}/*/hdmap 2>/dev/null || echo ''"
        rc, out, err = DockerManager.exec_command(container_name, cmd, timeout=15)
        if rc != 0 or not out.strip():
            return []
        dirs = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if line:
                sn_name = line.rstrip("/").split("/")[-2]
                dirs.append(sn_name)
        return sorted(dirs)

    @classmethod
    def start_bag_record(cls, container_name: str,
                         current_user: dict, target_user: str = None) -> dict:
        logger.info(f"开始录制Bag: container={container_name}, user={current_user.get('username')}")

        cls._ensure_ros2_container(container_name)

        with _bag_sessions_lock:
            if container_name in _bag_sessions:
                session = _bag_sessions[container_name]
                if session.get("status") == "recording":
                    raise RuntimeError(f"容器 '{container_name}' 已有录制任务进行中")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bag_dir_name = f"rosbag2_{timestamp}"

        start_cmd = (
            f"source /home/boonray/install/setup.bash && "
            f"cd /home/boonray && "
            f"nohup ros2 bag record -s mcap --all -o {bag_dir_name} "
            f"> /tmp/bag_record.log 2>&1 &"
        )
        logger.debug(f"后台启动录制: {start_cmd}")
        rc, out, err = DockerManager.exec_command(container_name, start_cmd, timeout=15)

        if rc != 0:
            logger.error(f"启动录制失败: rc={rc}, out={out}, err={err}")
            raise RuntimeError(f"启动录制失败: {err or out or '未知错误'}")

        time.sleep(2)

        verify_cmd = f"pgrep -f 'ros2 bag record' || echo ''"
        vrc, vout, verr = DockerManager.exec_command(container_name, verify_cmd, timeout=5)
        if not vout.strip():
            log_cmd = "cat /tmp/bag_record.log 2>/dev/null || echo 'no log'"
            lrc, lout, _ = DockerManager.exec_command(container_name, log_cmd, timeout=5)
            logger.error(f"录制进程未成功启动，日志: {lout}")
            raise RuntimeError(f"录制进程未成功启动: {lout[:200]}")

        session = {
            "container_name": container_name,
            "started_at": time.time(),
            "timestamp": timestamp,
            "bag_dir_name": bag_dir_name,
            "status": "recording",
            "pid_info": vout.strip(),
        }
        with _bag_sessions_lock:
            _bag_sessions[container_name] = session

        logger.info(f"Bag录制已启动: container={container_name}, timestamp={timestamp}, pid={vout.strip()}")
        return {
            "success": True,
            "message": "录制已启动",
            "container_name": container_name,
            "timestamp": timestamp,
            "status": "recording",
        }

    @classmethod
    def stop_bag_record(cls, container_name: str,
                        current_user: dict, target_user: str = None) -> dict:
        logger.info(f"停止录制Bag: container={container_name}")

        with _bag_sessions_lock:
            session = _bag_sessions.get(container_name)

        if not session or session.get("status") != "recording":
            raise RuntimeError(f"容器 '{container_name}' 没有进行中的录制任务")

        bag_dir_name = session.get("bag_dir_name", "")
        timestamp = session.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))

        try:
            pkill_cmd = "pkill -f 'ros2 bag record' 2>/dev/null || true"
            rc, out, err = DockerManager.exec_command(container_name, pkill_cmd, timeout=10)
            time.sleep(3)

            check_cmd = "pgrep -f 'ros2 bag record' || echo ''"
            crc, cout, _ = DockerManager.exec_command(container_name, check_cmd, timeout=5)
            if cout.strip():
                logger.warning(f"录制进程仍在运行，强制 kill: {cout.strip()}")
                DockerManager.exec_command(container_name,
                    "pkill -9 -f 'ros2 bag record' 2>/dev/null || true", timeout=5)
                time.sleep(2)
            logger.info("录制进程已终止")
        except Exception as e:
            logger.warning(f"终止录制进程时出错: {e}")

        bag_storage = cls._get_bag_storage(current_user, target_user)

        container_bag_dir = ""
        if bag_dir_name:
            container_bag_dir = f"{cls.CONTAINER_BAG_PATH}/{bag_dir_name}"
            check_cmd = f"test -d {container_bag_dir} && echo 'exists' || echo ''"
            crc, cout, _ = DockerManager.exec_command(container_name, check_cmd, timeout=5)
            if not cout.strip():
                container_bag_dir = ""

        if not container_bag_dir:
            find_cmd = f"cd {cls.CONTAINER_BAG_PATH} && ls -dt rosbag2_* 2>/dev/null | head -1 || echo ''"
            rc, out, err = DockerManager.exec_command(container_name, find_cmd, timeout=10)
            container_bag_dir = out.strip().split("\n")[0].strip() if (rc == 0 and out.strip()) else ""

        if not container_bag_dir:
            raise RuntimeError(f"容器内未找到录制生成的bag目录 (rosbag2_*)")

        logger.info(f"找到bag目录: {container_bag_dir}")

        tar_name = f"{os.path.basename(container_bag_dir)}.tar.gz"
        host_tar_path = os.path.join(bag_storage, tar_name)

        container_tar_path = f"/tmp/{tar_name}"
        container_parent = os.path.dirname(container_bag_dir)
        container_basename = os.path.basename(container_bag_dir)

        tar_cmd = f"cd {container_parent} && tar -czf {container_tar_path} {container_basename}"
        logger.debug(f"容器内打包bag: {tar_cmd}")
        rc, out, err = DockerManager.exec_command(container_name, tar_cmd, timeout=300)
        if rc != 0:
            logger.error(f"容器内打包bag失败: rc={rc}, out={out}, err={err}")
            raise RuntimeError(f"容器内打包失败: {err or out or '未知错误'}")

        logger.info(f"容器内打包成功，开始拷贝到宿主机: {container_tar_path} -> {host_tar_path}")
        copy_cmd = DockerManager._docker("cp", f"{container_name}:{container_tar_path}", host_tar_path)
        rc, out, err = DockerManager.run_cmd(copy_cmd, timeout=120)
        if rc != 0:
            logger.error(f"拷贝bag失败: rc={rc}, err={err}")
            raise RuntimeError(f"拷贝到宿主机失败: {err or out or '未知错误'}")

        try:
            DockerManager.exec_command(container_name, f"rm -f {container_tar_path}", timeout=10)
        except Exception:
            pass

        file_size = os.path.getsize(host_tar_path) if os.path.isfile(host_tar_path) else 0

        with _bag_sessions_lock:
            if container_name in _bag_sessions:
                _bag_sessions[container_name]["status"] = "stopped"

        logger.info(f"Bag录制完成: {host_tar_path}, size={file_size}")
        return {
            "success": True,
            "message": "录制已停止并导出",
            "file_path": host_tar_path,
            "file_name": tar_name,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2),
            "duration_seconds": round(time.time() - session.get("started_at", time.time()), 1),
        }

    @classmethod
    def get_bag_status(cls, container_name: str) -> dict:
        with _bag_sessions_lock:
            session = _bag_sessions.get(container_name)

        if not session:
            return {
                "container_name": container_name,
                "status": "idle",
                "message": "无录制任务",
            }

        if session.get("status") == "recording":
            elapsed = round(time.time() - session.get("started_at", time.time()), 1)
            return {
                "container_name": container_name,
                "status": "recording",
                "elapsed_seconds": elapsed,
                "timestamp": session.get("timestamp"),
            }

        return {
            "container_name": container_name,
            "status": session.get("status", "unknown"),
            "timestamp": session.get("timestamp"),
        }

    @classmethod
    def list_bag_files(cls, current_user: dict, target_user: str = None) -> dict:
        bag_storage = cls._get_bag_storage(current_user, target_user)

        if not os.path.exists(bag_storage):
            return {"success": True, "files": [], "path": bag_storage}

        files = []
        try:
            for name in sorted(os.listdir(bag_storage)):
                p = os.path.join(bag_storage, name)
                if os.path.isfile(p):
                    st = os.stat(p)
                    files.append({
                        "name": name,
                        "size": st.st_size,
                        "size_mb": round(st.st_size / 1024 / 1024, 2),
                        "mtime": int(st.st_mtime),
                    })
        except PermissionError:
            raise RuntimeError("无权限访问bag目录")

        return {"success": True, "files": files, "path": bag_storage}
