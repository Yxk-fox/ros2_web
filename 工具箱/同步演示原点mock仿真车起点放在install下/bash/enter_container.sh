#!/usr/bin/env bash
# 在【容器内部】运行：打印横幅、source ROS2 环境，然后交给交互式 bash。
# 由 open_truck_terminals.sh 通过 docker exec 调用，环境变量:
#   TRUCK_ID  车辆编号（仅用于显示）
# 用法: docker exec -it <容器> bash /home/boonray/install/bash/enter_container.sh

clear
printf '===================================================\n'
printf ' 仿真车终端  fz_c%s\n' "${TRUCK_ID:-?}"
printf ' ROS2 环境: %s\n' "/home/boonray/install/setup.bash"
printf ' 查看定位: ros2 topic echo /localization/localization_data --once\n'
printf '===================================================\n'

set +u
# shellcheck disable=SC1090
source /home/boonray/install/setup.bash
set -u

exec bash -i
