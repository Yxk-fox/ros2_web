#!/usr/bin/env bash
# 公共变量与函数（被其它脚本 source）
# 位置: install/bash/common.sh

# 本目录（install/bash）。容器内路径为 /home/boonray/install/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 容器内 ROS2 环境脚本（主机的 install 目录被挂载到容器的 /home/boonray/install）
CONTAINER_SETUP="/home/boonray/install/setup.bash"

# 容器内本脚本目录（与主机 SCRIPT_DIR 指向同一份挂载文件）
CONTAINER_BASH_DIR="/home/boonray/install/bash"

# 定位话题
LOC_TOPIC="/localization/localization_data"

# 配置文件目录（主机路径）
CONFIG_DIR="$INSTALL_DIR/simulation_launches/share/simulation_launches/config"

# 匹配运行中的 mock 仿真车容器，名字以 _fz_c<数字> 结尾
CONTAINER_REGEX='_fz_c[0-9]+$'

# 取一台运行中的 mock 车容器名 -> stdout
get_running_containers() {
    docker ps --format '{{.Names}}' \
        | grep -E "$CONTAINER_REGEX" \
        | sort -V
}

# 容器名 -> 车辆编号（如 ..._fz_c80 -> 80）
truck_id_of() {
    sed -E 's/.*_fz_c([0-9]+)$/\1/' <<<"$1"
}

# 车辆编号 -> 对应配置文件（主机路径），不存在则返回空
yaml_of_id() {
    local f="$CONFIG_DIR/truckfz_c$1.yaml"
    [ -f "$f" ] && printf '%s' "$f"
}

# 在指定容器内执行命令（登录式 shell，自动加载 ROS 环境）
# 用法: in_container <容器名> <命令串...>
in_container() {
    local name="$1"; shift
    docker exec -i "$name" bash -lc "$*"
}

# 交互方式在容器内开 shell（用于终端模拟器）
in_container_tty() {
    local name="$1"; shift
    docker exec -it "$name" bash -lic "$*"
}

# 采集单台车，结果写入 $1 临时文件:  <id>|<x>|<y>|<yaw> 或 <id>|ERROR|...
# 用法: collect_one <输出目录> <容器名>
# 依赖环境变量 TIMEOUT（可选，默认 15 秒）
collect_one() {
    local outdir="$1" cname="$2"
    local cid res to
    to="${TIMEOUT:-15}"
    cid="$(truck_id_of "$cname")"
    res="$(ECHO_TIMEOUT="$to" \
        docker exec -i "$cname" bash "$CONTAINER_BASH_DIR/container_echo.sh" 2>/dev/null || true)"
    if [[ "$res" == x=* ]]; then
        local x y yaw
        x="${res#*x=}";     x="${x%% *}"
        y="${res#*y=}";     y="${y%% *}"
        yaw="${res#*yaw=}"; yaw="${yaw%% *}"
        printf '%s|%s|%s|%s\n' "$cid" "$x" "$y" "$yaw" > "$outdir/$cid"
    else
        printf '%s|ERROR|%s\n' "$cid" "${res:-no_response}" > "$outdir/$cid"
    fi
}
