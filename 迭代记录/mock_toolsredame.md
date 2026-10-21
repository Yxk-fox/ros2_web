1. 运行环境与启动
依赖
用途
说明
Python3 + tkinter
全部页面
系统自带
图形桌面 (DISPLAY)
全部页面
需在桌面会话中运行，SSH 终端里无法弹出界面
paho-mqtt
云平台工具-MQTT
未安装时点「连接」会提示 pip install paho-mqtt
requests
仿真测试-API
单案例 / 批量任务收发
docker + 镜像 ros2_humble_image:v1 / robotruck*
仿真测试、目标点更新、烧录相关
需已装 GPU 驱动（--gpus all）
expect / sudo
Orin 烧录
驱动 tztek_flash.sh，执行时需 sudo 密码
rosbag（可选）/ planning_msgs
地图工具
无 rosbag 时用内置解析器；地图转换需 map_pb2 可导入
mock_tools.py
启动方式（桌面终端）：
python3 mock_tools.py
[图片]
2. 首页
- 标题：Mock 辅助测试工具，主体为 10 张卡片，每行 4 张，点击进入对应页面。
- 卡片一览：
页面
色标
主要功能
Chair 座椅控制
蓝
座椅控车 / 附件 / 任务 / 车况回显 / 延时模拟
V2E 控车
绿
行走 / 举升 / 转向
故障模拟
橙
组合故障一键触发 / 车辆反馈改写
交通灯控制
紫
手动 / 计时 / 多灯独立
地图工具
青
bag 大小分析 / map 格式转换
仿真测试
红
单案例 / 批量 / 容器会话
Orin 烧录
灰
镜像扫描 / 整机烧录
网络工具
蓝
tc 入口 UDP 延迟注入 / 清理
云平台工具
橙
UDP 灯态 / MQTT / TCP
目标点更新
深蓝
dump_goal 坐标平移

---
3. Chair 座椅控制
用途：模拟座椅控制器（本机 seat_control_01）对目标车（默认 fz_c01）发送控制指令并接收车况回显。
3.1 设置区
- 控制模式：UDP直连JSON / 铲运转发JSON（经铲运机 notify_to_device 转发）/ UDP直连PB（protobuf 指令）。
- 控制开关「开始控制」：勾选后每 0.2s 持续下发行走/挡位/油门等控制指令，右上角状态变为"控制中"。
- 回复延时：0–999ms 滑条，模拟 network_latency 探测的网络延时（用于延时测试）。
- SN 配置：可修改 目标车SN / 本设备SN，点「应用」生效。
- 急停：勾选后 emergency_stop=1 随控制指令每 0.2s 发送。
- 忽略障碍物：「常开」每 0.5s 自动发；或点「发送一次」。
3.2 控制指令区（随控制开关每 0.2s 发送）
- 驾驶模式：人工 / 遥控 / 自动；挡位：P/R/N/D；PTO：保持 / 上升 / 下降。
- 油门、刹车、转向（0–100 / 0–100 / 100…-100，左正右负，「归0」一键回中）。
3.3 附件控制区
以 6@ chair_control_cmd 发送：转向灯(左/右/关)、前照灯、空调、雨刮、雨刮喷水、缓行器、
差速锁、示廓灯、室内灯、前雾灯、前工作灯、侧照灯、应急转向、雨棚（每个「开」/「关」）。
3.4 任务指令区（一次性 chair_rt_msg_ctv）
开始自动驾驶、停止任务、暂停任务、路径录制、复位自动、自动举升。
3.5 自定义原始报文区
- 前缀：1@ UDP直连 / 6@ Chair直连 / 7@ UDP本地；可勾选「走铲运」。
- method 输入名称，params 框填 JSON（如 {"target_drive_mode": 1}），点「发送报文」。
- 默认 method：chair_control_cmd。
3.6 车况回显区
实时显示车端下发的 chair_rt_msg_vtc 字段（驾驶模式 / 挡位 / 车速 / SOC / 电池电压电流 /
电机转速 / 油门 / 刹车 / 前轮转角 / 举升角 / 取力器 / 手刹 / 急停来源 / 网络与座椅延时 / 故障等级）。
注意：心跳与回显依赖车端/铲运端在线；页面离开时自动清理 UDP socket 与线程。

