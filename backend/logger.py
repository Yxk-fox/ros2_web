#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志管理模块
统一配置日志级别、格式和输出目标
"""

import logging
import os

LOG_DIR = os.path.expanduser("~/ros2_web/log")
os.makedirs(LOG_DIR, exist_ok=True)


class LogConfig:
    """日志配置管理类"""
    _initialized = False

    @staticmethod
    def setup(level=logging.INFO, log_file=None):
        handlers = [logging.StreamHandler()]
        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            handlers=handlers
        )
        return logging.getLogger("ros2-web")

    @staticmethod
    def init_default():
        if LogConfig._initialized:
            return logging.getLogger("ros2-web")
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        logger = logging.getLogger("ros2-web")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        file_handler_app = logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding='utf-8')
        file_handler_app.setLevel(logging.DEBUG)
        file_handler_app.setFormatter(formatter)
        logger.addHandler(file_handler_app)

        file_handler_audit = logging.FileHandler(os.path.join(LOG_DIR, "audit.log"), encoding='utf-8')
        file_handler_audit.setLevel(logging.INFO)
        file_handler_audit.setFormatter(formatter)
        logger.addHandler(file_handler_audit)

        file_handler_debug = logging.FileHandler(os.path.join(LOG_DIR, "audit_debug.log"), encoding='utf-8')
        file_handler_debug.setLevel(logging.DEBUG)
        file_handler_debug.setFormatter(formatter)
        logger.addHandler(file_handler_debug)

        LogConfig._initialized = True
        return logger


# 模块导入时自动初始化基础日志
logger = LogConfig.init_default()
