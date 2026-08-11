#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件管理模块
负责加载、保存和管理 config.json 配置
"""

import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def _default_config():
    """返回默认配置"""
    return {
        "server": {"host": "0.0.0.0", "port": 8875, "ssl_key": "", "ssl_cert": ""},
        "cors": {
            "allow_origins": ["http://localhost:8875", "http://127.0.0.1:8875"],
            "allow_origin_regex": r"https?://([a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\]):8875"
        },
        "plugins": {"execution_enabled": False},
        "security": {
            "jwt_secret": "CHANGE_ME_TO_A_RANDOM_SECRET",
            "jwt_algorithm": "HS256",
            "jwt_expire_minutes": 10080,
            "bcrypt_rounds": 12,
            "rate_limit_enabled": False,
            "rate_limit_requests": 5,
            "rate_limit_period": 60,
            "input_filter_enabled": False,
            "input_filter_whitelist": ["ros2", "ls", "pwd", "echo", "cat", "source", "docker", "bash", "sh", "tc", "stress"],
            "audit_enabled": True,
            "audit_log_file": "~/ros2_web/log/audit.log"
        },
        "database": {"type": "json", "path": "~/ros2_web/data/data.json", "audit_path": "~/ros2_web/data/audit_logs.json"},
        "docker": {"default_image": "ros2_humble_image:v1", "use_sudo": False},
        "ros2_workspace": {
            "host_ws": "~/robotruck_ros2",
            "host_install": "~/robotruck_ros2/install",
            "container_install": "/home/boonray/install",
            "container_bag_path": "/home/boonray/.boonray/bagfiles"
        },
        "paths": {
            "launch_dir": "~/robotruck_ros2/install/simulation_launches/share/simulation_launches/launch",
            "scripts_dir": "~/robotruck_ros2/Docker/scripts",
            "logs_dir": "~/robotruck_ros2/Docker/logs",
            "bag_storage": "~/robotruck_ros2/Docker/bags",
            "config_dir": "~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config",
            "backup_dir": "~/robotruck_ros2/Docker/bk"
        },
        "whitelist": {"default_prefixes": ["ros2_"]},
        "cloud_env": {
            "current_env": "106",
            "current_ip": "106.14.223.60",
            "ip_map": {
                "106": "106.14.223.60",
                "139": "139.196.75.44",
                "192": "192.168.9.252"
            }
        },
        "visualization": {
            "default_method": "vnc",
            "order": ["vnc", "rviz_x11", "rvizweb"],
            "methods": {
                "foxglove": {
                    "name": "Foxglove Studio",
                    "description": "Foxglove 已弃用，请使用 VNC 远程桌面",
                    "enabled": False,
                    "port": 9090,
                    "container_port": 9090,
                    "auto_install": False
                },
                "vnc": {
                    "name": "VNC远程桌面",
                    "description": "容器中启动VNC服务和XFCE桌面，通过Web浏览器访问完整桌面环境",
                    "enabled": True,
                    "port": 5901,
                    "container_port": 5901,
                    "web_port": 6080,
                    "container_web_port": 6080,
                    "password": "",
                    "auto_install": True,
                    "geometry": "1920x1080"
                },
                "rviz_x11": {
                    "name": "原生RVIZ (X11转发)",
                    "description": "在容器中启动原生RVIZ2，通过VNC查看",
                    "enabled": True,
                    "require_gpu": False,
                    "auto_install": True
                }
            }
        }
    }


def load_config():
    """加载配置文件，不存在则使用默认值"""
    import logging
    logger = logging.getLogger("ros2-web")
    defaults = _default_config()
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for section in defaults:
                if section in cfg:
                    defaults[section].update(cfg[section])
            logger.info(f"已加载配置文件: {CONFIG_FILE}")
        except Exception as e:
            logger.warning(f"配置文件加载失败，使用默认值: {e}")
    else:
        logger.info("未找到 config.json，使用默认配置")
    return defaults


def save_config(cfg):
    """保存配置到 config.json"""
    import logging
    logger = logging.getLogger("ros2-web")
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.info(f"配置已保存到: {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"配置保存失败: {e}")
        return False
