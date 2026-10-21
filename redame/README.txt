"""
版权所有：上海伯镭科技有限公司
@File    :  README.txt
@Time    :  2026/08/28
@Author  :  Fox
@Version :  v3.5
@Desc    :  Mock Truck 管理工具 - 项目说明文档（解耦版）

            代码结构：
            1. 项目简介
            2. 文件结构（解耦架构）
            3. 依赖安装
            4. 配置说明
            5. 启动服务
            6. 常见问题
            7. 日志文件说明
            8. 解耦开发规范
"""
================================================================================
                   Mock Truck 管理工具 - 项目说明（解耦版）
================================================================================

项目简介
---------
本工具提供基于 Web 的 ROS2 仿真车辆管理与 Docker 容器管理界面。
采用前后端分离架构，后端使用 FastAPI + WebSocket，前端为独立静态文件。
所有功能均通过 REST API 和 WebSocket 与后端交互。

版本: v3.5
更新日期: 2026-08-28

v4.0-decoupled 主要更新：
  🏗️ 架构解耦
    - 后端完全模块化：core / database / services / routers 四层分离
    - 配置管理独立为 core/config.py，支持热加载
    - 日志管理独立为 logger.py，统一配置
    - 安全工具独立为 core/security.py，JWT/密码/速率限制集中管理
    - 数据库适配器独立为 database/（json_db.py + supabase_db.py）
    - 业务服务独立为 services/（DockerManager / ROS2ScriptGenerator / SystemMonitor 等）
    - 路由统一使用 FastAPI APIRouter，可按领域进一步拆分
    - app.py 仅保留入口职责（< 200 行）
  🚀 部署优化
    - deploy.py 支持 --skip-system / --skip-deps / --only-deps 参数
    - Python 依赖批量检查、一次性安装缺失包，速度提升
    - systemd 服务配置内容比对，避免无意义重写
    - 已安装环境自动跳过，不再重复下载
  ✨ 功能保留
    - 所有 v3.6 功能完整保留，API 兼容
    - 数据库初始化脚本不变
    - 前端资源不变
  📦 数据导出（新增）
    - 新增「数据导出」面板：提取地图（hdmap）、录制 ROS2 Bag（mcap格式）、Web 下载
    - 独立文件实现：services/data_export_service.py + routers/data_export.py + js/panels/data_export.js
    - 通过 MutationObserver 向容器列表动态注入按钮，不修改原有代码
    - 用户隔离：bag/hdmap 文件仅落地到当前用户空间（~/robotruck_ros2/<user>/Docker/bags/）
    - 专用下载接口 GET /api/data-export/bag/download，权限 data-export

v4.0.1 部署适配（2026-08-26）：
  🚀 deploy.py 一键部署跨服务器适配
    - 用户名全自动获取：SUDO_USER > LOGNAME/USER/USERNAME 环境变量 > getpass 兜底，
      适配所有服务器（含 systemd / cron / ssh 无 tty 环境），无需修改任何脚本内容
    - 自动加入 docker 组：部署时自动检测并 usermod -aG docker <用户>，
      已在组中自动跳过，加入后提示需重新登录生效
    - 非 root 运行时友好提示：提示使用 sudo 重新执行（sudo 会提示输入当前用户密码），
      并支持选择由脚本自动以 sudo 重新拉起自身
    - systemd 服务以实际执行用户身份运行，用户家目录 / Python 路径 / 项目路径全部自动推导

