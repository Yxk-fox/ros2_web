#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户工作空间管理模块
"""

import os
import shutil
import subprocess
from fastapi import HTTPException

from logger import logger
from core.constants import ROS2_DEFAULT

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
    """
    # 管理员可指定查看其他用户的工作空间
    effective_user = current_user
    if target_user and current_user.get("role") == "admin":
        from database import db
        user = db.get_user(target_user) or db.get_user_by_id(target_user)
        if user:
            effective_user = user
    
    if effective_user.get("role") == "admin" and not target_user:
        # 管理员全局操作（未指定target_user）时使用全局默认路径
        result = {
            "scripts_dir": ROS2_DEFAULT["scripts_dir"],
            "logs_dir": ROS2_DEFAULT["logs_dir"],
            "bag_storage": ROS2_DEFAULT["bag_storage"],
            "backup_dir": ROS2_DEFAULT["backup_dir"],
            "launch_dir": ROS2_DEFAULT["launch_dir"],
            "host_ws": ROS2_DEFAULT["host_ws"],
            "host_install": ROS2_DEFAULT["host_install"],
            "container_install": ROS2_DEFAULT["container_install"],
            "container_bag_path": ROS2_DEFAULT["container_bag_path"],
            "container_bag_path_alt": ROS2_DEFAULT["container_bag_path_alt"],
            "config_dir": ROS2_DEFAULT["config_dir"],
            "bk_backups_dir": os.path.join(ROS2_DEFAULT["backup_dir"], ".bk_backups"),
            "target_user": target_user,
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
    user_install = os.path.join(home_folder_path, "install")
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
    }

def create_user_workspace(username: str) -> str:
    """创建用户工作目录和基础Docker运行环境"""
    base_path = os.path.expanduser("~/robotruck_ros2")
    user_home = os.path.join(base_path, username)
    
    docker_dir = os.path.join(user_home, "Docker")
    subdirs = ["bags", "bk", "logs", "scripts"]
    
    try:
        os.makedirs(user_home, exist_ok=True)
        os.makedirs(docker_dir, exist_ok=True)
        
        for subdir in subdirs:
            os.makedirs(os.path.join(docker_dir, subdir), exist_ok=True)
        
        os.chmod(user_home, 0o755)
        os.chmod(docker_dir, 0o755)
        for subdir in subdirs:
            os.chmod(os.path.join(docker_dir, subdir), 0o755)
        
        src_bk = os.path.expanduser("~/robotruck_ros2/Docker/bk")
        dst_bk = os.path.join(docker_dir, "bk")
        if os.path.isdir(src_bk):
            for item in os.listdir(src_bk):
                src_item = os.path.join(src_bk, item)
                dst_item = os.path.join(dst_bk, item)
                if os.path.isdir(src_item):
                    if os.path.exists(dst_item):
                        shutil.rmtree(dst_item)
                    shutil.copytree(src_item, dst_item)
                else:
                    shutil.copy2(src_item, dst_item)
        
        try:
            subprocess.run(["chown", "-R", "fox:fox", user_home], capture_output=True)
        except Exception:
            pass
        
        logger.info(f"已创建用户工作目录: {user_home}")
        return user_home
    except Exception as e:
        logger.error(f"创建用户工作目录失败: {e}")
        raise HTTPException(500, f"创建用户工作目录失败: {e}")
