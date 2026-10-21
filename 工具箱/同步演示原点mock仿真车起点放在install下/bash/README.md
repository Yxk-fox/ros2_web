# 仿真车起始点回填脚本

本目录下的脚本用于管理运行中的 mock 仿真车容器，主要功能是：
1. 为每台运行中的 mock 车各打开一个已 source 好 ROS2 环境的终端（便于人工查看）
2. 自动采集每台车当前的定位 `(x, y, yaw)`，并回填到对应的
   `simulation_launches/.../config/truckfz_c<编号>.yaml` 的起始点字段，
   以便下次重启仿真车时使用当前位置作为新起始点。

---

## 目录结构

```
install/
├── bash/                              # 本目录，主机端 shell 脚本
│   ├── common.sh                     # 公共变量与函数（被其它脚本 source）
│   ├── container_echo.sh             # 容器内执行：读取一次定位并解析 x/y/yaw
│   ├── enter_container.sh            # 容器内执行：打印横幅 + source ROS2 + 交互 shell
│   ├── fill_start_points.sh          # 主脚本：批量采集 + 回填 yaml 起始点
│   ├── open_truck_terminals.sh       # 为每台车各开一个 ROS2 终端
│   ├── run_all.sh                    # 一键：开终端 + 回填起始点
│   └── fill_result_*.txt             # 每次回填产生的明细日志（自动生成）
└── simulation_launches/share/simulation_launches/config/
    └── truckfz_c<编号>.yaml          # 每台车对应的参数文件
```

### 路径约定

| 主机路径                                  | 容器内路径                            |
|------------------------------------------|--------------------------------------|
| `install/`                               | `/home/boonray/install`              |
| `install/bash/`                          | `/home/boonray/install/bash/`        |
| `install/setup.bash`                     | `/home/boonray/install/setup.bash`   |

容器名固定以 `_fz_c<编号>` 结尾（如 `ros2_admin_..._fz_c55`），脚本据此匹配。

---

## 各脚本说明

### 1. `common.sh`（被 source，不直接执行）

定义所有公共变量与函数：

| 名称                       | 说明                                                                |
|---------------------------|--------------------------------------------------------------------|
| `CONTAINER_REGEX`         | 容器名匹配正则：`_fz_c[0-9]+$`                                     |
| `LOC_TOPIC`               | 定位话题：`/localization/localization_data`                        |
| `get_running_containers`  | 列出所有运行中的 mock 车容器名（已 `sort -V`）                     |
| `truck_id_of`             | 容器名 → 车辆编号（如 `..._fz_c80` → `80`）                       |
| `yaml_of_id`              | 车辆编号 → 对应 `truckfz_c<编号>.yaml` 主机路径                    |
| `collect_one`             | 采集单台车的 x/y/yaw，结果写入临时文件 `<id>`                       |
| `in_container` / `in_container_tty` | 在容器内执行命令 / 交互式 shell                       |

### 2. `container_echo.sh`（容器内执行）

由主机脚本通过 `docker exec` 调用，输出单行：
```
x=<值> y=<值> yaw=<值>
```

环境变量：
- `ECHO_TIMEOUT`：等待话题超时秒数（默认 15）
- `RAW=1`：直接输出原始 YAML（人工查看用）
- `SETUP`：ROS2 setup.bash 路径
- `LOC_TOPIC`：定位话题名

### 3. `enter_container.sh`（容器内执行）

由 `open_truck_terminals.sh` 通过 `docker exec -it` 调用，进入容器后：
1. 打印横幅（含车辆编号、ROS2 路径、常用命令提示）
2. `source /home/boonray/install/setup.bash`
3. `exec bash -i` 进入交互式 shell

环境变量：`TRUCK_ID`（仅用于显示）。

### 4. `fill_start_points.sh`（主脚本：采集 + 回填）

```bash
./fill_start_points.sh                # 采集全部运行中的车并写入（先备份）
./fill_start_points.sh 80 51 55       # 只处理指定编号
./fill_start_points.sh --dry-run      # 只采集并预览，不改文件
./fill_start_points.sh -y             # 写入前不询问
./fill_start_points.sh -j 12          # 并发采集数（默认 8）
./fill_start_points.sh -t 20          # 单车等待话题超时秒数（默认 15）
./fill_start_points.sh -h            # 查看帮助
```

选项：

| 选项            | 说明                          |
|----------------|------------------------------|
| `-n` / `--dry-run` | 只预览不写入                |
| `-y` / `--yes`     | 写入前不询问                |
| `-j N`             | 并发数（默认 8）            |
| `-t N`             | 单车超时秒数（默认 15）     |

执行流程：
1. `docker ps` 列出所有运行中的 mock 车容器
2. 用 `xargs -P` 并发，每台车在容器内运行 `container_echo.sh` 采集 x/y/yaw
3. 对每台车：
   - 找到对应的 `truckfz_c<编号>.yaml`（找不到则跳过）
   - 备份为 `<yaml>.bak_<时间戳>`
   - 用 `awk` 精确替换 `start_x` / `start_y` / `start_yaw` 三个字段，
     保留原缩进和注释