v3.5 容器管理与性能优化（2026-08-28）：
  🐛 缺陷修复
    - 管理员 Docker 管理面板看不到用户的 ROS2 容器
      根因：前端"ROS2容器"按钮按镜像名过滤（filter_image=ros2_），而用户容器镜像
      显示为未打标签的镜像 ID（如 88fc0f0bc583），不含"ros2_"字符串，全部被过滤。
      修复：改按容器名前缀过滤（filter_name=ros2_），后端返回 is_ros2 标志供前端判断。
      同步修正"其他容器"按钮排除逻辑（!ros2_ 按名称排除，而非按镜像排除）。
    - 删除 install 时未同步清空 Docker 目录
      根因：/api/install/delete 仅 move install 目录到备份，残留 bags/rosbag、
      logs/容器日志、scripts/启动脚本、bk/生成的 .yaml/.py/.sh、.bk_backups 历史备份。
      修复：新增 _cleanup_user_docker_dir()，删除时同步清理：
        · bags/logs/scripts 清空内容（保留目录）
        · bk 递归删 .yaml/.yml/.py/.sh，保留 start_docker_template.sh / .pem / .rviz
        · .bk_backups 整体删除
        · Docker 根目录杂项（log.zip 等）清理，仅保留 bags/bk/logs/scripts 四个标准目录
  ⚡ 性能优化（8 并发请求总耗时 1.90s → 0.65s）
    - 高频只读端点 async def → def：FastAPI 自动放入线程池执行，
      docker 子进程 / nvidia-smi / psutil / 目录扫描不再阻塞事件循环。
      涉及端点：system_status / system_monitor / list_images / list_containers /
      get_install_status / list_scripts / get_default_paths / get_quota_status /
      traffic_status / get_light_status / list_truck_configs / get_truck_config
    - Supabase 查询加 TTL 内存缓存：get_user 30s、get_visible_container_names 10s；
      update_user / delete_user / update_user_role / register_container /
      remove_container_record 主动失效缓存
    - 容器列表接口合并 2 次 docker ps 子进程为 1 次（list_containers_detailed）
  🎨 UI 优化
    - 容器列表去除"镜像"列（名称/状态/运行时长/云平台连接/操作 共5列）
    - 名称/状态/运行时长/云平台连接 4 列等宽自适应，操作列按按钮内容自适应
    - 操作按钮过多自动换行到第二排，按钮配色改用渐变 + 阴影美化

================================================================================
                          解耦架构说明
================================================================================

后端目录结构（解耦后）：

~/ros2_web/backend/
├── app.py                  # 入口文件（仅：创建App、注册中间件、挂载路由、静态文件）
├── config.json             # 运行时配置文件
├── logger.py               # 日志管理模块（统一格式、级别、输出目标）
├── deps.py                 # FastAPI 依赖注入（get_current_user / require_admin / require_permission）
├── models.py               # Pydantic 请求模型（LoginRequest / RegisterRequest）
├── core/                   # 核心基础设施层
│   ├── config.py           # 配置加载/保存/默认值管理
│   ├── constants.py        # 全局常量（从 config.json 衍生，统一管理）
│   ├── security.py         # JWT/密码哈希/命令过滤/速率限制
│   ├── middleware.py       # 安全头中间件 + 无缓存中间件
│   ├── cache.py            # SimpleCache 内存缓存
│   ├── utils.py            # 通用工具函数（ros2命令执行、目录树、路径处理等）
│   └── workspace.py        # 用户工作空间管理（路径验证、创建、初始化）
├── database/               # 数据访问层
│   ├── __init__.py         # 数据库工厂（init_database）
│   ├── json_db.py          # JSON 文件数据库实现
│   └── supabase_db.py      # Supabase 数据库实现
├── services/               # 业务逻辑层
│   ├── docker_manager.py   # Docker 容器管理（DockerManager 类）
│   ├── script_generator.py # ROS2 脚本生成器（ROS2ScriptGenerator 类）
│   ├── system_monitor.py   # 系统监控（SystemMonitor 类）
│   ├── system_utils.py     # 系统工具（SystemUtils 类）
│   ├── traffic_light.py    # 红绿灯模拟器（TrafficLightSender / TimerTrafficLightSender）
│   └── data_export_service.py # 数据导出服务（DataExportService：hdmap提取 + ros2 bag录制）
└── routers/                # 接口层（路由定义）
    ├── api.py              # 统一路由入口（包含通用路由，挂载子路由）
    ├── data_export.py      # 数据导出路由（hdmap提取 + ros2 bag录制 + 下载）
    └── __init__.py         # 包标识

前端目录结构（不变）：

~/ros2_web/frontend/
├── index.html              # 主页面
├── css/
│   └── sj_style.css        # 全局样式
└── js/
    ├── sj_script.js        # 前端业务逻辑
    ├── sj_validators.js    # 前端注册校验逻辑
    └── panels/             # 面板模块（按功能拆分，通过 MutationObserver 注入）
        ├── terminal.js     # 终端面板模块
        └── data_export.js  # 数据导出模块（提取地图/录制Bag/下载Bags）