---
4. V2E 控车
用途：模拟铲运控制器对目标车（fz_c01）的控制，支持行走与举升。
- 控制模式：勾选「开始控制」后进入受控状态；异常拒绝时下方红字显示拒绝原因。
- 动作模式：行走 或 举升，切换显示对应面板。
- 行走：挡位 R/D → 点「启动移动」（再次点击=停止）→ 转向滑条（左正右负，可归0）+ 油门。
- 举升：货厢控制 保持 / 上升 / 下降 + 油门配合。
- 日志区显示收发报文。

---
5. 故障模拟
用途：让 decision_center 命中判定、自动上报故障（直接发故障码无效，改的是车辆反馈）。
原理（页面「说明」区）
故障由 decision_center 检测并上报；本页通过 mock_vehicle 的
/mock_truck/change_status（反馈模拟）与 /mock_truck/change_mock_status（通用属性改写）
改写 pitch / lift_angle 等反馈，让 DC 命中判定后自然触发。模拟值需在对应任务状态下才生效。
mock_vehicle 私有属性经名称修饰，JSON 键需用 _MockVehicle__pitch / _MockVehicle__liftAngle。
操作区
- 一键触发故障（组合场景）：点按钮即触发对应组合，下方显示故障码与说明；「恢复正常 (pitch=0, lift_angle=0)」一键复位。
- 车辆反馈模拟（change_status 全部方法，3 列网格）：bit 项直接点 1/0 即发送；
其余项填值后点「发送」；每项可「复位」；顶部「全部复位」。tpms 特殊项 0=低 / 780=常。
- 通用属性改写：属性名栏（可写 _MockVehicle__xxx 私有属性）+ 值 → 发送。
注意：本页需要本机有 rclpy 且 mock_vehicle 节点在线（@change_status 话题）。
若当前环境无 rclpy，标题栏状态将显示「ROS 不可用」。

---
6. 交通灯控制
用途：批量控制交通灯设备灯态（UDP 到 目标IP:端口，1@ rt_message 灯态协议）。
- 配置：目标IP（默认 106.14.223.60）、端口 1234、发送间隔（默认 0.3s）。
- 设备SN列表：每行一个，改动后自动重建设备行。
- 红/绿/黄灯时长（秒）：默认红10 / 绿30 / 黄3，「应用配置」生效。
- 全局控制（所有设备）：全部绿灯 / 全部红灯 / 全部黄灯 / 全部关灯；「开始发送」按设定间隔持续广播（再点停止）。
- 计时模式：「开始计时」后，勾选了「参与计时」的设备按 红→绿→黄→红 循环自动切换（再点停止）。
- 设备列表：每行单灯独立控制（绿/红/黄/关 + 参与计时勾选）。
灯态与颜色：1=绿 2=红 3=关 4=黄。

---
7. 地图工具
用途：① ROS1 .bag 大小分析（统计各 topic 累计序列化字节）② .bin 地图 → .txt/.json。
7.1 配置
- planning_msgs 路径：地图转换需要 planning_msgs.map.map_pb2。默认指向 备份/脚本/pb2json
所在目录，可用「浏览」改为其它包含 planning_msgs 的目录。
7.2 Bag 大小分析
- 点「选择 Bag 文件并分析」，选 .bag 后统计每个 topic 的总序列化字节数与占比。
- 优先调用 rosbag；未安装时自动使用内置纯 Python 解析器，但仅支持未压缩 bag，
遇到 CHUNK（压缩）数据会提示改用 rosbag 环境。
7.3 地图格式转换
- 选择输出格式：txt / json / both。
- 点「选择 Map 文件并转换」选 .bin 文件，转换结果输出到同目录的 .txt / .json。
- 转换在后台线程执行，日志区显示进度与结果路径。

