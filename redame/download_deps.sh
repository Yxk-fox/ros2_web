#!/bin/bash
: <<'HEADER'
版权所有：上海伯镭科技有限公司
@File    :  download_deps.sh
@Time    :  2026/07/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  Mock Truck 管理工具 - 离线依赖下载脚本

            代码结构：
            1. 脚本安全设置
            2. 下载目录配置
            3. 依赖清单复制（从同目录 requirements.txt）
            4. 依赖包下载
            5. 离线包打包
            6. 启动入口
HEADER
# ============================================================
# Mock Truck - 依赖下载脚本（离线安装包生成）
# 版本: 4.0-decoupled
# 更新日期: 2026-07-21
# ============================================================
# 用途：在联网环境下下载所有依赖包，打包为离线安装包
# 使用方法（文件位于 redame/ 目录）：
#   chmod +x ~/ros2_web/redame/download_deps.sh
#   ~/ros2_web/redame/download_deps.sh
# ============================================================

set -e

# ---------- 配置 ----------
PACKAGE_DIR="$HOME/ros2_offline_packages"
PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"

# ---------- 创建目录 ----------
echo "📁 创建离线包目录: $PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR/packages"
cd "$PACKAGE_DIR"

# ---------- 复制 requirements.txt ----------
if [ -f "$REQ_FILE" ]; then
    echo "📝 复制 requirements.txt（来源: $REQ_FILE）..."
    cp "$REQ_FILE" requirements.txt
else
    echo "❌ 未找到 requirements.txt: $REQ_FILE"
    exit 1
fi

# ---------- 下载依赖包 ----------
echo "⬇️ 开始下载依赖包（使用清华镜像源）..."
pip3 download -r requirements.txt -d ./packages -i "$PIP_INDEX"

# ---------- 打包 ----------
echo "📦 打包离线包..."
tar -czf ros2_offline_packages.tar.gz packages/ requirements.txt

# ---------- 输出信息 ----------
echo ""
echo "============================================================"
echo "✅ 离线包已打包完成！"
echo "📁 位置: $PACKAGE_DIR/ros2_offline_packages.tar.gz"
echo "📦 大小: $(du -h ros2_offline_packages.tar.gz | cut -f1)"
echo ""
echo "📌 安装方法（在目标机器上）："
echo "   1. 解压: tar -xzf ros2_offline_packages.tar.gz"
echo "   2. 安装: pip3 install --no-index --find-links=./packages -r requirements.txt"
echo "============================================================"

# ============================================================
# 预留扩展区域（共50行）
# 以下为未来可能需要下载的额外依赖，默认注释
# ============================================================
# echo "⬇️ 下载额外依赖（SQLAlchemy）..."
# pip3 download sqlalchemy==2.0.30 -d ./packages -i "$PIP_INDEX"
#
# echo "⬇️ 下载额外依赖（Redis）..."
# pip3 download redis==5.0.1 -d ./packages -i "$PIP_INDEX"
#
# echo "⬇️ 下载额外依赖（Celery）..."
# pip3 download celery==5.3.6 -d ./packages -i "$PIP_INDEX"
#
# echo "⬇️ 下载额外依赖（Prometheus）..."
# pip3 download prometheus-client==0.20.0 -d ./packages -i "$PIP_INDEX"
#
# echo "⬇️ 下载额外依赖（测试框架）..."
# pip3 download pytest==8.2.0 -d ./packages -i "$PIP_INDEX"
# pip3 download pytest-asyncio==0.23.0 -d ./packages -i "$PIP_INDEX"
# pip3 download httpx==0.27.0 -d ./packages -i "$PIP_INDEX"
#
# echo "⬇️ 下载额外依赖（异步数据库驱动）..."
# pip3 download aiosqlite==0.20.0 -d ./packages -i "$PIP_INDEX"
# pip3 download asyncpg==0.29.0 -d ./packages -i "$PIP_INDEX"