其他目录（不变）：

~/ros2_web/
├── ui/
│   └── favicon.ico         # 网站图标
├── data/                   # 数据目录
│   ├── data.json
│   ├── audit_logs.json
│   ├── foxglove_layout.json
│   └── ros2_web_supabase.sql
├── log/                    # 日志目录
├── redame/                 # 文档与部署脚本
│   ├── README.txt          # 本文件
│   ├── requirements.txt    # Python 依赖清单
│   └── download_deps.sh    # 离线依赖下载脚本
└── deploy.py               # 一键部署脚本

================================================================================
                          依赖安装
================================================================================

在 Ubuntu 20.04/22.04 上，首先安装 Python 3.8+ 和 pip：
    sudo apt update
    sudo apt install python3 python3-pip

安装 Python 依赖（依赖清单位于 redame/ 目录）：
    pip3 install -r ~/ros2_web/redame/requirements.txt

国内加速下载：
    pip3 install -r ~/ros2_web/redame/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

确保 Docker 服务已安装并运行，且当前用户有权限执行 docker 命令：
    sudo usermod -aG docker $USER
    # 重新登录后生效

================================================================================
                          配置说明
================================================================================

配置文件: ~/ros2_web/backend/config.json

1. 服务器配置
   - host: 监听地址（默认 0.0.0.0）
   - port: 监听端口（默认 8875）

2. 安全配置
   - jwt_secret: JWT 密钥（必须修改为随机字符串！）
   - jwt_expire_minutes: Token 过期时间（默认 1440 分钟）
   - audit_enabled: 审计日志开关（默认 true）

3. 数据库配置
   - type: json / supabase
   - path: 数据文件路径（JSON 模式下默认 ~/ros2_web/data/data.json）
   - audit_path: 审计日志 JSON 路径（JSON 模式下使用）
   - url / key / service_role_key: Supabase 模式下的连接信息

   登录认证逻辑：
   - Supabase 模式下，用户名/邮箱及其 bcrypt 密码哈希存储在 public.users 表中。
   - 登录时优先使用 public.users 表的 password 字段进行本地验证。
   - 首次启动若不存在管理员账户，会自动创建默认管理员 admin / Boonray2020!。

   审计日志：
   - 用户登录、登出、容器操作、脚本执行等所有审计事件写入 public.audit_logs 表。
   - 同时镜像一份到本地 log/audit.log，方便离线排查。

   容器权限隔离：
   - 容器启动时在 public.containers 表中记录 created_by（用户 ID）。
   - 普通用户仅可见/操作自己启动的容器；管理员可看全部。
   - 未记录归属的旧容器默认放行，避免误拦。

4. CORS 配置
   - allow_origins: 明确允许的来源列表
   - allow_origin_regex: 允许来源正则

5. Docker 配置
   - default_image: 默认 Docker 镜像
   - use_sudo: 是否使用 sudo（建议 false）

6. 云环境配置 (cloud_env)
   - current_env: 当前环境标识（"106" / "139" / "192"）
   - current_ip: 当前云平台 IP
   - ip_map: 环境标识到 IP 的映射
   - 切换环境时 current_env 和 current_ip 会自动更新并持久化到 config.json

7. 可视化配置
   - default_method: 默认可视化方案（foxglove/vnc/rvizweb/rviz_x11）
   - order: 可视化方案显示顺序
   - methods: 各可视化方法配置
     * foxglove - Foxglove Studio 云端可视化
       - enabled: 是否启用
       - port: rosbridge_server 端口（默认 9091）
       - container_port: 容器内端口（默认 9090）
       - auto_install: 是否自动安装依赖
     * vnc - VNC 远程桌面
       - enabled: 是否启用
       - port: VNC 端口（默认 5903）
       - container_port: 容器内端口（默认 5901）
       - web_port: Web VNC 端口（默认 6080）
       - password: VNC 密码（默认 ros2vnc）
       - auto_install: 是否自动安装依赖
     * rvizweb - Web 版 RVIZ
       - enabled: 是否启用
       - port: 服务端口（默认 8082）
       - container_port: 容器内端口（默认 8080）
       - auto_install: 是否自动安装依赖
     * rviz_x11 - 原生 RVIZ（不推荐）
       - enabled: 是否启用（默认 false）
       - require_gpu: 是否需要 GPU

