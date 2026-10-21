#!/usr/bin/env bash
# 在【容器内部】运行：source 环境后读取一次定位数据。
# 输出单行:  x=<值> y=<值> yaw=<值>
# 由主机脚本通过  docker exec <容器> bash /home/boonray/install/bash/container_echo.sh  调用
#
# 可选环境变量:
#   ECHO_TIMEOUT  等待话题的超时秒数（默认 15）
#   RAW=1         直接输出 ros2 topic echo 的原始 YAML（人工查看用）

set -u

SETUP="${SETUP:-/home/boonray/install/setup.bash}"
TOPIC="${LOC_TOPIC:-/localization/localization_data}"
TIMEOUT="${ECHO_TIMEOUT:-15}"

# colcon 的 setup.bash 与 set -u 不兼容，source 期间临时关闭
set +u
# shellcheck disable=SC1090
source "$SETUP"
set -u

if [ "${RAW:-0}" = "1" ]; then
    timeout "$TIMEOUT" ros2 topic echo "$TOPIC" --once
    exit $?
fi

out="$(timeout "$TIMEOUT" ros2 topic echo "$TOPIC" --once 2>/dev/null)" || {
    echo "ERROR: timeout_or_no_data"
    exit 1
}

x="$(printf '%s\n' "$out" | awk '/^x:/{print $2; exit}')"
y="$(printf '%s\n' "$out" | awk '/^y:/{print $2; exit}')"
yaw="$(printf '%s\n' "$out" | awk '/^yaw:/{print $2; exit}')"

if [ -z "$x" ] || [ -z "$y" ] || [ -z "$yaw" ]; then
    echo "ERROR: parse_failed"
    exit 1
fi

echo "x=$x y=$y yaw=$yaw"