4. 输出明细到 `fill_result_<时间戳>.txt`
5. 退出码：0=成功；2=有采集失败

### 5. `open_truck_terminals.sh`（开终端）

```bash
./open_truck_terminals.sh            # 为全部运行中的车开终端
./open_truck_terminals.sh 80 51 55   # 只为指定编号的车开终端
```

- 自动检测 `gnome-terminal` / `terminator` / `xterm` / `konsole` /
  `xfce4-terminal` / `mate-terminal` / `lxterminal` / `tilix` / `qterminal`
  / `urxvt` / `rxvt`
- 检测不到时可用：`TERMINAL=/path/to/terminal ./open_truck_terminals.sh`
- 每个终端会进入对应容器、source ROS2 环境，可直接执行：
  ```
  ros2 topic echo /localization/localization_data --once
  ```

### 6. `run_all.sh`（一键执行）

```bash
./run_all.sh                 # 开终端 + 写入（写入前会确认）
./run_all.sh --dry-run       # 开终端 + 只预览不写入
./run_all.sh --no-terminal   # 跳过第一步，只采集回填
./run_all.sh -y              # 写入不询问
```
其余参数（`-j` / `-t` / 车辆编号）会透传给 `fill_start_points.sh`。

---

## 典型用法

### 场景 1：回填全部车的当前位置到 yaml

```bash
cd install/bash
./fill_start_points.sh -y
```
执行后每台车的 `truckfz_c<编号>.yaml` 中 `start_x / start_y / start_yaw`
会被替换为当前定位值，原文件备份为 `.bak_<时间戳>`。

### 场景 2：只看一台车的当前位置（不改文件）

```bash
./fill_start_points.sh --dry-run 55
```
输出示例：
```
[预览] fz_c55  start_x=-94.85662295942166 start_y=239.48872156453595 start_yaw=-68.42039580221658 -> truckfz_c55.yaml
```

### 场景 3：手动查看某台车定位（不开终端）

```bash
docker exec -i <容器名> bash /home/boonray/install/bash/container_echo.sh
```
输出：
```
x=-94.85662295942166 y=239.48872156453595 yaw=-68.42039580221658
```

### 场景 4：手动查看原始话题数据

```bash
docker exec -i <容器名> bash -c \
  'source /home/boonray/install/setup.bash && \
   ros2 topic echo /localization/localization_data --once'
```

### 场景 5：开终端进容器手测

```bash
./open_truck_terminals.sh 55
```
进入容器后直接：
```bash
ros2 topic echo /localization/localization_data --once
```

---

## 字段说明

`truckfz_c<编号>.yaml` 中 `mock_truck` 段：

```yaml
mock_truck:
  wheel_base: 4.0
  # 起始点
  start_x: <x 米>      # 与话题 x 字段同单位（米），直接填入
  start_y: <y 米>      # 与话题 y 字段同单位（米），直接填入
  start_z: 0.0         # z 不采集，保持原值
  start_yaw: <yaw 度>  # 与话题 yaw 同为度，直接填入（内部 math.radians 换算）
```

---

## 故障排查

| 现象                                 | 可能原因 / 处理                                                              |
|-------------------------------------|----------------------------------------------------------------------------|
| `当前没有运行中的 mock 仿真车容器`    | 用 `docker ps` 检查容器是否在运行；容器名必须以 `_fz_c<数字>` 结尾          |
| `[失败] 采集不到定位: timeout_or_no_data` | 定位话题未发布；可在容器内手动 `ros2 topic echo` 验证；用 `-t 30` 增加超时 |
| `[跳过] 找不到配置文件`              | `truckfz_c<编号>.yaml` 不存在；检查 `config/` 目录下是否有对应编号的文件   |
| `未找到可用的终端模拟器`             | 安装 `xterm`：`sudo apt install xterm`；或用 `TERMINAL=...` 显式指定        |
| 终端打开但 ROS2 命令找不到            | 容器内 `/home/boonray/install/setup.bash` 不存在；检查 install 目录是否挂载 |
| awk 替换后缩进丢失                   | 不会发生，`set_key` 用 `match($0, /^[[:space:]]*/)` 保留原缩进              |

### 查看回填明细

每次执行会在本目录生成 `fill_result_<时间戳>.txt`，记录每台车的处理结果：
```
id  x  y  yaw  yaml  status
55  -94.85662295942166  239.48872156453595  -68.42039580221658  truckfz_c55.yaml  WRITTEN
```

---

## 单位与字段对应

| 话题字段         | yaml 字段       | 单位 | 备注                       |
|-----------------|-----------------|-----|----------------------------|
| `x`             | `start_x`       | 米  | 直接填入                   |
| `y`             | `start_y`       | 米  | 直接填入                   |
| `yaw`           | `start_yaw`     | 度  | 内部用 `math.radians` 换算 |
| `z`             | `start_z`       | 米  | 脚本不采集，保持 0.0       |