8. 端口配置方案
   - 基础端口（domain_id=0）:
     * Foxglove/rosbridge: 宿主机 9091 → 容器 9090
     * VNC: 宿主机 5903 → 容器 5901
     * VNC Web: 宿主机 6080 → 容器 6080
     * rvizweb: 宿主机 8082 → 容器 8080
   - 端口偏移规则: host_port = base_port + domain_id * 10
   - 每个脚本根据其 domain_id 自动分配唯一端口，避免冲突

容器端口映射要求：
   启动 ROS2 容器时建议映射以下端口：
   - 9091:9090   (Foxglove Studio / rosbridge_server)
   - 5903:5901   (VNC 远程桌面)
   - 6080:6080   (Web VNC)
   - 8082:8080   (rvizweb)

示例：
   docker run -d \
     -p 9091:9090 \
     -p 5903:5901 \
     -p 6080:6080 \
     -p 8082:8080 \
     --name ros2_container \
     ros2_humble_image:v1

================================================================================
                          启动服务
================================================================================

手动启动（推荐）：
    cd ~/ros2_web/backend && python3 app.py

使用 uvicorn 启动：
    cd ~/ros2_web/backend
    uvicorn app:app --host 0.0.0.0 --port 8875 > ~/ros2_web/log/app.log 2>&1 &

强制重启（清除占用端口）：
    fuser -k 8875/tcp 2>/dev/null || true
    sleep 2
    cd ~/ros2_web/backend
    uvicorn app:app --host 0.0.0.0 --port 8875 > ~/ros2_web/log/app.log 2>&1 &

访问地址：
    http://<服务器IP>:8875

默认管理员账户：
    用户名: admin
    密码: Boonray2020!

说明：
    - JSON 模式：默认管理员写入 ~/ros2_web/data/data.json。
    - Supabase 模式：首次启动时会在 public.users 表中自动创建/修复 admin 记录，
      密码以 bcrypt 哈希形式保存在 public.users.password 字段。

首次登录后请尽快修改默认密码。

================================================================================
                          一键部署
================================================================================

使用 deploy.py 一键部署（需要 root / sudo）：

    cd ~/ros2_web
    sudo python3 deploy.py

部署脚本已适配所有服务器，无需按机器修改任何内容：
    - 用户名自动获取：优先读取 SUDO_USER（sudo 执行时的真实用户），
      其次 LOGNAME / USER / USERNAME 环境变量，最后 getpass 兜底；
      兼容 systemd / cron / ssh 无控制终端环境
    - 自动加入 docker 组：部署时自动检测执行用户是否在 docker 组，
      未入组则自动执行 usermod -aG docker <用户>；已入组自动跳过
    - 非 root 运行时的提示：直接执行 python3 deploy.py 会提示
      "请使用 sudo 重新执行（sudo 将提示输入当前用户密码）"，
      并可选择由脚本自动以 sudo 重新拉起自身，无需手动重敲命令
    - 路径全自动推导：项目目录 / 用户家目录 / Python 解释器路径均自动获取，
      换服务器、换用户名均可直接使用

注意：
    - docker 组权限加入后需注销并重新登录（或执行 newgrp docker）才生效
    - 部署报告中的默认账号为 admin / Boonray2020!，首次登录后请立即修改

参数说明：
    --skip-system    跳过系统环境检查与安装（Python/Docker/Git），仅部署应用
    --skip-deps      跳过 Python 依赖安装
    --only-deps      仅安装 Python 依赖，跳过系统服务部署（免 sudo）

示例：
    # 全新部署
    sudo python3 deploy.py

    # 系统环境已就绪，仅部署应用和依赖
    sudo python3 deploy.py --skip-system

    # 仅更新 Python 依赖
    sudo python3 deploy.py --skip-system --only-deps

================================================================================
                  部署平台支持与跨环境复用说明
