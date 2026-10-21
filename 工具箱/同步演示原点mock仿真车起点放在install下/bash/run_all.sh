#!/usr/bin/env bash
# 一键执行：
#   第一步  为每台运行中的 mock 车各开一个已 source 好 ROS2 的终端（任务1）
#   第二步  批量采集每台车的 x/y/yaw 并回填 truckfz_c<编号>.yaml（任务2）
#
# 用法:
#   ./run_all.sh                 # 开终端 + 写入（写入前会确认）
#   ./run_all.sh --dry-run       # 开终端 + 只预览不写入
#   ./run_all.sh --no-terminal   # 跳过第一步，只采集回填
#   ./run_all.sh -y              # 写入不询问
# 其余参数（-j/-t/车辆编号）会透传给 fill_start_points.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OPEN_TERMINAL=1
FILL_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --no-terminal) OPEN_TERMINAL=0; shift ;;
        *) FILL_ARGS+=("$1"); shift ;;
    esac
done

echo "############ 第一步：为每台运行中的 mock 车打开终端 ############"
if [ "$OPEN_TERMINAL" = "1" ]; then
    "$SCRIPT_DIR/open_truck_terminals.sh" || \
        echo "[警告] 终端打开失败/无图形界面，继续执行采集。"
else
    echo "已跳过（--no-terminal）。"
fi

echo
echo "############ 第二步：采集定位并回填 truckfz_c*.yaml ############"
if [ "${#FILL_ARGS[@]}" -gt 0 ]; then
    "$SCRIPT_DIR/fill_start_points.sh" "${FILL_ARGS[@]}"
else
    "$SCRIPT_DIR/fill_start_points.sh"
fi
