#!/usr/bin/env bash
# 任务2：读取每一台运行中 mock 车的定位(x/y/yaw)，并回填到各自的
#        simulation_launches/.../config/truckfz_c<编号>.yaml 的起始点：
#            start_x / start_y / start_yaw
#
# 单位（已核对 mock_vehicle.py：内部 math.radians(start_yaw)）：
#   start_yaw 与话题 yaw 同为“度”，直接填入，不做换算；x/y 为米，直接填入。
#
# 用法:
#   ./fill_start_points.sh                # 采集全部运行中的车并写入（先备份）
#   ./fill_start_points.sh 80 51 55       # 只处理指定编号
#   ./fill_start_points.sh --dry-run      # 只采集并预览，不改文件
#   ./fill_start_points.sh -j 12          # 并发采集数（默认 8）
#   ./fill_start_points.sh -t 20          # 单车等待话题超时秒数（默认 15）
#
# 选项:
#   -n, --dry-run   只预览不写入
#   -y, --yes       写入前不询问
#   -j N            并发数
#   -t N            单车超时(秒)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

DRY_RUN=0
ASSUME_YES=0
JOBS=8
TIMEOUT=15
IDS=()

while [ $# -gt 0 ]; do
    case "$1" in
        -n|--dry-run) DRY_RUN=1; shift ;;
        -y|--yes)     ASSUME_YES=1; shift ;;
        -j)           JOBS="$2"; shift 2 ;;
        -t)           TIMEOUT="$2"; shift 2 ;;
        -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            IDS+=("$1"); shift ;;
    esac
done

TS="$(date +%Y%m%d_%H%M%S)"
LOG="$SCRIPT_DIR/fill_result_$TS.txt"

# 用 awk 精确替换某 key 的值，保留原缩进
set_key() {
    local file="$1" key="$2" val="$3"
    awk -v k="$key" -v v="$val" '
        {
            if ($0 ~ "^[[:space:]]*"k":[[:space:]]*") {
                match($0, /^[[:space:]]*/)
                indent = substr($0, 1, RLENGTH)
                $0 = indent k ": " v
            }
            print
        }' "$file"
}

main() {
    mapfile -t containers < <(get_running_containers)
    if [ "${#containers[@]}" -eq 0 ]; then
        echo "[提示] 当前没有运行中的 mock 仿真车容器。" >&2; exit 0
    fi

    # 过滤指定编号
    local -A want_map=()
    if [ "${#IDS[@]}" -gt 0 ]; then local i; for i in "${IDS[@]}"; do want_map["$i"]=1; done; fi
    local targets=() cname cid
    for cname in "${containers[@]}"; do
        cid="$(truck_id_of "$cname")"
        if [ "${#want_map[@]}" -eq 0 ] || [ -n "${want_map[$cid]:-}" ]; then
            targets+=("$cname")
        fi
    done

    echo "运行中的 mock 车: ${#targets[@]} 台；并发 $JOBS；单车超时 ${TIMEOUT}s；配置目录:"
    echo "  $CONFIG_DIR"
    [ "$DRY_RUN" = "1" ] && echo "  模式: DRY-RUN（不写入）"

    # ---------- 并发采集 ----------
    local tmp; tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp:-}"' EXIT
    local c
    for c in "${targets[@]}"; do printf '%s\0%s\0' "$tmp" "$c"; done \
        | TIMEOUT="$TIMEOUT" xargs -0 -n2 -P"$JOBS" bash -c '
            source "'"$SCRIPT_DIR"'/common.sh"
            collect_one "$0" "$1"'

    # ---------- 回填 ----------
    local ok=0 fail=0 skip=0
    {
        printf '# fill_start_points 结果 %s\n' "$TS"
        printf 'id  x  y  yaw  yaml  status\n'
    } > "$LOG"

    # 按编号数字升序处理
    local f
    for f in $(ls -1 "$tmp" | sort -V); do
        local line x y yaw yaml
        line="$(cat "$tmp/$f")"
        cid="$f"
        if [[ "$line" == *"|ERROR|"* ]]; then
            printf '[失败] fz_c%-3s 采集不到定位: %s\n' "$cid" "${line#*|ERROR|}"
            printf '%s  -  -  -  -  COLLECT_FAILED\n' "$cid" >> "$LOG"
            fail=$((fail+1)); continue
        fi
        IFS='|' read -r _ x y yaw <<<"$line"
        yaml="$(yaml_of_id "$cid" || true)"
        if [ -z "$yaml" ]; then
            printf '[跳过] fz_c%-3s 找不到配置文件 truckfz_c%s.yaml\n' "$cid" "$cid"
            printf '%s  %s  %s  %s  -  YAML_NOT_FOUND\n' "$cid" "$x" "$y" "$yaw" >> "$LOG"
            skip=$((skip+1)); continue
        fi

        if [ "$DRY_RUN" = "1" ]; then
            printf '[预览] fz_c%-3s start_x=%s start_y=%s start_yaw=%s -> %s\n' \
                "$cid" "$x" "$y" "$yaw" "$(basename "$yaml")"
            printf '%s  %s  %s  %s  %s  DRY_RUN\n' "$cid" "$x" "$y" "$yaw" "$(basename "$yaml")" >> "$LOG"
            ok=$((ok+1)); continue
        fi

        # 备份后写入（每个文件备份一次）
        cp -a "$yaml" "$yaml.bak_$TS"
        set_key "$yaml" start_x   "$x"   > "$yaml.tmp"
        set_key "$yaml.tmp" start_y "$y" > "$yaml.tmp2"
        set_key "$yaml.tmp2" start_yaw "$yaw" > "$yaml.tmp3"
        mv "$yaml.tmp3" "$yaml"; rm -f "$yaml.tmp" "$yaml.tmp2"
        printf '[完成] fz_c%-3s start_x=%s start_y=%s start_yaw=%s -> %s (已备份)\n' \
            "$cid" "$x" "$y" "$yaw" "$(basename "$yaml")"
        printf '%s  %s  %s  %s  %s  WRITTEN\n' "$cid" "$x" "$y" "$yaw" "$(basename "$yaml")" >> "$LOG"
        ok=$((ok+1))
    done

    echo "------------------------------------------------------------"
    echo "成功 $ok，失败 $fail，跳过 $skip。明细: $LOG"
    [ "$fail" -gt 0 ] && return 2
    return 0
}

# 写入前确认（非 dry-run 且交互且未加 -y）
if [ "$DRY_RUN" = "0" ] && [ "$ASSUME_YES" = "0" ] && [ -t 0 ]; then
    read -rp "将备份并改写各 truckfz_c*.yaml 的起始点，是否继续? [y/N] " ans
    case "$ans" in y|Y|yes|YES) ;; *) echo "已取消。"; exit 1;; esac
fi

main