================================================================================

【操作系统支持情况】

  ✅ Ubuntu 20.04 / 22.04 / 24.04（推荐，原生支持）
     - deploy.py 使用 apt 安装 Python / Docker / Git
     - 使用 systemd 配置开机自启服务
     - 全流程一键完成

  ⚠️ 其他 Linux 发行版（CentOS / Debian / Rocky 等）
     - Python 依赖安装、应用启动可正常使用
     - 系统级软件安装（apt 命令）需手动改为对应包管理器（yum / dnf）
     - systemd 服务配置通用，可正常使用
     - 建议使用 --skip-system 跳过系统环境安装，手动准备 Python3/Docker/Git

  ❌ Windows（不支持自动部署）
     - deploy.py 依赖 apt / systemctl / usermod 等 Linux 专属命令，无法直接运行
     - systemd 不存在于 Windows，无法配置开机自启服务
     - 如需在 Windows 上运行，请按以下步骤手动部署：
       1) 安装 Python 3.8+（https://www.python.org/downloads/）
       2) 安装 Docker Desktop（https://www.docker.com/products/docker-desktop/）
       3) 安装 Git（https://git-scm.com/download/win）
       4) 执行依赖安装：
            pip install -r redame\requirements.txt
       5) 启动服务（不配置开机自启）：
            cd backend
            python app.py
       6) 访问 http://127.0.0.1:8875
     - Windows 下推荐使用任务计划程序或 NSSM 替代 systemd 实现开机自启

【跨用户复用说明】

  deploy.py 已支持跨用户部署，无需修改脚本即可在不同用户下使用：

  - 用户名自动识别：SUDO_USER > LOGNAME/USER/USERNAME > getpass 兜底，
    兼容 systemd / cron / ssh 无 tty 环境（不使用依赖控制终端的 os.getlogin()）
  - 项目路径自动识别：基于脚本所在目录推导，无需硬编码
  - HOME 目录自动推导：systemd 服务文件中 PATH 包含 ~/.local/bin
  - Python 解释器自动定位：使用 shutil.which("python3") 查找
  - docker 组自动配置：未入组自动 usermod -aG docker 加入，已入组跳过

  在新用户下部署只需：
    # 1. 切换到目标用户
    su - <目标用户>

    # 2. 拷贝项目到目标用户家目录
    cp -r /home/fox/ros2_web ~/

    # 3. 修改项目归属
    chown -R <目标用户>:<目标用户> ~/ros2_web

    # 4. 执行部署（需 sudo 权限；忘记加 sudo 时脚本会提示并可直接确认自动重跑）
    cd ~/ros2_web
    sudo python3 deploy.py

  部署完成后，systemd 服务将以目标用户身份运行，
  日志目录、数据目录归属也会自动正确。

【跨服务器复用说明】

  将项目迁移到新服务器时，需注意以下事项：

  1. 环境前置条件：
     - Ubuntu 20.04+（推荐）/ 其他 Linux（需手动准备环境）
     - root 或 sudo 权限账号
     - 可访问外网（用于 pip / apt 安装）或准备离线依赖包

  2. 迁移步骤：
     # 打包源项目（在原服务器执行）
     cd ~
     tar -czf ros2_web.tar.gz \
       --exclude='ros2_web/log/*' \
       --exclude='ros2_web/data/*.json' \
       --exclude='ros2_web/__pycache__' \
       --exclude='ros2_web/backend/__pycache__' \
       ros2_web/

     # 传输到新服务器
     scp ros2_web.tar.gz <新服务器IP>:~/

     # 在新服务器解压并部署
     ssh <新服务器IP>
     tar -xzf ros2_web.tar.gz
     cd ros2_web
     sudo python3 deploy.py

  3. 部署后必做配置：
     - 修改 backend/config.json 中的 jwt_secret（务必更换为随机字符串！）
     - 检查并修改 cloud_env.current_ip / current_env（如云环境不同）
     - 如使用 Supabase，确认 url / key 配置正确
     - 修改默认管理员密码（首次登录后立即修改）
     - 检查端口 8875 是否被占用：ss -tlnp | grep 8875

  4. 离线环境部署：
     - 在联网机器上执行 redame/download_deps.sh 生成离线包
     - 将 ros2_offline_packages/ 和项目一起拷贝到目标服务器
     - 安装依赖：pip3 install --no-index --find-links=./packages -r redame/requirements.txt
     - 系统软件（Python/Docker/Git）需在目标服务器提前手动安装

  5. Docker 镜像迁移：
     - ROS2 仿真依赖的 Docker 镜像需单独迁移
     - 导出：docker save -o ros2_image.tar <镜像名:标签>
     - 传输：scp ros2_image.tar <新服务器>:~/
     - 导入：docker load -i ros2_image.tar

