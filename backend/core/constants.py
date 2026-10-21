#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局常量模块
所有从配置衍生的全局常量集中定义
"""

import os
import pwd
import secrets
from dotenv import load_dotenv

load_dotenv()

from core.config import load_config, save_config

CONFIG = load_config()

home = pwd.getpwuid(os.getuid()).pw_dir


def _expand(p):
    """展开路径中的 ~ 和相对路径"""
    return os.path.expanduser(p)


# ---------- 安全配置 ----------
SECURITY = CONFIG.get("security", {})
JWT_SECRET = os.getenv("ROS2_WEB_JWT_SECRET") or SECURITY.get("jwt_secret", "CHANGE_ME_TO_A_RANDOM_SECRET")
if JWT_SECRET == "CHANGE_ME_TO_A_RANDOM_SECRET":
    import logging
    logging.getLogger("ros2-web").warning(
        "检测到默认 JWT 密钥，已自动生成本进程临时强密钥；生产环境请配置 ROS2_WEB_JWT_SECRET 或 config.json。"
    )
    JWT_SECRET = secrets.token_urlsafe(48)
JWT_ALGORITHM = SECURITY.get("jwt_algorithm", "HS256")
JWT_EXPIRE_MINUTES = SECURITY.get("jwt_expire_minutes", 1440)
BCRYPT_ROUNDS = SECURITY.get("bcrypt_rounds", 12)
# 用户管理：管理员「重置密码」按钮统一重置为该默认密码（明文存储于 users.password_plain，供管理员查看）
DEFAULT_RESET_PASSWORD = SECURITY.get("default_reset_password", "B@@nray!123")
RATE_LIMIT_ENABLED = SECURITY.get("rate_limit_enabled", False)
RATE_LIMIT_REQUESTS = SECURITY.get("rate_limit_requests", 5)
RATE_LIMIT_PERIOD = SECURITY.get("rate_limit_period", 60)
INPUT_FILTER_ENABLED = SECURITY.get("input_filter_enabled", False)
INPUT_FILTER_WHITELIST = SECURITY.get("input_filter_whitelist", ["ros2", "ls", "pwd", "echo", "cat", "source", "docker", "bash", "sh", "tc", "stress"])
AUDIT_ENABLED = SECURITY.get("audit_enabled", True)
AUDIT_LOG_FILE = _expand(SECURITY.get("audit_log_file", "~/ros2_web/audit.log"))

# ---------- 数据库配置 ----------
DB_TYPE = CONFIG.get("database", {}).get("type", "json")
DB_PATH = _expand(CONFIG["database"].get("path", "~/ros2_web/data/data.json"))
AUDIT_DB_PATH = _expand(CONFIG["database"].get("audit_path", "~/ros2_web/data/audit_logs.json"))
SUPABASE_URL = os.getenv("SUPABASE_URL") or CONFIG["database"].get("url", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or CONFIG["database"].get("key", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or CONFIG["database"].get("service_role_key", "")

# ---------- ROS2 工作空间 ----------
ROS2_DEFAULT = {
    "launch_dir": _expand(CONFIG["paths"]["launch_dir"]),
    "scripts_dir": _expand(CONFIG["paths"]["scripts_dir"]),
    "logs_dir": _expand(CONFIG["paths"]["logs_dir"]),
    "bag_storage": _expand(CONFIG["paths"]["bag_storage"]),
    "host_ws": _expand(CONFIG["ros2_workspace"]["host_ws"]),
    "host_install": _expand(CONFIG["ros2_workspace"]["host_install"]),
    "container_install": CONFIG["ros2_workspace"]["container_install"],
    "docker_image": CONFIG["docker"]["default_image"],
    "container_bag_path": CONFIG["ros2_workspace"]["container_bag_path"],
    "container_bag_path_alt": CONFIG["ros2_workspace"].get("container_bag_path_alt", "/home/boonray/.boonray/bagfiles"),
    "config_dir": _expand(CONFIG["paths"]["config_dir"]),
    "backup_dir": _expand(CONFIG["paths"]["backup_dir"])
}
WHITELIST_FILE = os.path.expanduser("~/.ros2_docker_manager_whitelist.json")
DEFAULT_WHITELIST = CONFIG["whitelist"]["default_prefixes"]
PORT = CONFIG["server"]["port"]
HOST = CONFIG["server"]["host"]
ROS2_WS = _expand(CONFIG["ros2_workspace"]["host_ws"])
INSTALL_DIR = _expand(CONFIG["ros2_workspace"]["host_install"])
SETUP_BASH = os.path.join(INSTALL_DIR, "setup.bash")
LAUNCH_DIR = os.path.join(INSTALL_DIR, "simulation_launches/share/simulation_launches/launch")
USE_SUDO = CONFIG["docker"]["use_sudo"]
DOCKER_PREFIX = "" if not USE_SUDO else "sudo "
CORS = CONFIG.get("cors", {})
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ROS2_WEB_CORS_ORIGINS", "").split(",") if o.strip()] or CORS.get("allow_origins", [])
CORS_ALLOW_ORIGIN_REGEX = CORS.get("allow_origin_regex")
PLUGIN_EXECUTION_ENABLED = CONFIG.get("plugins", {}).get("execution_enabled", False)

# ---------- 可视化配置 ----------
VISUALIZATION_CONFIG = CONFIG.get("visualization", {})
DEFAULT_VISUALIZATION_METHOD = VISUALIZATION_CONFIG.get("default_method", "vnc")
VISUALIZATION_METHODS = VISUALIZATION_CONFIG.get("methods", {})

# 全局共享状态
ws_clients = []
traffic_sender = None
timer_traffic_sender = None
manual_timer_traffic_sender = None

# 审计日志目录
os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)

# 面板权限列表
ALL_PANELS = [
    "welcome", "scripts", "advanced-scripts", "docker", "advanced-docker",
    "images", "traffic", "advanced-fault", "tools", "monitor",
    "simulation", "topics", "nodes", "services", "actions",
    "advanced-extend",
    "api-manager", "theme", "settings", "tickets",
    "data-export"
]