---
8. 仿真测试
用途：融合 auto_test.py（单案例）与 auto_51sim.py（批量）的自动化仿真测试，
并通过 cars_ros2 逻辑一键拉起 T01~T10 容器。
8.1 Docker 容器会话（T01~T10）
- 容器列表（空格分隔，默认 T01…T10）、镜像（默认 ros2_humble_image:v1）、镜像根目录
（默认 /home/boonray/robotruck/ros2）。
- 「启动全部容器会话」：逐个 docker run --privileged --rm --gpus all，注入 ROS_DOMAIN_ID，
挂载 install 与 launches，并 gnome-terminal 打开容器内 bash。
- 「停止全部容器会话」：逐个 docker stop。
- 容器名解析：T01 → 数字 1 作为 ROS_DOMAIN_ID 与 hostname。
8.2 单案例（auto_test）
参数：案例（默认 T01）、设备SN（fz_c01）、容器（fz1）、API Token（内置单案例 token）。
按钮
作用
完成全流程
打开窗口并启动容器 → 等待容器就绪 → 等待AD就绪 → 查看日志 → 发送任务 → 中断任务 → 继续任务
打开窗口并启动容器
仅拉起容器会话并打印窗口提示
等待容器就绪
轮询容器内可执行文件就绪（最长 90s）
等待AD就绪
容器内 ros2 node list 节点数 ≥5 视为 AD 就绪（最长 300s）
发送任务
调云端 arrange_task（API：mineapiprod.boonray.com/dispatch）
中断任务
调 break_task
继续任务
调 continue_task
清理容器
停止并移除容器
8.3 批量（auto_51sim）
- 案例目录（默认 /home/boonray/robotruck/ros2/auto_51sim）→「刷新案例数」：
优先找 case* 子目录，找不到则回退为全部子目录（实际案例多为 b01-1 此类命名）。
- 设备SN、Token（内置批量 token）。
- 自动确认：勾选后跳过所有"确认继续"等待；不勾选时工作线程会停在关键节点并激活
「确认继续 →」按钮，人工确认后继续（每次等待超时 1800s）。
- 流程：启动批量测试 → 逐案执行 启动容器→等AD就绪→发任务→等截止→扫描故障→收尾 →
全部完成后「生成报告」写 test_report.md（含案例数、通过/失败、业务故障、运行异常统计）。
- 过程中通过 /tmp/auto_51sim_guardian_*.sh 与容器通信（触发/完成文件，超时 30s）。
- 中途可「停止批量」（中断剩余案例）；完成后「清理容器」统一回收。
API 常量：项目ID 56955550355457，用户ID 56524522090689；
单案例/批量 token 过期时间不同（exp 1788664202 / 1790142525），如失效需替换界面上的 token 或更新常量。

---
9. NVIDIA Orin 烧录
用途：Orin 工控机整机镜像烧录（fusion main.py + auto_flash_orin.sh）。
9.1 镜像准备
- 镜像清单：ROS1_64_Before2026、ROS1_64_After2026、ROS2_Ubuntu22.04。
- 下载地址：https://ug.link/drivingcontrol，账号 boonray / 密码 Password1!；解压到 ~/robotruck。
- 进入页面自动扫描 ~/robotruck 下的镜像目录；点「刷新镜像列表」重新扫描。
- 选中镜像后下方显示 镜像路径 与 烧录模式（before2026 / after2026 / ros2），「开始烧录」才可用。
9.2 烧录流程（后台线程执行）
1. 配置 Python 环境 → 2. 检查设备（RECOVERY 模式/USB 连接）→ 3. 按模式选择 flash 步骤：
  - before2026：expect 驱动 sudo ./tztek_flash.sh（3000ms 发菜单键、6000ms 发 6、8000ms 发 yes）。
  - after2026 / ros2：先解压 dram/emmc 的 .tbz2、挂载 system.img.raw 到
Linux_for_Tegra/rootfs、停止 udisks2 服务，再执行 l4t_flash_prerequisites.sh 与
l4t_update_initrd.sh，最后 flash。
- 「停止烧录」终止当前 expect 进程；失败/停止后「开始烧录」按钮会被禁用，需重新检查设备。
9.3 注意事项
- 需要 expect 与 sudo 权限（脚本内按需提示密码）。
- 烧录期间不要断电、不要拔 USB 线。
- 完成后提示后续步骤：1. 等待工控机重启 2. 升级内核 3. ROS2 配置 SN 和设备名
4. 检查网口 IP 5. 重启。

---
10. 网络工具
用途：为入口 UDP 流量注入模拟延迟（network.sh），并一键清理恢复（network1.sh）。
- 配置：网卡（默认 eno2np1）、入口延迟 ms（默认 5000）。
- 注入延迟：自动执行
modprobe ifb → 网卡挂 ingress qdisc → u32 匹配 UDP(协议17) 重定向到 ifb0 →
ifb0 上 netem delay Xms。
- 清理恢复：删除网卡 ingress 过滤器与 ifb0 的 qdisc，down 掉 ifb0。
- 每一步命令与返回码显示在日志区。
需要 sudo 权限；非 root 启动时命令会提示输入 sudo 密码。