================================================================================
                          开机自启（systemd）
================================================================================

如需手动配置开机自启，可创建 systemd 服务：

1. 创建服务文件：
   sudo tee /etc/systemd/system/ros2_web.service > /dev/null << 'EOF'
   [Unit]
   Description=Mock Truck Service (Decoupled)
   After=network.target docker.service
   Requires=docker.service

   [Service]
   Type=simple
   User=fox
   WorkingDirectory=/home/fox/ros2_web/backend
   ExecStart=/home/fox/.local/bin/uvicorn app:app --host 0.0.0.0 --port 8875
   Restart=always
   RestartSec=10
   StandardOutput=journal
   StandardError=journal
   Environment="PATH=/usr/bin:/usr/local/bin"
   Environment="ROS_DOMAIN_ID=0"
   Environment="RMW_IMPLEMENTATION=rmw_fastrtps_cpp"
   Environment="PYTHONPATH=/home/fox/ros2_web/backend"

   [Install]
   WantedBy=multi-user.target
   EOF

2. 启用并启动服务：
   sudo systemctl daemon-reload
   sudo systemctl enable ros2_web
   sudo systemctl start ros2_web

3. 查看状态与日志：
   sudo systemctl status ros2_web
   sudo journalctl -u ros2_web -f

================================================================================
                          Supabase 数据库初始化
================================================================================

数据库初始化脚本（整合版，包含全部5张表）：
    ~/ros2_web/data/ros2_web_supabase.sql

包含的表：
    - public.users           - 用户表（含 password / permissions 字段）
    - public.audit_logs      - 审计日志表（用户登录、容器操作等）
    - public.containers      - 容器归属表（created_by 字段用于权限隔离）
    - public.tickets         - 工单表（问题反馈/需求）
    - public.ticket_replies  - 工单回复表

初始化方法：
    在 Supabase 控制台 SQL Editor 中执行 ~/ros2_web/data/ros2_web_supabase.sql
    脚本幂等，可重复执行。

================================================================================
                          日志文件说明
================================================================================

后端日志文件：
   - ~/ros2_web/log/app.log          - 后端应用日志（DEBUG级别）
   - ~/ros2_web/log/audit.log        - 审计日志镜像（INFO级别，同时写入 Supabase public.audit_logs）
   - ~/ros2_web/log/audit_debug.log  - 调试审计日志（DEBUG级别）

Supabase 数据库表：
   - public.users           - 用户表
   - public.audit_logs      - 审计日志表
   - public.containers      - 容器归属表
   - public.tickets         - 工单表
   - public.ticket_replies  - 工单回复表

前端日志文件：
   - ~/ros2_web/log/index_html.log   - 前端页面日志
   - ~/ros2_web/log/sj_js.log        - 前端JS日志
   - ~/ros2_web/log/sj_css.log       - 前端CSS日志

