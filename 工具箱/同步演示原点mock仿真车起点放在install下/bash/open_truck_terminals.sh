#!/usr/bin/env bash
# 任务1：为【每一台运行中的 mock 仿真车容器】各打开一个终端，
#        终端已进入容器并 source 好 ROS2 环境，可直接执行:
#           ros2 topic echo /localization/localization_data --once
#
# 用法:
#   ./open_truck_terminals.sh            # 为全部运行中的车开终端
#   ./open_truck_terminals.sh 80 51 55   # 只为指定编号的车开终端
#
# 说明: 需要图形界面（本机桌面或已转发 X）。自动识别 gnome-terminal/
#       xterm/xfce4-terminal/konsole/mate-terminal；识别不到可用
#       TERMINAL=/path/to/your-terminal ./open_truck_terminals.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# ---------------- 终端模拟器检测 ----------------
# 输出两行: 第1行=终端类型, 第2行=实际可执行文件
# 注意: 部分系统里 /usr/bin/gnome-terminal 可能被替换/链接成 terminator，
#       需用 --version 判别真实身份，二者命令行参数不兼容。
detect_terminal() {
    if [ -n "${TERMINAL:-}" ] && command -v "$TERMINAL" >/dev/null 2>&1; then
        echo "custom"; echo "$TERMINAL"; return 0
    fi
    local bin ver
    # 真 GNOME Terminal
    if command -v gnome-terminal >/dev/null 2>&1; then
        ver="$(gnome-terminal --version 2>&1 || true)"
        if echo "$ver" | grep -qi 'gnome terminal'; then
            echo "gnome-terminal"; echo "$(command -v gnome-terminal)"; return 0
        fi
        if echo "$ver" | grep -qi 'terminator'; then
            echo "terminator"; echo "$(command -v gnome-terminal)"; return 0
        fi
    fi
    # 独立安装的 terminator
    if command -v terminator >/dev/null 2>&1; then
        echo "terminator"; echo "$(command -v terminator)"; return 0
    fi
    # 其它常见终端
    local t
    for t in xterm konsole xfce4-terminal mate-terminal \
             lxterminal tilix qterminal urxvt rxvt; do
        if command -v "$t" >/dev/null 2>&1; then echo "$t"; echo "$(command -v "$t")"; return 0; fi
    done
    return 1
}

# 用指定终端为某容器开窗（进入容器后执行 enter_container.sh）
launch_window() {
    local type="$1" bin="$2" cname="$3" cid="$4"
    local enter="$CONTAINER_BASH_DIR/enter_container.sh"

    case "$type" in
        gnome-terminal)
            "$bin" --title="fz_c$cid" -- \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter"
            ;;
        terminator)
            # terminator: -x 后全部作为命令及其参数
            "$bin" -T "fz_c$cid" -x \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
        konsole)
            "$bin" -p "RemoteTitle=fz_c$cid" -e \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
        xfce4-terminal)
            "$bin" --title="fz_c$cid" -e \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
        xterm|urxvt|rxvt)
            "$bin" -T "fz_c$cid" -e \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
        mate-terminal|lxterminal|tilix|qterminal)
            "$bin" --title="fz_c$cid" -e \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
        *)
            "$bin" -e \
                docker exec -it -e TRUCK_ID="$cid" "$cname" bash "$enter" &
            ;;
    esac
}

main() {
    local term_type term_bin
    if ! { IFS=$'\n' read -r term_type; IFS=$'\n' read -r term_bin; } < <(detect_terminal); then
        echo "[错误] 未找到可用的终端模拟器，请先安装 xterm（sudo apt install xterm），" >&2
        echo "       或用 TERMINAL=/路径/终端 $0 运行。" >&2
        exit 1
    fi
    echo "使用终端模拟器: $term_type ($term_bin)"

    local want=("$@")
    local -A want_map=()
    if [ "${#want[@]}" -gt 0 ]; then
        local w; for w in "${want[@]}"; do want_map["$w"]=1; done
    fi

    mapfile -t containers < <(get_running_containers)
    if [ "${#containers[@]}" -eq 0 ]; then
        echo "[提示] 当前没有运行中的 mock 仿真车容器。" >&2
        exit 0
    fi

    local n=0 cname cid
    for cname in "${containers[@]}"; do
        cid="$(truck_id_of "$cname")"
        if [ "${#want_map[@]}" -gt 0 ] && [ -z "${want_map[$cid]:-}" ]; then
            continue
        fi
        echo "打开终端 -> fz_c$cid  ($cname)"
        launch_window "$term_type" "$term_bin" "$cname" "$cid"
        n=$((n+1))
        sleep 0.4
    done
    echo "完成，共打开 $n 个终端。"
}

main "$@"