---
11. 云平台工具
用途：融合 CloudPlantProject —— UDP 灯态上报、MQTT 故障发布与 YAML 回放、TCP 收发。
11.1 UDP 灯态上报（1@ rt_message）
- 目标IP（默认 106.14.223.60）、端口 1234、SN（默认 psz_light）、灯态（1=绿 2=红 3=关 4=黄）。
- 持续时长（秒，0=只发一次）、发送间隔（秒）。
- 「发送一次」立即发一条；「持续发送」按间隔循环，可设时长自动结束，或「停止」手动停止。
11.2 MQTT（paho-mqtt）
- 默认：host 106.14.223.60:1883、client_id mock_tools_mqtt、username ds、
password 为云端 token（已内置，可编辑替换）、keepalive 60。
- 主题默认 report/55722339745601/robotruck_mock_truck/fault。
- 编辑器内填 JSON payload（示例已预填 faults / timestamp:@time 自动替换 / in_task）。
- 「连接」后用「发布」发送；「断开」释放连接。
- YAML 回放：下拉框来自 CloudPlantProject/yaml_data/（*.yaml），可「浏览…」选自定义文件
（回放时逐条连接并发布该 topic 的 MQTT 消息）。需先连接 MQTT 再点「连接后回放」。
11.3 TCP（json\n 行协议）
- 默认 host 106.14.223.60:5555；「订阅topic」留空则接收全部，非空则过滤。
- 发送：主题（默认 command/56955550355457/fz_c01/request/start_task）+ payload JSON →「发送」。
- 收到消息实时显示在日志区（TCP 状态以右上「未连接/已连接」区分）。
MQTT 需要 paho-mqtt；本页所有默认凭据均可直接编辑以对接不同环境。

---
12. 目标点更新
用途：在容器内跑一个 rclpy 节点，把车辆上报的目标点整体平移指定偏移后重新发布。
- 运行配置：容器（默认 fz1，需已运行且内部装有 /opt/ros/humble）。
- 节点行为：订阅 /guardian/dump_goal（也可在脚本常量中调整），收到后对目标点纵坐标
平移输入偏移，发布到 /perception/new_dump_goal；支持循环持续输入偏移。
- 操作：
  1. 确认容器 fz1 已运行；
  2. 「启动监听节点」——自动把内置脚本写入宿主机 /tmp/update_new_goal_host.py 并
docker cp 到容器 /tmp/update_new_goal.py，再 docker exec 启动（已 source
/opt/ros/humble/setup.bash 与 /home/boonray/install/setup.bash）；
  3. 在「目标点偏移控制」输入纵向偏移（米，往后负 / 往前正，默认 6）→「发送偏移」，
或点快捷按钮 -6 / -1 / +1 / +6；
  4. 「停止节点」结束进程。
- 日志区显示节点输出；进程退出自动恢复按钮状态。

---
13. 常见问题（FAQ）
现象
处理
双击运行无窗口 / 报 DISPLAY 错误
需在桌面图形会话中运行，勿用普通 SSH 终端
云平台 MQTT 连接失败
pip install paho-mqtt；检查 host/port 与 密码 token 是否过期
仿真测试 API 401
界面上的 Token 过期，替换为最新 token（或更新 SIM_API_TOKEN/SIM_BATCH_TOKEN）
容器启动报 no GPU / gpus all 失败
确认宿主已装 NVIDIA 驱动，或移除 --gpus all 改 CPU（会影响基于 GPU 的仿真）
目标点更新提示"容器未运行"
先 docker ps 确认 fz1 存在并处于 up 状态
地图转换报 "缺少 map_pb2"
确认 planning_msgs 路径指向含 map_pb2.py 的目录，或改用 pb2json 目录
bag 分析报"不支持压缩"
该 bag 为压缩格式，需在装有 rosbag 的环境分析
故障模拟显示 ROS 不可用
本机需可用 rclpy 且 mock_vehicle 节点在线
Orin 烧录按钮置灰
未选中有效镜像，或上次烧录失败被禁用；先「刷新镜像列表」并重新检查设备
网络工具命令返回非 0
权限不足，以能 sudo 的方式运行工具