容器日志文件：
   - ~/robotruck_ros2/Docker/logs/*.log - ROS2 节点日志

系统日志：
   - journalctl -u ros2_web          - systemd 服务日志

日志分析建议：
   - 启动失败：查看 app.log 和 audit.log
   - 容器问题：查看容器日志目录和系统日志
   - 可视化问题：查看容器日志和端口映射
   - 红绿灯问题：查看 app.log 中 [Traffic] 前缀的日志

================================================================================
                          解耦开发规范
================================================================================

后续所有开发必须遵循以下规范，保持解耦架构：

1. 新增功能先在 services/ 实现业务逻辑
   - 禁止在 routers/ 中写复杂业务逻辑
   - routers/ 只负责：接收请求 -> 调用 service -> 返回响应

2. 在 routers/ 按领域新建或补充路由文件
   - 当前所有路由在 routers/api.py（过渡方案）
   - 后续应按领域拆分为：auth.py, admin.py, system.py, docker.py, ros2.py 等
   - 每个路由文件使用 FastAPI APIRouter
   - 在 app.py 中通过 app.include_router() 统一挂载

3. 公共工具放入 core/
   - 通用函数、常量、安全配置、中间件放入 core/
   - 禁止在各模块间直接复制工具函数

4. 禁止在 app.py 直接写业务代码
   - app.py 仅保留：FastAPI 创建、中间件注册、路由挂载、静态文件、启动入口
   - 目标行数：< 200 行

5. 数据库访问统一通过 database/
   - 禁止在 routers/services 中直接操作 JSON 文件或 Supabase 客户端
   - 统一使用 database/__init__.py 中导出的 db 对象

6. 日志统一使用 logger.py
   - 禁止在各模块中自行配置 logging
   - 统一使用 from logger import logger

================================================================================
                          常见问题
================================================================================

Q: 首次启动后如何登录？
A: 使用默认管理员账号 admin / Boonray2020! 登录。

Q: 如何修改默认管理员密码？
A: 登录后可在系统设置中修改。

Q: 普通用户为什么看不到某些菜单？
A: 需要管理员在【系统设置 → 用户管理】中为其分配对应页面权限。

Q: WebSocket 连接失败？
A: 请确保在 WebSocket URL 中携带了有效的 token 参数。

Q: ROS2 话题/节点/服务/Action 无法加载？
A: 请先在 Docker 管理面板中选中一个运行中的 ROS2 容器。

Q: 启动仿真车失败？
A: 可能是端口冲突，检查 docker ps 和 ss -tlnp 查看端口占用情况。

Q: 日志文件为空？
A: 确保日志目录存在且有写入权限：
   mkdir -p ~/ros2_web/log && chmod 755 ~/ros2_web/log

Q: 如何生成离线依赖包？
A: 执行 ~/ros2_web/redame/download_deps.sh，会在 ~/ros2_offline_packages/ 生成离线包。
   离线安装：pip3 install --no-index --find-links=./packages -r requirements.txt

Q: deploy.py 为什么要 sudo？
A: 因为需要安装系统级软件、写入 systemd 服务文件、配置 Docker 组权限。
   使用 --skip-system --only-deps 可免 sudo 仅安装 Python 依赖。

Q: 忘记加 sudo 直接运行 python3 deploy.py 会怎样？
A: 脚本不会直接报错退出，而是提示"请使用 sudo 重新执行（sudo 将提示
   输入当前用户密码）"，并询问是否由脚本自动以 sudo 重新拉起自身，
   输入 y 确认后 sudo 会提示输入密码并继续部署，无需手动重敲命令。

Q: 换了一台服务器 / 换了用户名，deploy.py 需要改哪里？
A: 什么都不用改。脚本自动获取真实执行用户（SUDO_USER / LOGNAME / USER
   环境变量 + getpass 兜底），自动推导项目路径、家目录与 Python 路径，
   自动检测并加入 docker 组，任何服务器直接 sudo python3 deploy.py 即可。

================================================================================
                          技术架构
================================================================================

后端技术栈：
    - FastAPI: Web 框架
    - Uvicorn: ASGI 服务器
    - WebSockets: 实时通信
    - JWT: 认证授权
    - bcrypt: 密码哈希
    - Docker SDK: 容器管理
    - psutil: 系统监控
    - paho-mqtt: MQTT 客户端（红绿灯模拟器）
    - requests: HTTP 请求（红绿灯模拟器登录）
    - Supabase: 云数据库（用户/审计/容器/工单）

前端技术栈：
    - 原生 JavaScript (ES6)
    - CSS 变量 (主题切换)
    - xterm.js: 终端模拟器
    - Fetch API: HTTP 请求
    - WebSocket API: 实时通信

================================================================================
                          技术支持
================================================================================

© Boonray 伯镭科技
版本: v3.5
日期: 2026-08-28
作者: Fox

================================================================================
