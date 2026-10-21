# Mock Truck Web 开发文档

> **版权所有**：上海伯镭科技有限公司
> **版本**：v5.0
> **更新日期**：2026-09-26
> **作者**：Fox
> **范围**：Mock Truck 管理工具全量代码逻辑说明，覆盖前后端架构、模块职责、关键流程、API 清单、配置体系与部署流程

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [后端代码详解](#3-后端代码详解)
4. [前端代码详解](#4-前端代码详解)
5. [数据流与关键业务流程](#5-数据流与关键业务流程)
6. [API 接口全量清单](#6-api-接口全量清单)
7. [配置体系](#7-配置体系)
8. [安全机制](#8-安全机制)
9. [部署与运维](#9-部署与运维)
10. [文件结构与索引](#10-文件结构与索引)

---

## 1. 项目概述

Mock Truck 是一个基于 Web 的 **ROS2 仿真车辆管理 + Docker 容器管理** 平台，采用前后端分离架构：

- **后端**：FastAPI + WebSocket + Docker SDK + Supabase/JSON 双数据库
- **前端**：原生 HTML/CSS/JS（无构建工具）+ Service Worker 加速
- **部署**：systemd 服务 + 一键 deploy.py 脚本
- **端口**：8875（HTTP）

### 1.1 核心能力

| 模块 | 能力 |
|------|------|
| 认证 | JWT 登录、注册、角色权限、面板权限矩阵 |
| Docker 管理 | 容器列表/启停/删除/重命名/资源更新/镜像管理/批量停止 |
| ROS2 仿真 | 话题/节点/服务/Action 查询与控制、仿真启停 |
| 脚本管理 | ROS2 启动脚本生成、编辑、批量执行、配额控制 |
| 文件管理 | install 目录上传/删除/部署/回滚、bk 备份管理、**install 多版本管理与切换（v5.0）** |
| 系统监控 | CPU/内存/GPU/进程实时监控、远程主机探测 |
| 红绿灯模拟 | MQTT 接收 + UDP 上报双通道、定时模式 |
| 终端 | xterm.js WebSocket 终端（按需加载） |
| 数据导出 | hdmap 提取、ros2 bag 录制（mcap）、Web 下载 |
| 工单系统 | 工单创建/列表/回复/附件 |
| 故障注入 | ROS2 节点 kill / topic kill / fault 列表 |
| 可视化 | Foxglove / VNC / RVIZ X11 三种方案 |

### 1.2 版本演进

- **v3.5**：容器列表性能优化、UI 重构、用户隔离
- **v4.0-decoupled**：后端四层解耦（core/database/services/routers）
- **v4.0.1**：deploy.py 跨用户/跨服务器适配
- **v4.0.2**：新增数据导出模块、容器列表布局优化、文档清理
- **v5.0**（当前）：**install 目录多版本管理**——上传压缩包按顶层目录名归档为 `<工作空间>/<版本>/install/`，首页可切换版本，所有 ROS2/Docker/脚本操作在所选版本下生效；用户表新增 `current_version` 字段，兼容旧版 `install` 路径自动回退

---

## 2. 整体架构

### 2.1 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器（前端 SPA）                     │
│  index.html + sj_script.js + panels/* + sw.js           │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP REST + WebSocket (Bearer JWT)
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI 应用 (app.py)                   │
│  中间件链：GZip → CORS → SecurityHeaders → NoCacheStatic │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    routers/ (路由层)                     │
│  api.py（主路由 ~150 个端点）+ data_export.py            │
└──────────────────────┬──────────────────────────────────┘
                       │ Depends(get_current_user / require_admin / require_permission)
┌──────────────────────▼──────────────────────────────────┐
│                  services/ (业务层)                      │
│  DockerManager / ROS2ScriptGenerator / SystemMonitor    │
│  SystemUtils / TrafficLightSender / DataExportService   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│        core/ + database/ (基础设施层)                    │
│  config / constants / security / workspace / cache      │
│  middleware / utils / json_db / supabase_db             │
└─────────────────────────────────────────────────────────┘
```

### 2.2 解耦开发规范

1. **业务逻辑放 services/**：禁止在 `app.py` 或 `routers/` 写业务代码
2. **routers/ 仅做参数校验 + 调用 service + 返回响应**
3. **公共工具放 core/**：配置、日志、安全、缓存、中间件
4. **新增功能优先追加新文件**，不修改既有代码（参考 `data_export` 实现）

### 2.3 数据库适配器模式

`backend/database/__init__.py` 根据 `config.json` 的 `database.type` 自动选择：

- `supabase`（生产推荐）：`SupabaseDatabase`，使用 Supabase 公共数据库
- `json`（本地开发）：`JsonDatabase`，使用本地 JSON 文件

两者实现相同接口（`get_user` / `create_user` / `verify_login` / `add_audit_log` / 工单 CRUD 等），上层代码无感知。

---

## 3. 后端代码详解

### 3.1 入口文件 `backend/app.py`

**职责**：FastAPI 应用创建、中间件注册、路由挂载、静态文件服务、SPA 前端回退

**关键流程**：
1. 创建 `FastAPI(title="Mock Truck API", version="3.2-decoupled")`
2. 注册全局异常处理器（`Exception` + `HTTPException`）
3. 注册中间件链（顺序敏感，后注册先执行）：
   - `GZipMiddleware`（响应压缩，>1000 字节）
   - `CORSMiddleware`（跨域，从 `core/constants.py` 读取白名单）
   - `SecurityHeadersMiddleware`（CSP / X-Frame-Options 等安全头）
   - `HTTPSRedirectMiddleware`（仅当配置了 SSL 证书时启用）
   - `NoCacheStaticMiddleware`（HTML 不缓存、静态资源 10 分钟 ETag）
4. 挂载 `routers/api.py` 的 `router`
5. 挂载静态文件目录：`/ui`、`/css`、`/js`
6. 注册根路由 `/` 直接返回 `index.html`（绕过 catch-all 中间件链）
7. SPA 前端回退：`/{full_path:path}` 优先返回真实文件，否则回 `index.html`
8. 文档中心：`/doc` 与 `/doc/{path}` 返回 `docs/` 目录内容
9. 启动入口：`uvicorn.run(app, host, port)`，启动时打印所有非 127.0.0.1 的 IP

### 3.2 核心层 `backend/core/`

#### 3.2.1 `core/config.py` —— 配置加载器

- `CONFIG_FILE`：`backend/config.json` 路径
- `_default_config()`：返回完整默认配置（用于缺失字段补全）
- `load_config()`：读取 `config.json`，与默认配置深度合并（`defaults[section].update(cfg[section])`）
- `save_config(cfg)`：写回 `config.json`（用于云环境切换等持久化场景）

#### 3.2.2 `core/constants.py` —— 全局常量

从 `CONFIG` 衍生的所有运行时常量集中定义，避免散落各处：

| 常量类别 | 主要常量 |
|---------|---------|
| 安全 | `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` / `BCRYPT_ROUNDS` / `RATE_LIMIT_*` / `INPUT_FILTER_*` / `AUDIT_*` |
| 数据库 | `DB_TYPE` / `DB_PATH` / `AUDIT_DB_PATH` / `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` |
| ROS2 工作空间 | `ROS2_DEFAULT`（dict：launch_dir/scripts_dir/logs_dir/bag_storage/host_ws/host_install/container_install/container_bag_path/config_dir/backup_dir） |
| 服务器 | `PORT` / `HOST` / `CORS_ALLOWED_ORIGINS` / `CORS_ALLOW_ORIGIN_REGEX` |
| 可视化 | `VISUALIZATION_CONFIG` / `DEFAULT_VISUALIZATION_METHOD` / `VISUALIZATION_METHODS` |
| 面板权限 | `ALL_PANELS`（23 个面板 ID 列表，admin 拥有全部） |
| 全局状态 | `ws_clients`（WebSocket 客户端列表）/ `traffic_sender` / `timer_traffic_sender` |

**特殊处理**：
- `JWT_SECRET` 默认值检测：若仍为 `"CHANGE_ME_TO_A_RANDOM_SECRET"`，则自动生成临时强密钥并打印警告
- 路径展开：所有 `~` 开头的路径通过 `_expand()` 转为绝对路径
- `os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)`：启动即确保审计日志目录存在

#### 3.2.3 `core/security.py` —— 安全工具

- `pwd_context`：passlib 的 bcrypt 上下文（`bcrypt__rounds=BCRYPT_ROUNDS`）
- `hash_password(password)` / `verify_password(plain, hashed)`：密码哈希与校验
- `create_jwt_token(data, expires_delta)`：JWT 签发，自动注入 `exp`
- `decode_jwt_token(token)`：JWT 解码，失败返回 `None`
- `sanitize_command(cmd_str)`：命令注入防御
  - 过滤 `;&|$` 反引号等危险字符
  - 校验命令是否在 `INPUT_FILTER_WHITELIST` 中
  - 限制命令长度 1024 字符
  - **仅在 `INPUT_FILTER_ENABLED=True` 时启用**（默认关闭）
- `limiter`：slowapi 速率限制器实例

#### 3.2.4 `core/middleware.py` —— 中间件

**`SecurityHeadersMiddleware`**：
- API 文档路径（`/api/docs` / `/api/redoc` / `/openapi.json`）跳过
- 其他响应添加：
  - `X-Content-Type-Options: nosniff`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy`：限制 script/style 仅允许 `self` + `cdn.jsdelivr.net`，connect 允许 `ws/wss/http/https`

**`NoCacheStaticMiddleware`**：
- HTML（`/`、`/index.html`、`*.html`）：`no-cache, no-store, must-revalidate`，删除 ETag
- 静态资源（`/css/*`、`/js/*`、`/images/*`、`/fonts/*` 及常见静态后缀）：`public, max-age=600, must-revalidate`（10 分钟 + ETag 校验）
- 其他请求：透传

#### 3.2.5 `core/workspace.py` —— 用户工作空间管理

**核心原则：用户隔离**

- `validate_user_path(requested_path, user_info, target_user=None)`：
  - 管理员无 `target_user` 时全局放行
  - 管理员操作目标用户空间：以目标用户的 `home_folder_path` 为根
  - 普通用户：必须在自己 `home_folder_path` 下
  - 使用 `os.path.realpath` 防止符号链接绕过
  - 路径不以 `user_root + os.sep` 开头则抛 `HTTPException(403)`

- `get_user_workspace_paths(current_user, target_user=None)`：
  - 管理员全局模式：返回 `ROS2_DEFAULT` 全局路径（v5.0：同样经 `resolve_versioned_install` 按管理员当前选择的版本解析 install）
  - 管理员查看目标用户：返回目标用户的隔离路径
  - 普通用户：基于 `home_folder_path` 拼接：
    - `scripts_dir = home/Docker/scripts`
    - `logs_dir = home/Docker/logs`
    - `bag_storage = home/Docker/bags`
    - `backup_dir = home/Docker/bk`
    - `launch_dir = <版本化 install>/simulation_launches/share/simulation_launches/launch`（v5.0：随所选版本变化）
    - `bk_backups_dir = home/Docker/bk/.bk_backups`
  - **v5.0 版本注入**：读取用户记录中的 `current_version` 字段，调用 `resolve_versioned_install` 解析后注入 `current_version` / `install_dir` / `version_dir` / `is_versioned` / `versions`（版本列表）

**v5.0 install 版本管理函数**：

| 函数 | 用途 |
|------|------|
| `sanitize_version_name(name)` | 版本名清洗（去除首尾空白/路径分隔符，截断 100 字符） |
| `is_valid_version_name(name)` | 合法性校验：非空、≤100 字符、仅 `[A-Za-z0-9._-]`、不得为 `.`/`..` 且不以 `.` 开头 |
| `list_user_versions(host_ws)` | 扫描工作空间下的版本目录（含 `install/setup.bash` 判定），排除 `install`/`Docker`/备份目录/隐藏目录 |
| `resolve_versioned_install(home, current_version)` | **核心路径解析**：版本合法且目录存在 → `<home>/<版本>/install`；否则回退旧版 `<home>/install`（`is_versioned=False`） |
| `is_version_backup_entry(entry)` | 识别删除/替换产生的备份目录（`<名>.deleted.<时间戳>` 等后缀模式，正则 `.(deleted\|bak\|replaced).\d{8,}$`） |
| `get_admin_install_dir()` | 获取管理员当前生效的 install 目录（供 `run_ros2_cmd` source 对应版本的 `setup.bash`） |

**版本化目录结构**：

```
<home_folder_path>/
├── install/                    # 旧版路径（未选择版本时回退使用）
├── Docker/                     # scripts/logs/bags/bk
├── demo_install_v1.0/          # v5.0：版本目录（压缩包顶层目录名）
│   └── install/
└── demo_install_v2.0/
    └── install/
```

- `create_user_workspace(username)`：
  - 路径：`~/robotruck_ros2/<username>/`
  - 从 `~/robotruck_ros2/Template`（纯净模板）复制为 `Docker` 目录
  - 模板不存在时退化为创建 `bags/bk/logs/scripts` 空子目录
  - `chown -R fox:fox`（兼容历史部署）
  - 返回 `user_home` 路径，写入用户表的 `home_folder_path`

#### 3.2.6 `core/cache.py` —— 内存缓存

- `SimpleCache(maxsize=128)`：基于 `OrderedDict` 的 LRU 缓存
  - `get(key)`：命中后移动到末尾，过期则删除返回 `None`
  - `set(key, value, ttl=60)`：写入并设置过期时间，超过 maxsize 弹出最旧
  - `invalidate(prefix=None)`：清空全部或前缀匹配
- `_memory_cache`：全局单例，maxsize=256
- 用于 `supabase_db.py` 缓存 `get_user`（30s TTL）、`get_visible_container_names`（10s TTL）

#### 3.2.7 `core/utils.py` —— 通用工具

关键函数：

| 函数 | 用途 |
|------|------|
| `expand_path(p)` | 展开 `~` 和环境变量 |
| `generate_username_from_email(email)` | 邮箱 → 用户名（`@` 前部分，`.` 替换为 `_`） |
| `extract_letters_and_numbers(name)` | 从 SN 提取字母+数字部分（兼容 `hytz3788` 与 `hytz_3788` 两种格式） |
| `generate_files(root_dir, user_input, log_callback, sim_dir, mock_dir)` | **核心**：根据 SN 生成 ROS2 配置文件（launch / cloud.yaml / device.yaml / project.yaml / truck.yaml / mock_truck.yaml / mock_truck_launch.py），并更新 `simulation_launch.py` 中的 `KEY_*` 常量 |
| `run_ros2_cmd(cmd, timeout)` | 在宿主机执行 ROS2 命令（v5.0：优先 source 管理员当前所选版本 install 下的 `setup.bash`，缺失时回退全局 `SETUP_BASH`） |
| `run_ros2_cmd_in_container(name, cmd, timeout)` | 在容器内执行 ROS2 命令 |
| `extract_versioned_install(tmp_path, host_ws, fallback_version)` | **v5.0**：将上传的压缩包解压为 `<host_ws>/<版本名>/install/` 结构（版本名取压缩包顶层目录名，非法时用 fallback；顶层直接是 install 内容时按 fallback 归档；同名版本自动备份为 `<名>.bak.<时间戳>` 后替换） |
| `_prune_backups(dir_path, prefix, keep=5)` | **v5.0**：清理同名版本的历史备份目录，仅保留最近 5 份 |
| `load_whitelist()` / `save_whitelist(prefixes)` | 加载/保存脚本白名单（`~/.ros2_docker_manager_whitelist.json`） |
| `parse_size(s)` | 解析 `100M` / `1G` 等大小字符串 |
| `get_used_ports()` | 扫描已使用端口（`ss -tlnp`） |
| `find_free_port(start, end, used_ports)` | 在范围内查找空闲端口 |
| `build_dir_tree(path, prefix, max_depth, ignore)` | 构建目录树（用于 install 目录展示） |
| `extract_and_flatten(zip_path, dest_dir)` | 解压并扁平化 zip |
| `_safe_copy2(src, dst)` | 安全复制（保留元数据） |
| `_normalize_rviz_config(path)` / `_resolve_rviz_config(path)` / `_maximize_rviz(path)` | RVIZ 配置处理 |
| `error_response(msg, code)` | 统一错误响应格式 |
| `broadcast_log(message)` | 向所有 WebSocket 客户端广播日志 |
| `generate_files(...)` | 详见 [§5.4](#54-脚本生成流程) |

### 3.3 数据库层 `backend/database/`

#### 3.3.1 `database/__init__.py` —— 工厂

```python
def init_database():
    if DB_TYPE == "supabase" and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDatabase(SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY)
    return JsonDatabase(DB_PATH, AUDIT_DB_PATH)
```

模块加载时即创建全局 `db` 实例，供 `deps.py` 与 `routers/` 导入。

#### 3.3.2 `database/json_db.py` —— JSON 文件数据库

**双文件设计**：
- `self.path`（`data/data.json`）：用户数据（users / configs）
- `self.audit_path`（`data/audit_logs.json`）：操作日志
- 两份独立加锁（`self.lock` / `self.audit_lock`），互不阻塞

**初始化**：
- 文件不存在 → 创建默认管理员 `admin / 123456`（JSON 模式密码）
- 旧用户字段补全：`id` / `onboarding_completed` / `onboarding_skipped`
- 权限迁移：非 admin 用户自动追加 `data-export` 权限
- 历史日志迁移：将 `data.json` 中遗留的 `audit_logs` 数组迁移到独立文件

**关键方法**：
- `get_user(username)` / `get_user_by_id(user_id)`（v5.0：`get_user` 支持按 email 键或 `username` 字段双重查找，与 Supabase 适配器行为对齐）
- `create_user(username, password, role, home_folder_path, permissions)`：根据 role 分配默认权限（v5.0：记录新增 `username` 字段、`current_version=""`、`home_folder_path`，与 Supabase 字段对齐）
- `update_user(user_id, updates)`：支持 password / role / permissions / current_version 更新
- `delete_user(user_id)`：保留至少 1 个管理员，否则拒绝删除
- `verify_login(username, password)`：bcrypt 校验
- `get_user_permissions(username)`：admin 返回 `ALL_PANELS`
- `add_audit_log(username, action, details)`：同时写 JSON 与 `AUDIT_LOG_FILE` 文本
- `get_audit_logs(limit=100)` / `delete_audit_logs(keep_recent)` / `delete_audit_logs_by_user(username)`
- `get_onboarding_state(username)` / `set_onboarding_state(username, completed, skipped)`
- 工单系统：`create_ticket` / `get_ticket` / `list_tickets` / `update_ticket` / `delete_ticket` / `create_reply` / `list_replies`（数据存于 `data/tickets.json`）
- 容器隔离（JSON 模式空实现）：`register_container` / `get_visible_container_names` 等返回 `False/None`（不做过滤）

**审计日志上限**：`MAX_AUDIT_LOGS = 10000`，超过自动裁剪最新 10000 条。

#### 3.3.3 `database/supabase_db.py` —— Supabase 数据库

- 表结构：`public.users` / `public.audit_logs` / `public.containers` / `public.tickets` / `public.ticket_replies`
- 容器隔离：`register_container(container_id, name, image, state, created_by)` 写入 `created_by`；`get_visible_container_names(current_user)` 返回 admin 全部 / 普通用户仅自己创建的
- 缓存：`get_user` 缓存 30s，`get_visible_container_names` 缓存 10s；写入操作主动失效
- DDL 脚本：`data/ros2_web_supabase.sql`（**v5.0 部署必做**：`users` 表需新增 `current_version TEXT DEFAULT ''` 列，启动时 `_migrate_onboarding_columns` 会自动探测并输出待执行 SQL，缺失时版本切换无法保存）

### 3.4 业务服务层 `backend/services/`

#### 3.4.1 `services/docker_manager.py` —— Docker 管理

`DockerManager` 类，封装所有 Docker CLI 操作（通过 subprocess 调用 `docker` 命令，不依赖 Docker SDK 以避免阻塞）：

| 方法 | 用途 |
|------|------|
| `run_cmd(cmd, timeout=30)` | 执行系统命令，返回 `(rc, stdout, stderr)` |
| `list_containers(running_only, filter_name, filter_image)` | 列出容器，支持 `!` 前缀排除 |
| `list_containers_detailed(running_only, filter_name, filter_image)` | **性能优化**：单次 `docker ps` 批量获取 ID/名称/状态/镜像/创建时间/`ros2.cloud_ip` label |
| `_docker(*args)` | 构造 `docker` 命令前缀（含 sudo 判断） |
| `stop_container(name)` / `stop_all_ros2_containers(container_names)` | 停止单个/批量（admin 全部 / 用户仅自己的） |
| `get_container_info(name, format_str)` | `docker inspect` 指定格式 |
| `update_resources(name, cpus, memory_gb)` | 动态调整 CPU/内存限制 |
| `exec_command(name, command, detach, timeout)` | 容器内执行命令（经 `sanitize_command` 过滤） |
| `list_images()` / `load_image(tar_path)` / `remove_image(image_name)` | 镜像管理（限制 5GB） |

**关键优化**：`list_containers_detailed` 合并原先的两次子进程为一次，避免每次刷新执行多个 `docker` 子进程。

#### 3.4.2 `services/script_generator.py` —— ROS2 脚本生成器

`ROS2ScriptGenerator` 类，基于模板生成 Docker 启动脚本：

**配额控制**：
- `ADMIN_QUOTA = 26` / `USER_QUOTA = 15` / `GLOBAL_MAX = 100`
- `BASE_VNC_PORT = 5900` / `BASE_WEB_PORT = 6080`
- `QUOTA_EXEMPT_BASES = {"simulation_launch"}`：核心仿真 launch 不计入车辆配额
- 总脚本位上限 16 = 15 辆车 + 1 个 simulation_launch

**模板管理**：
- 模板文件 `start_docker_template.sh` 存放在管理员全局 `~/robotruck_ros2/Docker/bk/`，避免被清空逻辑误删
- 用户脚本存放在各自工作空间的 `Docker/scripts/`

**索引管理**：
- `_extract_used_indices_from_dir(scripts_dir)`：从脚本提取已用索引
  - 新脚本：`# VEHICLE_INDEX=N` 注释行
  - 旧脚本兼容：从 `ROS_DOMAIN_ID=N` 反推（N-1），或从 `DISPLAY=:N` 反推（N-1）
- 寻找最小未用索引，避免冲突

**端口分配规则**：
- `host_port = base_port + domain_id * 10`
- 例如 `domain_id=1`：VNC 5901 → 5911，Web 6080 → 6090

#### 3.4.3 `services/system_monitor.py` —— 系统监控

`SystemMonitor.get_system_status()`：
- **CPU**：`psutil.cpu_percent(interval=0.3)` + 每核心使用率 + 平均负载
- **内存**：`psutil.virtual_memory()` + `psutil.swap_memory()`
- **GPU**：调用 `nvidia-smi` 查询 GPU 利用率/显存/温度/功耗（超时 2s）
- **GPU 进程**：`nvidia-smi --query-compute-apps` + UUID 映射到 GPU index
- **进程 Top20**：按 CPU 占用排序

返回 `(sys_text, proc_data, gpu_proc_data)` 三元组。

#### 3.4.4 `services/system_utils.py` —— 系统工具

`SystemUtils` 类：
- `change_software_source(source_url)`：切换 apt 源（备份 `/etc/apt/sources.list`）
- `install_package(package)` / `uninstall_package(package)`
- 证书切换、文件夹同步等

#### 3.4.5 `services/traffic_light.py` —— 红绿灯模拟器

两个类：

**`TrafficLightSender`**（MQTT 模式）：
- 通过 HTTP 登录云平台获取 token（`/shovel/api/v3/device/login/`）
- 通过 MQTT 订阅 `command/{project_id}/{sn}/request/change_state` 接收灯状态变更
- 通过 UDP 上报灯状态到 `cloud_host`
- 状态：`STATE_GREEN=1` / `STATE_RED=2` / `STATE_OFF=3` / `STATE_YELLOW=4`
- 模式：`mode=1`（自动响应 MQTT）/ `mode=2`（手动，忽略 MQTT）

**`TimerTrafficLightSender`**（定时模式）：
- 按固定间隔循环切换灯状态
- 用于测试场景

#### 3.4.6 `services/data_export_service.py` —— 数据导出

`DataExportService` 类（v4.0 新增）：

**常量**：
- `BAG_RECORD_CMD`：默认 bag 录制命令（mcap 格式，全话题）
- `HDMAP_BASE = "/home/boonray/resource_data"`：容器内 hdmap 根目录
- `CONTAINER_BAG_PATH = "/home/boonray"`：容器内 bag 录制目录

**会话管理**：
- `_bag_sessions: dict` + `_bag_sessions_lock`：每个容器一个录制会话
- 状态：`recording` / `stopped` / `idle`

**关键方法**：

| 方法 | 流程 |
|------|------|
| `_ensure_ros2_container(name)` | 校验容器存在 + 运行中 + 镜像含 `ros2/humble/foxy` |
| `_sanitize_sn(sn)` | 仅保留 `[a-zA-Z0-9_-]` |
| `_get_bag_storage(user, target_user)` | 返回 `ROS2_DEFAULT["bag_storage"]`（全局 bag 目录，未来可改为用户隔离） |
| `extract_hdmap(name, sn, user, target_user)` | 详见 [§5.5](#55-地图提取流程) |
| `start_bag_record(name, user, target_user)` | 详见 [§5.6](#56-bag-录制流程) |
| `stop_bag_record(name, user, target_user)` | 详见 [§5.6](#56-bag-录制流程) |
| `get_bag_status(name)` | 返回当前录制会话状态 + 已录制时长 |
| `list_bag_files(user, target_user, container_name)` | 列出 bag 目录文件，可按 vehicle_id 过滤 |
| `delete_bag_files(filenames, user, target_user)` | 批量删除 bag 文件（路径遍历防御） |
| `_extract_vehicle_id(name)` | 从容器名提取 vehicle_id（兼容 `ros2_admin_xxx` / `ros2_xxx` 格式） |

### 3.5 路由层 `backend/routers/`

#### 3.5.1 `routers/api.py` —— 主路由

包含约 150 个端点，按业务域分组（详见 [§6 API 清单](#6-api-接口全量清单)）。

**全局服务实例**：
- `script_generator`：`ROS2ScriptGenerator` 实例
- `system_monitor`：`SystemMonitor` 实例
- `traffic_sender` / `timer_traffic_sender`：从 `core.constants` 导入的全局状态

**关键路由分组**：

| 分组 | 代表端点 | 说明 |
|------|---------|------|
| 认证 | `/api/auth/login`、`/api/auth/register`、`/api/auth/me` | JWT 签发与校验 |
| 用户管理 | `/api/admin/users`（GET/POST/PUT/DELETE） | 管理员专属 |
| 审计日志 | `/api/admin/audit-logs` | 管理员查看/清除 |
| 权限 | `/api/auth/permissions`、`/api/auth/onboarding` | 用户权限与新手引导 |
| 系统状态 | `/api/system/status`、`/api/system/monitor` | CPU/内存/GPU 实时 |
| 系统工具 | `/api/system/apt-source`、`/api/system/install`、`/api/system/clean` | 换源/装包/清理 |
| 云环境 | `/api/system/cloud-env`、`/api/system/cloud-status`、`/api/system/cloud-config` | 切换云平台 |
| 文件 | `/api/files/list`、`/api/files/upload`、`/api/files/download`、`/api/files/delete` | 文件管理 |
| ROS2 | `/api/ros2/topics`、`/api/ros2/nodes`、`/api/ros2/services`、`/api/ros2/actions` | ROS2 实体查询 |
| ROS2 控制 | `/api/ros2/simulation/start`、`/api/ros2/topic/kill`、`/api/ros2/node/kill` | 仿真与 kill |
| Docker | `/api/docker/containers`、`/api/docker/container/{id}/*` | 容器全生命周期 |
| 可视化 | `/api/visualization/methods`、`/api/docker/container/{id}/visualize` | Foxglove/VNC/RVIZ |
| 脚本 | `/api/scripts/generate`、`/api/scripts/list`、`/api/scripts/execute` | 脚本 CRUD + 执行 |
| install | `/api/install/status`、`/api/install/upload`、`/api/install/versions`、`/api/install/versions/switch`、`/api/install/delete`、`/api/install/deploy` | install 目录管理（v5.0：多版本上传/切换/删除） |
| bk 备份 | `/api/system/bk/*` | 备份/回滚/历史 |
| 端口 | `/api/ports/used` | 已用端口列表 |
| 红绿灯 | `/api/traffic-light/*`、`/api/timer-traffic-light/*` | MQTT + 定时两种模式 |
| 批量生成 | `/api/batch/generate` | 批量生成车辆配置 |
| 车辆配置 | `/api/truck/config/list`、`/api/truck/config/{filename}` | truck YAML 管理 |
| 白名单 | `/api/system/whitelist`（GET/POST/DELETE） | 脚本白名单 |
| GPU | `/api/system/monitor/gpu-detail` | GPU 详情 |
| 系统检查 | `/api/system/check`、`/api/system/check/fix` | 健康检查 + 自动修复 |
| 远程主机 | `/api/system/remote-hosts` | SSH 远程主机管理 |
| 插件 | `/api/system/plugins` | 动态插件加载 |
| API 设置 | `/api/system/api-settings` | 远程 API 配置 |
| 资源泄漏 | `/api/system/resource-leaks` | 资源泄漏检测 |
| 帮助 | `/api/system/help/{page}`、`/api/system/help` | 帮助页面 CRUD |
| sudo 检查 | `/api/system/sudo-check`、`/api/system/auth/save`、`/api/system/auth/status` | sudo 密码托管 |
| 故障注入 | `/api/fault/inject`、`/api/fault/clear`、`/api/fault/list`、`/api/fault/history` | 故障管理 |
| WebSocket | `/ws`、`/ws/containers/{name}/logs`、`/ws/containers/{name}/shell` | 实时日志与终端 |
| 工单 | `/api/tickets`、`/api/tickets/{id}`、`/api/tickets/{id}/replies`、`/api/tickets/attachments` | 工单全流程 |

**性能优化**（v3.5）：
- 高频只读端点改为 `def`（非 `async def`）：FastAPI 自动放入线程池执行，避免 `docker` 子进程 / `nvidia-smi` / `psutil` 阻塞事件循环
- 涉及端点：`system_status` / `system_monitor` / `list_images` / `list_containers` / `get_install_status` / `list_scripts` / `get_default_paths` / `get_quota_status` / `traffic_status` / `get_light_status` / `list_truck_configs` / `get_truck_config`

#### 3.5.2 `routers/data_export.py` —— 数据导出路由

v4.0 新增，遵循解耦规范：

- **路由层只做**：参数校验（Pydantic 模型）→ 调用 `DataExportService` → 写审计日志 → 返回响应
- **不包含业务逻辑**

**Pydantic 模型**：
- `HdmapExtractRequest`：`container_name` / `sn` / `target_user`
- `BagRecordRequest` / `BagStopRequest`：`container_name` / `target_user`
- `BagDeleteRequest`：`filenames: list` / `target_user`

**端点**：
- `GET /api/data-export/hdmap/sn-list?container_name=`
- `POST /api/data-export/hdmap/extract`
- `POST /api/data-export/bag/start`
- `POST /api/data-export/bag/stop`
- `GET /api/data-export/bag/status?container_name=`
- `GET /api/data-export/bag/list?container_name=&target_user=`
- `POST|DELETE /api/data-export/bag/delete`
- `GET /api/data-export/bag/download?file=&target_user=`

所有端点均通过 `Depends(require_permission('data-export'))` 校验权限。

### 3.6 依赖注入 `backend/deps.py`

- `security = HTTPBearer(auto_error=False)`：Bearer Token 提取器
- `get_current_user(credentials)`：解析 JWT → 查询用户 → 返回 `{email, role, username, home_folder_path, id, current_version}`（v5.0：注入 `current_version` 供工作空间路径解析）
- `require_admin(current_user)`：校验 `role == "admin"`，否则 403
- `require_permission(panel)`：返回依赖函数
  - admin 直接放行
  - 普通用户：查 `db.get_user_permissions(email)`，未授权抛 403

### 3.7 数据模型 `backend/models.py`

```python
class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False
    remember_days: int = 1  # 1/7/15/30

class RegisterRequest(BaseModel):
    username: str
    password: str
```

### 3.8 日志 `backend/logger.py`

- `LOG_DIR = ~/ros2_web/log`
- 三个 FileHandler：
  - `app.log`（DEBUG 级别，全量）
  - `audit.log`（INFO 级别，审计）
  - `audit_debug.log`（DEBUG 级别，调试）
- 一个 StreamHandler（INFO 级别，控制台）
- `_initialized` 单例保护，避免重复初始化
- 模块导入即自动初始化，导出全局 `logger` 实例

---

## 4. 前端代码详解

### 4.1 主页面 `frontend/index.html`

**结构**（24 个章节）：
1. 页面元信息与外部依赖
2. 登录注册弹窗
3. 侧边栏导航
4. 主内容面板
5. 脚本与运行时依赖
6. 启动入口

**外部依赖**（按需加载）：
- `xterm.css` + `xterm.js`：首次打开终端时由 `loadTerminalModule()` 注入
- `sj_style.css`：同步加载（首屏关键）
- `onboarding.css`：`media="print" onload="this.media='all'"` 异步加载

**面板列表**（与 `ALL_PANELS` 对应）：
`welcome` / `scripts` / `advanced-scripts` / `vehicle` / `docker` / `advanced-docker` / `images` / `traffic` / `advanced-fault` / `tools` / `monitor` / `simulation` / `topics` / `nodes` / `services` / `actions` / `advanced-extend` / `api-manager` / `theme` / `settings` / `tickets` / `data-export`

**v5.0 侧边栏版本徽章**：`sidebar-header` 中新增 `#sidebarVersionBadge` 元素，全局展示当前 install 版本号（`updateSidebarVersionBadge()` 更新，无版本时隐藏）。

### 4.2 主逻辑 `frontend/js/sj_script.js`

**24 个章节**：

1. **全局变量与配置**
   - `API_BASE = ''`（同源）
   - `AUTH_TOKEN`：从 `localStorage` 读取
   - `CURRENT_USER` / `USER_ROLE` / `CURRENT_VERSION`（v5.0：当前 install 版本，随 `/api/auth/me` 同步）
   - `ENV_IP_MAP`：云环境 IP 映射
   - `subMenuMap` / `menuHierarchy`：菜单层级
   - `defaultColors`：dark/light 主题颜色

2. **认证管理**：`login()` / `register()` / `logout()` / `checkAuth()` / Token 管理

3. **初始化与导航**：`initApp()` / `switchPanel(name)` / `toggleSubMenu(parent)`

4. **API 工具函数**：`apiGet(url)` / `apiPost(url, data)` / `apiPut` / `apiDelete`（自动注入 `Authorization: Bearer <token>`）

5. **Toast 通知**：`showToast(msg, type)`（success/error/warning/info）

6. **WebSocket 连接**：`connectWS()` / 自动重连 / `wsReconnectTimer`

7. **系统状态**：`loadSystemStatus()` / `refreshSystemStatus()`

8. **仿真控制**：`startSimulation()` / `stopSimulation()`

9. **话题管理**：`listTopics()` / `topicInfo(name)` / `topicEcho(name)` / `pubTopic()` / `killTopic()`

10. **节点管理**：`listNodes()` / `nodeInfo()` / `killNode()`

11. **服务管理**：`listServices()` / `serviceType()` / `callService()` / `killService()`

12. **Action 管理**：`listActions()` / `actionInfo()` / `sendGoal()`

13. **Docker 管理**
    - `loadContainers(filter)`：容器列表
    - `renderContainerRow(c)`：渲染单行（含操作按钮）
    - `startContainer(id)` / `stopContainer(id)` / `restartContainer(id)` / `removeContainer(id)`
    - `viewLogs(id)` / `execCommand(id)` / `viewRosLogs(id)` / `updateResources(id)`
    - `openTerminal(id, mode)`：调用 `loadTerminalModule()` 按需加载终端
    - **操作按钮布局**：移除"更多"下拉，所有按钮（启动/停止/重启/终端/日志/RVIZ/资源/删除/提取地图/录制Bag/下载Bags）直接排在 `.action-buttons` 容器中

14. **脚本管理**：`generateScript()` / `listScripts()` / `editScript()` / `executeScript()` / `batchExecute()` / `removeGpu()`

15. **镜像管理**：`loadImages()` / `loadImage()` / `removeImage()`

16. **系统监控**：`loadMonitor()` / `toggleAutoRefresh()`

17. **其他工具**：换源 / 装包 / 证书切换 / 文件夹同步

17b. **install 版本管理（v5.0）**
    - `renderVersionSectionHtml(data)`：首页"安装目录管理"卡片顶部渲染版本区块（当前版本徽章 + 下拉切换器 + 版本删除按钮，仅旧版 `install` 存在时显示回退项）
    - `switchInstallVersion()`：切换版本（confirm 确认 → POST `/api/install/versions/switch` → 自动刷新页面使全局生效）
    - `deleteInstallVersion(version)`：删除非当前版本（后端备份为 `<名>.deleted.<时间戳>`）
    - `updateSidebarVersionBadge(v)`：更新侧边栏版本徽章
    - 上传成功后自动切换到新版本并刷新页面；`checkInstallStatus()` 同时缓存版本列表信息

18. **红绿灯模拟**：`startTraffic()` / `stopTraffic()` / `setLightState()` / `setLightMode()`

19. **批量生成车辆**：`batchGenerate()`

20. **主题设置**：`applyTheme(colors)` / `toggleTheme()` / `saveTheme()`

21. **终端模拟（xterm）**：`loadTerminalModule(callback)` 动态注入 xterm CDN + `panels/terminal.js`

22. **子菜单控制**：`toggleSubMenu(parent)` / `expandSubMenu(child)`

23. **修改密码**：`changePassword()`

24. **工具函数**：`escapeHtml(s)` / `formatBytes(n)` / `formatDuration(s)` / `hasPermission(panel)` / `closeDropdowns()` 等

### 4.3 表单校验 `frontend/js/sj_validators.js`

- `isValidBoonrayEmail(username)`：校验 `名.姓@boonray.com` 格式
- `isValidPassword(pwd)`：密码强度
  - 首字母大写
  - 至少一个字母
  - 至少一个特殊符号
  - 不能含连续三个递增/递减数字（如 `123`、`321`）
  - 长度 ≥ 6（由调用方检查）

### 4.4 终端模块 `frontend/js/panels/terminal.js`

**按需加载策略**：
- 首次打开终端时由 `loadTerminalModule()` 同时注入：
  - `xterm.js`（~150KB）
  - `xterm-addon-fit`
  - `panels/terminal.js` 本身
- 避免首屏被迫下载 xterm

**核心函数**：`_openTerminalImpl(containerId, mode, sourceRos2)`
- 创建全屏 overlay + 可拖拽调整大小的 modal
- 通过 WebSocket `/ws/containers/{name}/shell` 建立终端会话
- 支持 `normal` / `root` 两种模式
- `sourceRos2=true` 时自动 `source /home/boonray/install/setup.bash`
- 工具栏：复制内容 / 清屏 / 最大化 / 关闭

### 4.5 数据导出模块 `frontend/js/panels/data_export.js`

**注入策略**：
- `MutationObserver` 监听 `#containersTableBody` 子节点变化
- 检测到新的 `tr[data-container-id]` 行时调用 `_injectButtonsIntoRow(row)`
- 通过 `INJECTED_FLAG = 'data-export-injected'` 标记避免重复注入

**注入条件**：
- 容器名包含 `ros2` / `humble` / `foxy` 才注入（`_isRos2Container`）
- 仅 ROS2 容器显示数据导出按钮

**注入的三个按钮**：
- 🗺️ 提取地图：打开 SN 选择 modal → 调用 `POST /api/data-export/hdmap/extract`
- ⏺️ 录制 Bag：调用 `POST /api/data-export/bag/start`，按钮变为"停止录制" → `POST /api/data-export/bag/stop`
- 📦 下载 Bags：打开 bag 列表 modal → `GET /api/data-export/bag/list` → 下载 `GET /api/data-export/bag/download`

**下载实现**：`fetch` + `Authorization` header → `blob` → `<a download>` 触发浏览器下载

### 4.6 onboarding `frontend/js/onboarding.js`

> **注意**：当前文件为空（占位），未实现新手引导逻辑。`sj_script.js` 中有 `loadOnboarding()` 占位调用。

### 4.7 Service Worker `frontend/sw.js`

**缓存策略**：
1. **静态资源**（`/css/*`、`/js/*`、`/images/*`、`/fonts/*`、`/ui/*` 及 `.css/.js/.png/.jpg/.gif/.svg/.ico/.woff/.woff2/.ttf/.eot`）：
   - **缓存优先**（cache-first）：F5 时直接返回缓存，后台静默更新
2. **HTML 文档**（`/`、`/index.html`、`*.html`）：
   - **stale-while-revalidate**：先返回缓存版本秒显，后台更新
3. **API 请求**（`/api/*`、`/ws`）：不拦截
4. **API 文档**（`/openapi.json`、`/api/docs`、`/api/redoc`、`/doc/*`）：不拦截

**生命周期**：
- `install`：预缓存核心资源（`sj_style.css`、`onboarding.css`、`sj_script.js`、`panels/terminal.js`），失败不阻止安装，`skipWaiting()` 立即接管
- `activate`：清理旧版本缓存，`clients.claim()` 立即生效

### 4.8 样式 `frontend/css/sj_style.css`

**容器列表表格布局**（v4.0.2 优化）：
```css
#containersCollapsible .data-table {
    table-layout: auto;  /* 内容列按内容宽度，操作列占剩余空间 */
    width: 100%;
}
#containersCollapsible .data-table th {
    padding: 8px 6px;
    font-size: 11px;
    text-align: center;  /* 表头居中 */
}
#containersCollapsible .data-table th:nth-child(1) {
    text-align: left;  /* 名称列左对齐 */
}
#containersCollapsible .data-table th:last-child {
    text-align: center !important;  /* 操作列表头居中 */
}
.action-btn {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 500;
    transition: all 0.2s ease;
    border: 1px solid transparent;
    cursor: pointer;
    white-space: nowrap;  /* 防止按钮换行 */
    flex-shrink: 0;  /* 不被压缩 */
}
```

**列布局**：
- 名称 / 容器运行状态 / 运行时长 / 云平台连接：4 列紧凑（按内容宽度）
- 操作：占据所有剩余空间，所有按钮单行排列

---

## 5. 数据流与关键业务流程

### 5.1 登录认证流程

```
浏览器                          后端                          数据库
  │                              │                              │
  │ POST /api/auth/login         │                              │
  │ {username, password, ...}    │                              │
  ├─────────────────────────────►│                              │
  │                              │ db.verify_login(user, pwd)  │
  │                              ├─────────────────────────────►│
  │                              │◄───── user dict (含 role) ──┤
  │                              │                              │
  │                              │ create_jwt_token({sub, role})│
  │                              │ db.add_audit_log(login_success)│
  │                              │                              │
  │  {access_token, role, ...}   │                              │
  │◄─────────────────────────────┤                              │
  │                              │                              │
  │ localStorage.setItem(token)  │                              │
  │                              │                              │
```

### 5.2 权限校验流程

每个受保护端点通过 `Depends(require_permission(panel))` 注入校验：

```
请求 → HTTPBearer 提取 token → decode_jwt_token
     → get_current_user（查询 db.get_user）
     → require_permission(panel)
        ├─ admin：直接放行
        └─ user：db.get_user_permissions(email)
                  ├─ panel in permissions：放行
                  └─ 否则：HTTPException(403)
```

### 5.3 容器列表加载流程

```
前端 loadContainers(filter)
  → GET /api/docker/containers?running_only=&filter_name=ros2_
  → 后端 DockerManager.list_containers_detailed(running_only, filter_name)
     → 单次 docker ps --format ... （含 ros2.cloud_ip label）
     → 返回 [{id, name, status, image, created, cloud_ip}, ...]
  → 前端 renderContainerRow(c) 渲染
     → .action-buttons 中按钮：
        启动/停止/重启/终端/日志/RVIZ/资源/删除
     → MutationObserver 触发 data_export.js 注入：
        提取地图/录制Bag/下载Bags
```

**性能优化**：
- 后端 `def`（非 `async def`）→ FastAPI 放入线程池，避免阻塞事件循环
- 单次 `docker ps` 替代多次子进程调用
- Supabase 模式下 `get_visible_container_names` 缓存 10s

### 5.4 脚本生成流程

```
用户输入 SN（如 mhw_299）
  → POST /api/scripts/generate {sn, ...}
  → ROS2ScriptGenerator.generate(...)
     1. 校验配额（admin 26 / user 15 / global 100）
     2. 提取已用索引（兼容新旧脚本格式）
     3. 分配最小未用索引 N
        - ROS_DOMAIN_ID = N + 1
        - DISPLAY = :N
        - VNC 端口 = 5900 + N * 10
        - Web 端口 = 6080 + N * 10
     4. generate_files(root_dir, sn, log_cb, sim_dir, mock_dir)
        - {SN}.py（launch，复制 simulation_launch.py 模板）
        - cloud_{SN}.yaml（设置 device_sn = SN）
        - device_{SN}.yaml（复制 device.yaml）
        - project_{SN}.yaml（复制 project.yaml）
        - truck{SN}.yaml（注意：truck 与 SN 间无下划线）
        - mock_truck_{SN}.yaml
        - mock_truck_{SN}.py（launch）
        - 更新 simulation_launch.py 中 KEY_* 常量
        - 更新 mock_truck_launch.py 中 default_config_name
     5. 基于模板 start_docker_template.sh 生成 start_docker_{SN}.sh
        - 写入 # VEHICLE_INDEX=N 标记
        - 替换端口、容器名、ROS_DOMAIN_ID 等变量
     6. 返回 {success, script_path, vehicle_index, ...}
```

### 5.5 地图提取流程

```
用户点击「提取地图」→ 选择 SN
  → POST /api/data-export/hdmap/extract {container_name, sn}
  → DataExportService.extract_hdmap(...)
     1. _ensure_ros2_container(name)
        - 校验容器存在 + 运行中 + 镜像含 ros2/humble/foxy
     2. _sanitize_sn(sn)：仅保留 [a-zA-Z0-9_-]
     3. _get_bag_storage(user, target_user)：返回 ~/robotruck_ros2/Docker/bags
     4. 时间戳：hdmap_{sn}_{YYYYmmdd_HHMMSS}.tar.gz
     5. 容器内打包：
        docker exec <name> bash -c \
          "cd /home/boonray/resource_data/{sn}/hdmap && tar -czf /tmp/{tar} -- ./*.pb.bin"
     6. 拷贝到宿主机：
        docker cp <name>:/tmp/{tar} {host_tar_path}
     7. 清理容器内临时文件：
        docker exec <name> rm -f /tmp/{tar}
     8. 返回 {success, file_path, file_name, size_bytes, size_mb}
  → 写审计日志
```

### 5.6 Bag 录制流程

```
启动录制：
  POST /api/data-export/bag/start {container_name}
  → DataExportService.start_bag_record(...)
     1. _ensure_ros2_container(name)
     2. 检查 _bag_sessions：若已有 recording 则 409 冲突
     3. 生成 bag_dir_name = rosbag2_{vehicle_id}_{timestamp}
     4. 容器内后台启动：
        docker exec -d <name> bash -c \
          "source /home/boonray/install/setup.bash && \
           cd /home/boonray && \
           nohup ros2 bag record -s mcap --all -o {bag_dir_name} \
           > /tmp/bag_record.log 2>&1 &"
     5. sleep(2) 后验证进程：
        docker exec <name> pgrep -f 'ros2 bag record'
     6. 写入 _bag_sessions[name] = {status: recording, started_at, ...}

停止录制：
  POST /api/data-export/bag/stop {container_name}
  → DataExportService.stop_bag_record(...)
     1. 检查 _bag_sessions：无 recording 则 409
     2. pkill -f 'ros2 bag record'（先 SIGTERM，3s 后仍存活则 pkill -9）
     3. 定位 bag 目录：
        - 优先：/home/boonray/{bag_dir_name}
        - 兜底：ls -dt /home/boonray/rosbag2_* | head -1
     4. 容器内打包：
        docker exec <name> tar -czf /tmp/{tar} -C /home/boonray {bag_dir_name}
     5. 拷贝到宿主机：
        docker cp <name>:/tmp/{tar} {host_tar_path}
     6. 清理容器内临时文件
     7. 更新 _bag_sessions[name].status = stopped
     8. 返回 {success, file_path, file_name, size_bytes, size_mb, duration_seconds}
```

### 5.7 WebSocket 终端流程

```
前端 _openTerminalImpl(containerId, mode, sourceRos2)
  → 创建 xterm Terminal 实例
  → new WebSocket('/ws/containers/{name}/shell?mode={mode}&source_ros2={sourceRos2}')
  → ws.onopen：发送初始尺寸 {rows, cols}
  → ws.onmessage：term.write(data)
  → term.onData(data)：ws.send(data)（用户输入）
  → term.onResize：ws.send(JSON.stringify({resize: [cols, rows]}))
  → ws.onclose：终端关闭

后端 /ws/containers/{name}/shell
  → 创建 docker exec -it <name> bash 会话
  → 双向流转发：stdin/stdout/stderr
  → mode=root 时附加 -u root
  → source_ros2=true 时先 source setup.bash
```

### 5.8 文件上传流程

```
前端：拖拽/选择文件
  → POST /api/files/upload (multipart/form-data)
  → 后端接收 UploadFile
  → validate_user_path(target_path, user_info)：路径遍历防御
  → 写入磁盘
  → 返回 {success, path, size}
```

### 5.9 用户隔离流程

```
普通用户操作：
  1. get_current_user → 获取 home_folder_path
  2. get_user_workspace_paths(user) → 返回用户隔离路径
  3. validate_user_path(requested, user) → 校验路径在 home_folder_path 下
  4. 任何越权路径访问 → HTTPException(403)

管理员操作：
  1. get_current_user → role == "admin"
  2. get_user_workspace_paths(admin, target_user)
     - target_user 为空：返回全局 ROS2_DEFAULT 路径
     - target_user 指定：返回目标用户路径
  3. validate_user_path(requested, admin, target_user)
     - 校验路径在目标用户的 home_folder_path 下
```

### 5.10 install 版本管理流程（v5.0 新增）

**上传（版本化解压 + 自动切换）**：

```
前端：选择 install 压缩包
  → POST /api/install/upload (multipart/form-data)
  → 保存到临时目录 _upload_<ts>/
  → extract_versioned_install(tmp_path, host_ws, fallback)
     - 压缩包顶层目录名（如 demo_install_v1.0/）作为版本名
     - 顶层直接是 install 内容时用 fallback 版本名
     - 版本名合法性校验（is_valid_version_name），非法字符拒绝/回退
     - 同名版本已存在 → 备份为 <名>.bak.<时间戳> 后替换，_prune_backups 保留 5 份
  → 生成 <host_ws>/<版本名>/install/ 目录
  → 写入用户记录 current_version = <版本名>（自动切换）
  → 返回 {success, version, auto_switched: true}
  → 前端刷新页面（版本全局生效）
```

**切换（首页下拉）**：

```
前端：版本下拉选择（含"旧版 install"回退项）
  → confirm 确认
  → POST /api/install/versions/switch {version, target_user?}
     - 空版本 = 回退旧版 <home>/install 路径（目录不存在也允许，等同未上传状态）
     - 非空版本：校验合法 + 必须在版本列表中
     - 普通用户传 target_user → 403；管理员可代切换
  → update_user(current_version)
  → 返回 {success, current_version, is_versioned}
  → 前端刷新页面
```

**版本生效范围（所有菜单操作跟随所选版本）**：

| 操作 | 生效方式 |
|------|---------|
| 仿真/话题/节点/服务/Action | `run_ros2_cmd` source `<版本>/install/setup.bash` |
| 脚本生成 | `launch_dir` 取自版本化 install |
| Docker 容器 | 容器挂载所选版本 install 目录到容器内固定路径 |
| install 目录树/删除 | 按版本化路径执行 |
| 前端展示 | 侧边栏版本徽章 + 首页版本区块 |

**删除版本**：

```
前端：版本列表中删除非当前版本
  → POST /api/install/delete {version}
  → 目录重命名为 <名>.deleted.<时间戳>（可恢复备份，非立即物理删除）
  → is_version_backup_entry 过滤，备份目录不会出现在版本列表中
  → 删除当前版本时：自动回退（current_version 清空 → 旧版 install 路径）
```

---

## 6. API 接口全量清单

### 6.1 认证 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login` | 公开 | 登录，返回 JWT |
| POST | `/api/auth/register` | 公开 | 注册（默认 user 角色） |
| POST | `/api/auth/logout` | 已登录 | 注销 |
| GET | `/api/auth/me` | 已登录 | 获取当前用户信息（v5.0：含 `current_version` 当前 install 版本） |
| GET | `/api/auth/permissions` | 已登录 | 获取权限列表 |
| GET | `/api/auth/onboarding` | 已登录 | 获取新手引导状态 |
| PUT | `/api/auth/onboarding` | 已登录 | 设置新手引导状态 |

### 6.2 用户管理 API（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/users` | 列出所有用户 |
| POST | `/api/admin/users` | 创建用户 |
| PUT | `/api/admin/users/{user_id}` | 更新用户 |
| DELETE | `/api/admin/users/{user_id}` | 删除用户 |
| GET | `/api/admin/audit-logs` | 查看审计日志 |
| DELETE | `/api/admin/audit-logs` | 清除审计日志 |

### 6.3 系统状态 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/status` | 系统状态文本 |
| GET | `/api/system/monitor` | CPU/内存/GPU/进程监控 |
| GET | `/api/system/monitor/gpu-detail` | GPU 详情 |
| GET | `/api/system/check` | 健康检查 |
| POST | `/api/system/check/fix` | 自动修复 |
| GET | `/api/system/resource-leaks` | 资源泄漏检测 |
| GET | `/api/system/sudo-check` | sudo 权限检查 |
| POST | `/api/system/auth/save` | 保存 sudo 密码（托管） |
| GET | `/api/system/auth/status` | sudo 状态 |

### 6.4 系统工具 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/system/apt-source` | 切换 apt 源 |
| POST | `/api/system/install` | 安装 apt 包 |
| POST | `/api/system/uninstall` | 卸载 apt 包 |
| POST | `/api/system/certificates` | 证书切换 |
| POST | `/api/system/sync` | 文件夹同步 |
| POST | `/api/system/cloud-config` | 云平台配置 |
| POST | `/api/system/clean` | 清理临时文件 |
| POST | `/api/system/open-folder` | 打开文件夹 |
| GET | `/api/system/cloud-env` | 获取云环境 |
| GET | `/api/system/cloud-status` | 云平台状态 |
| GET | `/api/system/remote-hosts` | 远程主机列表 |
| POST | `/api/system/remote-hosts` | 添加远程主机 |
| DELETE | `/api/system/remote-hosts/{name}` | 删除远程主机 |
| POST | `/api/system/remote-hosts/{name}/test` | 测试远程主机连接 |
| GET | `/api/system/plugins` | 插件列表 |
| POST | `/api/system/plugins` | 启用插件 |
| DELETE | `/api/system/plugins/{name}` | 禁用插件 |
| POST | `/api/system/plugins/{name}/execute` | 执行插件 |
| GET | `/api/system/api-settings` | API 设置 |
| POST | `/api/system/api-settings` | 更新 API 设置 |

### 6.5 文件管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/files/list` | 列出目录 |
| GET | `/api/files/download` | 下载文件 |
| POST | `/api/files/delete` | 删除文件 |
| POST | `/api/files/mkdir` | 创建目录 |
| POST | `/api/files/upload` | 上传文件 |
| POST | `/api/files/rename` | 重命名 |
| POST | `/api/files/sync-bags` | 同步 bag 文件 |

### 6.6 ROS2 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ros2/simulation/start` | 启动仿真 |
| POST | `/api/ros2/cmd_vel` | 发布速度命令 |
| POST | `/api/ros2/topic/pub` | 发布话题消息 |
| POST | `/api/ros2/topic/kill` | kill 话题 |
| POST | `/api/ros2/node/kill` | kill 节点 |
| POST | `/api/ros2/service/kill` | kill 服务 |
| GET | `/api/ros2/topics` | 话题列表 |
| GET | `/api/ros2/topic/{name}/info` | 话题信息 |
| GET | `/api/ros2/topic/{name}/echo` | 话题数据 echo |
| GET | `/api/ros2/nodes` | 节点列表 |
| GET | `/api/ros2/node/{name}/info` | 节点信息 |
| GET | `/api/ros2/services` | 服务列表 |
| GET | `/api/ros2/service/{name}/type` | 服务类型 |
| POST | `/api/ros2/service/{name}/call` | 调用服务 |
| GET | `/api/ros2/actions` | Action 列表 |
| GET | `/api/ros2/action/{name}/info` | Action 信息 |
| POST | `/api/ros2/action/{name}/send_goal` | 发送 goal |

### 6.7 Docker API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/docker/containers` | 容器列表 |
| POST | `/api/docker/container/{id}/start` | 启动容器 |
| POST | `/api/docker/container/{id}/stop` | 停止容器 |
| POST | `/api/docker/container/{id}/restart` | 重启容器 |
| POST | `/api/docker/container/{id}/rviz` | 启动 RVIZ |
| DELETE | `/api/docker/container/{id}` | 删除容器 |
| GET | `/api/docker/container/{id}/logs` | 容器日志 |
| POST | `/api/docker/container/{id}/exec` | 执行命令 |
| GET | `/api/docker/container/{id}/roslogs` | ROS 日志 |
| POST | `/api/docker/container/{id}/update` | 更新资源 |
| POST | `/api/docker/container/{id}/commit` | 提交镜像 |
| GET | `/api/docker/container/{id}/foxglove-url` | Foxglove URL |
| POST | `/api/docker/container/{id}/visualize` | 启动可视化 |
| POST | `/api/docker/stop-all-ros2` | 停止所有 ROS2 容器 |
| POST | `/api/docker/sync-time` | 同步容器时间 |
| GET | `/api/docker/images` | 镜像列表 |
| POST | `/api/docker/images/load` | 加载镜像 |
| DELETE | `/api/docker/images/{name}` | 删除镜像 |

### 6.8 可视化 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/visualization/methods` | 可视化方案列表 |
| POST | `/api/visualization/set-default` | 设置默认方案 |
| POST | `/api/visualization/method/{method_key}` | 启用/禁用方案 |
| POST | `/api/visualization/order` | 调整顺序 |

### 6.9 脚本管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scripts/launch-files` | launch 文件列表 |
| POST | `/api/scripts/generate` | 生成脚本 |
| GET | `/api/scripts/list` | 脚本列表 |
| DELETE | `/api/scripts/clear-all` | 清空所有脚本 |
| GET | `/api/scripts/default-paths` | 默认路径 |
| GET | `/api/scripts/quota` | 配额状态 |
| GET | `/api/scripts/{name}/content` | 脚本内容 |
| PUT | `/api/scripts/{name}` | 编辑脚本 |
| DELETE | `/api/scripts/{name}` | 删除脚本 |
| POST | `/api/scripts/batch-execute` | 批量执行 |
| POST | `/api/scripts/execute` | 执行单个 |
| POST | `/api/scripts/remove-gpu` | 移除 GPU 配置 |

### 6.10 install 目录 API（v5.0 版本化）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/install/status` | install 状态（v5.0：含 `current_version` / `is_versioned` / `versions`，install 路径随所选版本） |
| POST | `/api/install/upload` | 上传 install 包（v5.0：版本化解压为 `<版本>/install/`，成功后自动切换并返回 `version`） |
| GET | `/api/install/versions` | **v5.0 新增**：版本列表 + 当前生效版本（管理员可传 `target_user` 查看指定用户） |
| POST | `/api/install/versions/switch` | **v5.0 新增**：切换版本（body：`{version, target_user?}`；空 version 回退旧版路径） |
| GET | `/api/install/tree` | install 目录树（v5.0：`version` 参数指定版本，默认当前版本） |
| POST | `/api/install/delete` | 删除 install（v5.0：`version` 参数指定版本；重命名为 `.deleted.<时间戳>` 备份；删当前版本自动回退） |
| GET | `/api/install/workspace-users` | 工作空间用户列表 |
| POST | `/api/install/deploy` | 部署 install |

### 6.11 bk 备份 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/system/bk/clean` | 清理备份 |
| POST | `/api/system/bk/copy-from-install` | 从 install 拷贝 |
| GET | `/api/system/bk/backups` | 备份列表 |
| POST | `/api/system/bk/rollback` | 回滚 |
| GET | `/api/system/bk/history` | 历史记录 |

### 6.12 端口 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ports/used` | 已用端口列表 |

### 6.13 红绿灯 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/traffic-light/status` | 模拟器状态 |
| POST | `/api/traffic-light/start` | 启动 MQTT 模拟器 |
| POST | `/api/traffic-light/stop` | 停止 |
| GET | `/api/traffic-light/light-status` | 灯状态 |
| POST | `/api/traffic-light/set-light-state` | 设置灯状态 |
| POST | `/api/traffic-light/set-mode` | 设置模式 |
| GET | `/api/timer-traffic-light/status` | 定时模拟器状态 |
| POST | `/api/timer-traffic-light/start` | 启动定时模拟器 |
| POST | `/api/timer-traffic-light/stop` | 停止定时模拟器 |

### 6.14 批量生成 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/batch/generate` | 批量生成车辆配置 |

### 6.15 车辆配置 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/truck/config/list` | 配置列表 |
| GET | `/api/truck/config/{filename}` | 获取配置 |
| PUT | `/api/truck/config/{filename}` | 更新配置 |

### 6.16 白名单 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/whitelist` | 白名单列表 |
| POST | `/api/system/whitelist` | 添加前缀 |
| DELETE | `/api/system/whitelist/{prefix}` | �除前缀 |

### 6.17 帮助页面 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/help/{page}` | 获取帮助页 |
| GET | `/api/system/help-pages` | 帮助页列表 |
| POST | `/api/system/help` | 创建/更新帮助页 |
| DELETE | `/api/system/help/{page}` | 删除帮助页 |

### 6.18 故障注入 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/fault/inject` | 注入故障 |
| POST | `/api/fault/clear` | 清除故障 |
| GET | `/api/fault/list` | 当前故障列表 |
| GET | `/api/fault/history` | 故障历史 |
| POST | `/api/fault/history/clear` | 清除历史 |

### 6.19 数据导出 API（v4.0 新增）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/data-export/hdmap/sn-list?container_name=` | data-export | 列出 SN |
| POST | `/api/data-export/hdmap/extract` | data-export | 提取地图 |
| POST | `/api/data-export/bag/start` | data-export | 开始录制 |
| POST | `/api/data-export/bag/stop` | data-export | 停止录制 |
| GET | `/api/data-export/bag/status?container_name=` | data-export | 录制状态 |
| GET | `/api/data-export/bag/list?container_name=&target_user=` | data-export | 文件列表 |
| POST\|DELETE | `/api/data-export/bag/delete` | data-export | 删除文件 |
| GET | `/api/data-export/bag/download?file=&target_user=` | data-export | 下载文件 |

### 6.20 WebSocket API

| 路径 | 说明 |
|------|------|
| `/ws` | 通用 WebSocket（系统日志广播） |
| `/ws/containers/{name}/logs` | 容器实时日志流 |
| `/ws/containers/{name}/shell` | 容器终端（xterm） |

### 6.21 工单 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tickets/meta` | 工单元数据 |
| POST | `/api/tickets` | 创建工单 |
| GET | `/api/tickets` | 工单列表（分页/过滤） |
| GET | `/api/tickets/{id}` | 工单详情 |
| PUT | `/api/tickets/{id}` | 更新工单 |
| PATCH | `/api/tickets/{id}` | 部分更新 |
| DELETE | `/api/tickets/{id}` | 删除工单 |
| POST | `/api/tickets/{id}/replies` | 添加回复 |
| GET | `/api/tickets/{id}/replies` | 回复列表 |
| POST | `/api/tickets/attachments` | 上传附件 |
| GET | `/api/tickets/attachments/{date_dir}/{user_id}/{filename}` | 下载附件 |

---

## 7. 配置体系

### 7.1 配置文件 `backend/config.json`

| 章节 | 关键字段 | 说明 |
|------|---------|------|
| `server` | `host` / `port` / `ssl_key` / `ssl_cert` | 监听地址、端口、SSL |
| `cors` | `allow_origins` / `allow_origin_regex` | 跨域白名单 |
| `plugins` | `execution_enabled` | 插件执行开关 |
| `security` | `jwt_secret` / `jwt_algorithm` / `jwt_expire_minutes` / `bcrypt_rounds` | JWT 与密码 |
| | `rate_limit_enabled` / `rate_limit_requests` / `rate_limit_period` | 速率限制 |
| | `input_filter_enabled` / `input_filter_whitelist` | 命令过滤白名单 |
| | `audit_enabled` / `audit_log_file` | 审计日志 |
| `database` | `type` | `json` / `supabase` |
| | `path` / `audit_path` | JSON 模式文件路径 |
| | `url` / `key` / `service_role_key` | Supabase 连接 |
| `docker` | `default_image` / `use_sudo` | Docker 配置 |
| `ros2_workspace` | `host_ws` / `host_install` / `container_install` / `container_bag_path` | ROS2 工作空间（v5.0：`host_install` 仅作为旧版回退路径，实际 install 路径由用户 `current_version` 动态解析） |

### 7.2 v5.0 版本管理相关配置说明

- **无新增配置项**：版本管理完全基于用户工作空间目录扫描，不引入额外配置
- **Supabase 部署**：需执行 `ALTER TABLE public.users ADD COLUMN IF NOT EXISTS current_version TEXT DEFAULT '';`（已包含在 `data/ros2_web_supabase.sql`）；服务启动时自动探测缺失并在日志输出待执行 SQL
- **JSON 部署**：无需操作，`data/data.json` 中用户记录自动补全 `current_version` 字段
- **兼容性**：旧版 `<home>/install` 目录继续可用——未选择版本（`current_version` 为空）时自动回退旧路径，存量环境升级 v5.0 后行为不变