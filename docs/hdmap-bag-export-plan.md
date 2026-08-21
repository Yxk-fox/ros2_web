    ================================================================================
                   数据导出功能开发方案文档（解耦版）
================================================================================

版权所有：上海伯镭科技有限公司
@File    :  hdmap-bag-export-plan.md
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  新增「提取地图」「录制 ROS2 Bag」「Web 下载 Bag」三大功能的
            开发方案文档。遵循 4.0-decoupled 架构与解耦开发规范，
            不修改任何既有代码，仅追加新文件与末尾追加注册语句。

            文档结构：
            1. 需求概述
            2. 现有代码分析（可复用资产）
            3. 整体设计（含用户隔离与权限矩阵）
            4. 后端 API 设计
            5. 后端实现细节（services 层 + routers 层）
            6. 前端设计
            7. 关键流程时序
            8. 安全与异常处理
            9. 文件改动清单
           10. 验收清单
           11. 后续可选增强
           12. 解耦架构符合性说明
================================================================================

# 数据导出功能开发方案文档

> **版本**：v2.0（对齐 4.0-decoupled 实际实现）
> **更新**：2026 年 8 月
> **范围**：新增「提取地图」「录制 ROS2 Bag（mcap 格式）」「下载 Bags」三大功能，不修改任何既有代码
> **架构基线**：v4.0-decoupled（core / database / services / routers 四层分离）
> **依赖代码**：`backend/services/docker_manager.py`、`backend/core/workspace.py`、`frontend/js/sj_script.js`
> **遵循规范**：[`redame/README.txt`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/redame/README.txt)「解耦开发规范」章节
> **权限**：统一使用 `data-export` 面板权限（在 `backend/core/constants.py` 的 `ALL_PANELS` 中追加）

---

## 一、需求概述

基于运维场景，提供三个一键式数据导出与下载能力，**目标对象为当前已选中的 ROS2 容器**：

| 功能 | 输入 | 输出（宿主机） | Web 下载 |
|------|------|-----------------|----------|
| 提取地图 (hdmap) | 容器 + 车辆 SN | `~/<bag_storage>/hdmap_<SN>_<时间戳>.tar.gz` | ✅ 支持 |
| 录制 ROS2 Bag | 容器 + 录制时长（或手动停止） | `~/<bag_storage>/rosbag2_<时间戳>.tar.gz` | ✅ 支持 |
| Web 下载到本地 | 导出文件名 | — | ✅ 浏览器下载到用户电脑 |

### 1.1 用户隔离红线

- **导出落地**：bag/hdmap 文件**只能**写入当前调用者（或管理员指定的 `target_user`）的 `bag_storage` 目录，严禁越权写入他人空间
- **下载访问**：普通用户**只能**下载自己 `bag_storage` 下的文件；管理员可指定 `target_user` 下载目标用户的文件
- **路径校验链**：导出 → 落地 → 下载三步均须通过 `validate_user_path` + `_safe_join` 双重校验

### 用户期望的原生命令（来自需求）

**1. 提取地图**
```bash
docker exec 容器ID/容器名称 bash -c "cd /home/boonray/resource_data/车辆sn号/hdmap && tar -czf - *.pb.bin" > ~/hdmap.tar.gz
```

**2. 录制 ros2bag（mcap 格式）**
```bash
source /home/boonray/install/setup.bash
cd /home/boonray
ros2 bag record -s mcap --all
```

**3. 从宿主机拷贝压缩包**（保持容器运行，宿主机执行）
```bash
docker cp 容器名称或ID:/home/boonray/rosbag2_2026_08_19-15_41_48.tar.gz /宿主机目标路径/
```

**4. 通过 Web 下载到本地电脑**
```
GET /api/data-export/bag/download?file=<文件名>&target_user=<可选>
```
> 专用下载接口，独立于 `/api/files/download`，权限为 `data-export`，避免普通用户需被授予 `tools` 权限才能下载 bag。

---

## 二、现有代码分析（可复用资产）

### 2.1 后端可复用组件

#### Docker 管理服务 [`backend/services/docker_manager.py`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/services/docker_manager.py)

| 方法 | 说明 | 复用方式 |
|------|------|----------|
| `DockerManager.run_cmd(cmd, timeout=30)` | 执行 shell，返回 `(rc, stdout, stderr)` | 直接调用 |
| `DockerManager._docker(*args)` | 拼装 `docker` 命令前缀（含 sudo 判断） | 直接调用 |
| `DockerManager.exec_command(name, command, detach=False, timeout=15)` | 容器内 exec，支持 `-d` 后台模式 | **录制 bag 用 detach=True** |
| `DockerManager.list_containers(running_only, filter_name, filter_image)` | 列出容器 | 校验容器存在/运行 |

> **关键点**：`exec_command` 已支持 `detach=True`（即 `docker exec -d`），完美适配 `ros2 bag record -a` 长时任务的后台启动需求。

#### 现有 Bag 同步参考实现 [`backend/routers/api.py:833-885`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/api.py#L833-L885)

`@router.post("/api/files/sync-bags")` 已实现了「容器 → 宿主机」的 `docker cp` 流程，是新功能的最佳参考模板：

```python
# 已有模式：先在容器内查找 bag 目录，再 docker cp 到宿主机
DockerManager._docker("exec", container_name, "bash", "-c", f"ls -d {bag_path}/rosbag2_* 2>/dev/null || true")
DockerManager._docker("cp", f"{container_name}:{bag_dir}", dest_dir)
```

#### 专用 Web 文件下载接口（独立实现） [`backend/routers/data_export.py`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/data_export.py)

```python
@router.get("/api/data-export/bag/download")
async def download_bag_file(
    file: str,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    # 文件名白名单校验（禁止分隔符、路径穿越）
    bag_storage = DataExportService._get_bag_storage(current_user, target_user)
    full_path = os.path.normpath(os.path.join(bag_storage, file))
    if not full_path.startswith(os.path.normpath(bag_storage)):
        raise HTTPException(status_code=400, detail="非法路径访问")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(full_path, filename=os.path.basename(full_path))
```

| 辅助函数 | 位置 | 作用 |
|----------|------|------|
| `DataExportService._get_bag_storage(current_user, target_user)` | [data_export_service.py](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/services/data_export_service.py) | 内部调用 `get_user_workspace_paths` 解析 `bag_storage`，自动创建目录 |
| `os.path.normpath + startswith` | 路由层 | 防止 `../etc/passwd` 路径遍历 |

> **设计要点**：bag 下载**不**复用既有 `/api/files/download`，而是新建专用接口。原因：
> 1. 既有接口依赖 `tools` 面板权限，普通用户通常没有该权限，但需要下载自己的 bag；
> 2. 专用接口使用 `data-export` 权限，与功能面板权限统一，便于管理员分配；
> 3. 参数更简洁（仅 `file=<文件名>`），不暴露 `folder_type` 概念，降低误用风险。

#### 既有 Web 文件列表接口 [`backend/routers/api.py:663-711`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/api.py#L663-L711)

`GET /api/files/list?folder_type=bags&subpath=` 返回用户 `bag_storage` 下所有文件，可用于前端展示「已导出的 bag 列表」供用户选择下载。

#### 工作空间路径 [`backend/core/workspace.py:73-119`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/core/workspace.py#L73-L119)

`get_user_workspace_paths(current_user, target_user)` 返回用户隔离路径，新功能必须沿用：

| 字段 | 默认值（管理员） | 普通用户 | 用途 |
|------|------------------|----------|------|
| `bag_storage` | `~/robotruck_ros2/Docker/bags` | `~/robotruck_ros2/<user>/Docker/bags` | **导出文件落地的宿主机目录** |
| `container_install` | `/home/boonray/install` | 同左 | `source install/setup.bash` 路径 |
| `container_bag_path` | `/home/nvidia/data/.boonray/bagfiles` | 同左 | 容器内 bag 默认路径 |
| `container_bag_path_alt` | `/home/boonray/.boonray/bagfiles` | 同左 | 容器内 bag 备选路径 |

##### 实际目录结构（以服务器 `192.168.9.150` 为例）

```
fox@fox-Server:~/robotruck_ros2$
├── Docker/                              ← 管理员的 Docker 工作目录
│   └── bags/                            ← ★ 管理员 bag_storage
│       ├── rosbag2_2026_08_19-15_41_48.tar.gz
│       └── hdmap_hytz_3788_20260821_153000.tar.gz
├── ke_yunxiao/                          ← 用户 ke_yunxiao 的 home_folder_path
│   └── Docker/
│       └── bags/                        ← ★ ke_yunxiao bag_storage
│           └── rosbag2_xxx.tar.gz
└── honglan_wang/                        ← 用户 honglan_wang 的 home_folder_path
    └── Docker/
        └── bags/                        ← ★ honglan_wang bag_storage
            └── rosbag2_xxx.tar.gz
```

| 用户身份 | `home_folder_path` | `bag_storage` |
|----------|---------------------|----------------|
| 管理员（admin） | `~/robotruck_ros2`（[`supabase_db.py:82`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/database/supabase_db.py#L82) 写死） | `~/robotruck_ros2/Docker/bags` |
| 普通用户 `ke_yunxiao` | `~/robotruck_ros2/ke_yunxiao`（[`workspace.py:135`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/core/workspace.py#L135) `create_user_workspace` 创建） | `~/robotruck_ros2/ke_yunxiao/Docker/bags` |
| 普通用户 `honglan_wang` | `~/robotruck_ros2/honglan_wang` | `~/robotruck_ros2/honglan_wang/Docker/bags` |

> **隔离规则**：bag 文件**永远只落地到** `<home_folder_path>/Docker/bags`，`home_folder_path` 由 `get_user_workspace_paths` 根据 `current_user` + 可选的 `target_user` 解析。

#### 安全与权限

- **权限依赖**：`require_permission('tools')`（已有），管理员或拥有 `tools` 面板权限的用户可用
- **路径校验**：`validate_user_path(path, current_user, target_user)` 防止越权访问
- **命令过滤**：`sanitize_command()` 仅在 `INPUT_FILTER_ENABLED=True` 时启用，默认关闭；白名单已含 `ros2/docker/bash/tar/source`，无需调整

#### 容器内关键路径常量（来自 `config.json`）

```json
{
  "container_install": "/home/boonray/install",
  "container_bag_path": "/home/nvidia/data/.boonray/bagfiles",
  "container_bag_path_alt": "/home/boonray/.boonray/bagfiles"
}
```

需求中的 `/home/boonray/resource_data/<SN>/hdmap` 是容器内地图目录，**SN 为路径变量**。

### 2.2 前端可复用组件 [`frontend/js/sj_script.js`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/frontend/js/sj_script.js)

| 全局变量/函数 | 位置 | 复用方式 |
|---------------|------|----------|
| `selectedContainerId` / `selectedContainerName` | L70-71 | 取当前选中容器 |
| `currentContainerId` | L53 | 取当前操作容器 |
| `selectContainer(id, name)` | L2266 | 容器选择已在 docker 面板提供 |
| `hasPermission(panel)` | L1218 | 权限校验 |
| `apiGet` / `apiPost` | 全局 | API 调用封装 |
| `showToast(msg, type)` | 全局 | 消息提示 |
| `customConfirm(msg, cb)` | 全局 | 二次确认 |
| `currentTargetUser` | 全局 | 管理员切换用户空间 |

#### 前端已有 SN 输入 [`frontend/index.html:908`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/frontend/index.html#L908)

`panel-tools` 已有 SN 输入框 `#batchIdentifier`（placeholder `输入SN（如 hytz_3788）`），新功能可复用或独立提供。

---

## 三、整体设计

### 3.1 设计原则

1. **零侵入**：不修改任何既有函数实现，仅追加新文件/新路由/新前端片段；前端通过 `MutationObserver` 动态向容器列表的操作按钮行注入新按钮，不修改 `sj_script.js` 的容器渲染逻辑
2. **复用既有架构**：沿用 `DockerManager` / `get_user_workspace_paths` / `require_permission` / `validate_user_path` 既有能力
3. **用户隔离（红线）**：
   - 导出文件**只能**落地到调用者（或管理员指定的 `target_user`）的 `bag_storage`
   - 下载文件**只能**访问调用者（或管理员指定的 `target_user`）的 `bag_storage`
   - 普通用户传 `target_user` 会被 `get_user_workspace_paths` / `DataExportService._get_bag_storage` **静默忽略**，仍操作自己的空间
4. **容器选中前置**：所有操作校验 `selectedContainerId` 非空且容器运行中
5. **专用下载接口**：`GET /api/data-export/bag/download` 独立于既有 `/api/files/download`，权限统一为 `data-export`，不依赖 `tools` 权限
6. **按钮位置**：提取地图、录制 Bag、下载 Bags、可视化按钮与「更多」按钮位于同一排（`.action-buttons` 容器内），按操作频率从左到右排列
7. **录制格式**：统一使用 `mcap` 格式录制（`ros2 bag record -s mcap --all`）

### 3.2 用户隔离与权限矩阵

#### 3.2.1 角色权限矩阵

| 操作 | 普通用户 | 管理员 | 管理员 + `target_user=ke_yunxiao` |
|------|----------|--------|------------------------|
| 提取地图（到自己空间） | ✅ 落地 `~/robotruck_ros2/<self>/Docker/bags/` | ✅ 落地 `~/robotruck_ros2/Docker/bags/` | ✅ 落地 `~/robotruck_ros2/ke_yunxiao/Docker/bags/` |
| 提取地图（携带 `target_user` 试图越权） | ⚠️ **静默降级**到自己空间（不报 403） | — | — |
| 录制 Bag + 停止导出（到自己空间） | ✅ | ✅ | ✅ |
| 录制 Bag（携带 `target_user` 试图越权） | ⚠️ **静默降级**到自己空间 | — | — |
| 列出自己的 bags | ✅ | ✅ | ✅（列 ke_yunxiao 的） |
| 列出他人 bags（携带 `target_user`） | ⚠️ **静默降级**列出自己的 | — | — |
| 下载自己的 bag | ✅ | ✅ | ✅（下载 ke_yunxiao 的） |
| 下载他人的 bag（携带 `target_user`） | ⚠️ **静默降级**只能下载自己的 | — | — |
| 删除自己的 bag | ✅（既有接口） | ✅ | ✅ |
| 路径遍历 `subpath=../etc/passwd` | ❌ 400 | ❌ 400 | ❌ 400 |

> **关键发现（既有行为）**：普通用户携带 `target_user` 参数时，既有 `get_user_workspace_paths` 与 `validate_user_path` **不会抛 403**，而是**静默忽略 `target_user`**，仍然操作自己的空间。这是更安全的「降级」设计（用户感知不到他人存在，也无法越权）。新功能必须沿用此既有行为。

##### 既有隔离逻辑代码佐证 [`backend/core/workspace.py:18-31`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/core/workspace.py#L18-L31)

```python
def validate_user_path(requested_path, user_info, target_user=None):
    # 管理员无 target_user 时全局操作，直接放行
    if user_info.get("role") == "admin" and not target_user:
        return True
    
    # ★ 关键：只有"管理员 + target_user"才会切换 check_user
    check_user = user_info
    if target_user and user_info.get("role") == "admin":   # ← 普通用户不进入此分支
        target_user_obj = db.get_user(target_user) or db.get_user_by_id(target_user)
        if target_user_obj:
            check_user = target_user_obj
    
    user_root = check_user.get("home_folder_path")   # ← 普通用户的 check_user 仍是自己
    # 校验 requested_path 是否在 user_root 下 → 普通用户只能通过自己的路径
```

#### 3.2.2 路径校验三道关

```
HTTP 请求 → require_permission('tools') ── 面板权限校验
         ↓
         get_user_workspace_paths(current_user, target_user)
         ↓ 管理员 + target_user → 切换到目标用户的 home_folder_path
         ↓ 普通用户 + target_user → 静默忽略，仍用自己的 home_folder_path
         ↓
         validate_user_path（用户隔离根）
         ↓
         _safe_join（防路径遍历）
         ↓
         文件操作
```

| 校验关 | 函数 | 作用 |
|--------|------|------|
| 第 1 关 | `require_permission('tools')` | 面板权限，普通用户须被授予 `tools` |
| 第 2 关 | `validate_user_path(path, current_user, target_user)` | 校验 `path` 是否在 `check_user.home_folder_path` 下；普通用户传 `target_user` 静默忽略，管理员切换 `check_user` |
| 第 3 关 | `_safe_join(root, subpath)` | 拒绝 `../` 跨目录 |

> **结论**：`/api/files/download` 已通过这三道关，新功能无需重复实现。

#### 3.2.3 导出阶段的强制隔离

新功能在导出阶段显式校验 `bag_storage` 落地路径（与既有 `/api/files/sync-bags` 等接口写法一致）：

```python
# 所有导出接口的标准开头（与既有 sync_bags 同款写法）
workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
bag_storage = workspace_paths["bag_storage"]          # 普通用户传入 target_user 时仍解析为自己的
validate_user_path(bag_storage, current_user, target_user)  # 双保险
os.makedirs(bag_storage, exist_ok=True)
```

**三种典型场景的实际行为**：

| 调用者 | 携带 `target_user` | `bag_storage` 实际落地路径 |
|--------|---------------------|----------------------------|
| 管理员 | 无 | `~/robotruck_ros2/Docker/bags/`（管理员空间） |
| 管理员 | `ke_yunxiao` | `~/robotruck_ros2/ke_yunxiao/Docker/bags/`（ke_yunxiao 空间） |
| 普通用户 `honglan_wang` | 无 | `~/robotruck_ros2/honglan_wang/Docker/bags/`（自己空间） |
| 普通用户 `honglan_wang` | `ke_yunxiao`（试图越权） | `~/robotruck_ros2/honglan_wang/Docker/bags/`（**静默降级到自己的空间**） |

> 即普通用户**不可能**将 bag 写到他人空间，也不可能下载他人 bag，既有隔离机制已闭环。

### 3.3 模块划分（对齐 4.0-decoupled 四层架构）

按 README「解耦开发规范」要求：业务逻辑放 services/、路由放 routers/、公共工具放 core/、app.py 仅做挂载。本功能据此落地：

```
新增文件（按四层架构归类）：
├─ services 层（业务逻辑）
│  └─ backend/services/data_export_service.py    # DataExportService 类：hdmap/bag 的 Docker 操作
│
├─ routers 层（接口）
│  └─ backend/routers/data_export.py             # APIRouter：接收请求→调用 service→返回响应
│
├─ frontend 层（UI）
│  └─ frontend/js/panels/data_export.js          # 复用既有 panels/ 目录约定（参考 terminal.js）
│                                                 # 通过 MutationObserver 向容器列表注入按钮到操作按钮行
│
└─ docs 层（本方案）
   └─ docs/hdmap-bag-export-plan.md

追加修改（仅末尾追加 / 列表加一项，不改既有逻辑）：
├─ backend/routers/api.py          # 末尾追加 include_router(data_export_router)
├─ backend/core/constants.py      # ALL_PANELS 末尾追加 'data-export'
├─ frontend/index.html             # 底部追加 <script src="js/panels/data_export.js"> 引用
│
│ ★ 注意：前端不再新建 panel card，而是通过 MutationObserver 动态注入按钮到
│   容器列表每行的 .action-buttons 容器中（与「更多」按钮同一排）。
│   这样既实现了"零侵入"（不改 sj_script.js），又保持了操作便捷性。

完全复用既有（零改动）：
├─ core/workspace.py              # get_user_workspace_paths / validate_user_path
├─ services/docker_manager.py     # exec_command(detach=True) / _docker / run_cmd
├─ database/                      # db.add_audit_log
└─ deps.py                        # require_permission('data-export')
```

> **架构符合性自查**（对应 README 解耦开发规范 6 条）：
> 1. ✅ 新增功能先在 `services/` 实现业务逻辑（`data_export_service.py`）
> 2. ✅ `routers/` 只接收请求→调用 service→返回响应（`data_export.py` 无业务逻辑）
> 3. ✅ 公共工具复用 `core/`（`workspace.py`），不复制工具函数
> 4. ✅ 不在 `app.py` 写业务代码，仅在 `api.py` 末尾 `include_router`
> 5. ✅ 数据库访问通过 `database/` 的 `db.add_audit_log`
> 6. ✅ 日志统一使用 `from logger import logger`

> 注：`constants.py` 中 `ALL_PANELS` 仅追加一个字符串元素 `'data-export'`，不修改任何既有项；管理员默认拥有全部面板权限，普通用户需管理员在用户管理里勾选 `data-export`。

### 3.4 数据流与隔离边界示意

```
┌─────────┐  录制/提取   ┌──────────┐  docker cp   ┌──────────────────┐
│  容器    │ ──────────▶ │ 后端服务  │ ───────────▶ │ 用户 bag_storage │
│ (boonray)│             │  DataExportService      │ (home_folder_path)│
└─────────┘             └──────────┘               └─────────┬──────┘
                                                            │ _get_bag_storage
                                                            │ (含用户隔离)
                                                            ▼
                                                    ┌──────────────────┐
                            GET /api/data-export/bag/download │  浏览器下载       │
              ┌─────────┐ ◀────────────────────────────────│  到用户电脑       │
              │ 用户电脑 │  权限 data-export + 文件名白名单   └──────────────────┘
              └─────────┘
```

> 服务器侧 bag 只能落在用户自己的 `bag_storage`；浏览器下载使用专用接口，带 `data-export` 权限校验与文件名白名单，严格限制访问范围。

---

## 四、后端 API 设计

所有新接口统一前缀 `/api/data-export/`，权限统一 `require_permission('data-export')`（专用面板权限）。

### 4.1 提取地图

#### `POST /api/data-export/hdmap/extract`

**请求体**
```json
{
  "container_name": "ros2_fox_hytz_3788",
  "sn": "hytz_3788",
  "target_user": null
}
```

**处理流程**
1. 校验 `container_name` 非空且在运行中（`DockerManager.list_containers`）
2. 校验 `sn` 合法（正则 `^[A-Za-z0-9_-]+$`，防注入）
3. 容器内探测地图目录：`docker exec <容器> bash -c "ls /home/boonray/resource_data/<SN>/hdmap/*.pb.bin 2>/dev/null | wc -l"`
4. 若 `.pb.bin` 数量为 0，返回失败提示
5. 容器内打包到 `/tmp/hdmap_<SN>_<时间戳>.tar.gz`：
   ```bash
   docker exec <容器> bash -c "cd /home/boonray/resource_data/<SN>/hdmap && tar -czf /tmp/hdmap_<SN>_<ts>.tar.gz *.pb.bin"
   ```
6. 宿主机落地路径：`<bag_storage>/hdmap_<SN>_<时间戳>.tar.gz`，`os.makedirs(bag_storage, exist_ok=True)`
7. `validate_user_path(bag_storage, current_user, target_user)` 校验
8. `docker cp <容器>:/tmp/hdmap_<SN>_<ts>.tar.gz <bag_storage>/`
9. 清理容器内临时文件：`docker exec <容器> rm -f /tmp/hdmap_<SN>_<ts>.tar.gz`
10. 审计日志：`db.add_audit_log(username, "extract_hdmap", f"{container_name} SN={sn}")`
11. 返回宿主机落地路径与文件大小

**响应**
```json
{
  "success": true,
  "message": "地图已导出",
  "host_path": "/home/fox/robotruck_ros2/Docker/bags/hdmap_hytz_3788_20260821_153000.tar.gz",
  "size_mb": 12.5,
  "file_count": 3
}
```

> **为何采用「容器内打包 + docker cp」而非 `> ~/hdmap.tar.gz` 流式重定向？**
> `DockerManager.run_cmd` 使用 `text=True` 模式，二进制 tar.gz 经 stdout 会被解码破坏。采用两步法可避免对既有方法的修改，且失败时可清理中间文件。

#### `POST /api/data-export/hdmap/list-sns`

**请求体**
```json
{ "container_name": "ros2_fox_hytz_3788" }
```

**用途**：列出容器内 `/home/boonray/resource_data/` 下所有 SN 目录，供前端下拉选择，避免手输错误。

```bash
docker exec <容器> bash -c "ls -d /home/boonray/resource_data/*/ 2>/dev/null | xargs -n1 basename"
```

**响应**
```json
{
  "success": true,
  "sns": ["hytz_3788", "hytz_3789"],
  "container_name": "ros2_fox_hytz_3788"
}
```

#### `POST /api/data-export/hdmap/preview`

**请求体**：`{ "container_name", "sn" }`

**用途**：预览该 SN 下 `hdmap` 目录的 `.pb.bin` 文件清单与大小，便于确认。

```bash
docker exec <容器> bash -c "ls -lh /home/boonray/resource_data/<SN>/hdmap/*.pb.bin 2>/dev/null"
```

### 4.2 录制 ROS2 Bag（mcap 格式）

录制是长时任务，拆为 `start` / `status` / `stop` / `list` 四段式。

#### `POST /api/data-export/bag/start`

**请求体**
```json
{
  "container_name": "ros2_fox_hytz_3788",
  "target_user": null
}
```

**处理流程**
1. 校验容器运行中
2. 检查 `_bag_sessions`，若已有录制任务则返回 409
3. 生成时间戳，记录 session
4. **后台启动录制**（关键：用 `detach=True`）：
   ```bash
   source /home/boonray/install/setup.bash && cd /home/boonray && ros2 bag record -s mcap --all
   ```
5. 记录 session：`_bag_sessions[container_name] = {"timestamp": ..., "started_at": ..., "user": ...}`
6. 审计日志
7. 返回 session 信息

**响应**
```json
{
  "success": true,
  "message": "录制已启动",
  "container_name": "ros2_fox_hytz_3788",
  "timestamp": "20260821_15_41_00",
  "status": "recording"
}
```

> **设计要点**：录制命令固定为 `ros2 bag record -s mcap --all`（使用 mcap 格式，录制所有话题）。录制目录为 `/home/boonray`（ROS2 bag 默认路径），通过 `ls -dt /home/boonray/rosbag2_*` 自动定位最新 bag。

#### `GET /api/data-export/bag/status?container_name=xxx`

**用途**：查询录制状态，由前端定时轮询。

**处理流程**
1. 查 `_bag_sessions` 是否存在该容器的 session
2. 返回录制中 / 空闲 / 已停止状态与已录时长

**响应**
```json
{
  "container_name": "ros2_fox_hytz_3788",
  "status": "recording",
  "elapsed_seconds": 45.2,
  "timestamp": "20260821_15_41_00"
}
```

`status` 取值：`idle` / `recording` / `stopped`

#### `POST /api/data-export/bag/stop`

**请求体**
```json
{
  "container_name": "ros2_fox_hytz_3788",
  "target_user": null
}
```

**处理流程**（一次调用完成「停止→打包→拷贝→清理」）
1. `pkill -f 'ros2 bag record'` 优雅停止，`sleep 3` 等待 bag 写入元数据
2. 二次检测进程：若仍存活则 `pkill -9` 强制终止
3. 通过 `ls -dt /home/boonray/rosbag2_* | head -1` 自动定位最新 bag 目录
4. 容器内打包：`cd /home/boonray && tar -czf /tmp/rosbag2_<ts>.tar.gz rosbag2_<ts>`
5. 宿主机落地：`<bag_storage>/rosbag2_<ts>.tar.gz`（经 `_get_bag_storage` 实现用户隔离）
6. `docker cp` 到宿主机用户空间
7. 清理容器内临时文件
8. 更新 session 状态为 `stopped`，写入审计日志
9. 返回宿主机路径与大小

**响应**
```json
{
  "success": true,
  "message": "录制已停止并导出",
  "file_path": "/home/fox/robotruck_ros2/Docker/bags/rosbag2_20260821_15_41_00.tar.gz",
  "file_name": "rosbag2_20260821_15_41_00.tar.gz",
  "size_bytes": 163840000,
  "size_mb": 156.3,
  "duration_seconds": 45.2
}
```

#### `GET /api/data-export/bag/list?target_user=<可选>`

**用途**：列出当前用户 `bag_storage` 下所有已导出的 bag 文件（供下载列表）。

**处理流程**
1. 通过 `_get_bag_storage` 获取当前用户（或管理员指定的 target_user）的 bag 目录
2. 扫描目录下所有文件，返回文件名、大小、修改时间

**响应**
```json
{
  "success": true,
  "files": [
    {"name": "rosbag2_20260821_15_41_00.tar.gz", "size": 163840000, "size_mb": 156.3, "mtime": 1755830400}
  ],
  "path": "/home/fox/robotruck_ros2/Docker/bags"
}
```

### 4.3 通用：容器选中前置

> 不新增接口。前端点击按钮时已校验 `selectedContainerName` 非空且容器运行中；后端各接口独立调用 `_ensure_ros2_container` 再次校验，确保安全。

### 4.4 专用 Web 下载接口

#### `GET /api/data-export/bag/download?file=<文件名>&target_user=<可选>`

**处理流程**
1. 文件名白名单校验（禁止分隔符 `/`, `\`, `..`）
2. 通过 `_get_bag_storage` 解析当前用户的 bag 目录
3. `os.path.normpath` + `startswith` 防路径遍历
4. `FileResponse` 返回文件，自动触发浏览器下载

**响应头**
```
Content-Disposition: attachment; filename="rosbag2_xxx.tar.gz"
Content-Type: application/gzip
```

**用户隔离保证**
- **普通用户 A** 访问 `/api/data-export/bag/download?file=x&target_user=other`
  → `_get_bag_storage` 内部调用 `get_user_workspace_paths`，普通用户传 `target_user` 被静默忽略
  → `bag_storage` = 自己空间
  → 只能下载自己空间下的文件
- **管理员** 可指定 `target_user` 下载其他用户空间的文件

> **与既有 `/api/files/download` 的区别**：
> 1. 权限不同：本接口使用 `data-export` 而非 `tools`，普通用户无需授予 `tools` 权限
> 2. 参数更简洁：仅需 `file=<文件名>`，不暴露 `folder_type` 概念
> 3. 更安全：独立路径，便于后续扩展（如添加下载审计、格式转换等）

---

## 五、后端实现细节

### 5.1 新增文件 `backend/services/data_export_service.py`

封装所有 Docker 操作，不直接依赖 `api.py`。按 README「解耦开发规范」第 1 条：「新增功能先在 services/ 实现业务逻辑」。

关键设计：
- `_get_bag_storage(current_user, target_user)`：统一解析用户隔离的 bag 存储路径，内部调用 `get_user_workspace_paths`，普通用户传 `target_user` 会被静默忽略
- `_ensure_ros2_container(container_name)`：校验容器存在、运行中、且镜像为 ROS2
- `BAG_RECORD_CMD = "source /home/boonray/install/setup.bash && cd /home/boonray && ros2 bag record -s mcap --all"`（mcap 格式录制所有话题）
- `_bag_sessions` + `_bag_sessions_lock`：进程内 session 表，加锁保护
- 录制定位：通过 `ls -dt /home/boonray/rosbag2_* | head -1` 自动定位最新 bag 目录（无需在录制前命名）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出服务模块
@File    :  data_export_service.py
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  hdmap 提取 + ros2 bag 录制业务逻辑，仅依赖 core/services/database 层
            遵循 README「解耦开发规范」第 1 条：业务逻辑放 services/
"""
import os
import re
import time
import threading
from datetime import datetime

from logger import logger
from services.docker_manager import DockerManager
from core.workspace import get_user_workspace_paths


_bag_sessions: dict = {}
_bag_sessions_lock = threading.Lock()


class DataExportService:
    """数据导出服务：hdmap 提取 + ros2 bag 录制"""

    BAG_RECORD_CMD = "source /home/boonray/install/setup.bash && cd /home/boonray && ros2 bag record -s mcap --all"
    HDMAP_BASE = "/home/boonray/resource_data"
    CONTAINER_BAG_PATH = "/home/boonray"

    @classmethod
    def _get_bag_storage(cls, current_user: dict, target_user: str = None) -> str:
        paths = get_user_workspace_paths(current_user, target_user=target_user)
        bag_storage = paths["bag_storage"]
        os.makedirs(bag_storage, exist_ok=True)
        return bag_storage

    @classmethod
    def _sanitize_sn(cls, sn: str) -> str:
        sn = re.sub(r'[^a-zA-Z0-9_\-]', '', sn)
        if not sn:
            raise ValueError("SN 不合法")
        return sn

    @classmethod
    def _ensure_ros2_container(cls, container_name: str) -> None:
        containers = DockerManager.list_containers(running_only=True, filter_name=container_name)
        found = [c for c in containers if c["name"] == container_name]
        if not found:
            all_containers = DockerManager.list_containers(running_only=False, filter_name=container_name)
            if any(c["name"] == container_name for c in all_containers):
                raise ValueError(f"容器 '{container_name}' 存在但未运行，请先启动容器")
            raise ValueError(f"容器 '{container_name}' 不存在")

        image = found[0].get("image", "")
        if "ros2" not in image.lower() and "humble" not in image.lower() and "foxy" not in image.lower():
            raise ValueError(f"容器 '{container_name}' 不是 ROS2 容器")

    # ---------- 地图 ----------
    @classmethod
    def _list_sn_dirs(cls, container_name: str) -> list:
        cls._ensure_ros2_container(container_name)
        cmd = f"ls -d {cls.HDMAP_BASE}/*/hdmap 2>/dev/null || echo ''"
        rc, out, err = DockerManager.exec_command(container_name, cmd, timeout=15)
        if rc != 0 or not out.strip():
            return []
        dirs = []
        for line in out.strip().split("\n"):
            line = line.strip()
            if line:
                sn_name = line.rstrip("/").split("/")[-2]
                dirs.append(sn_name)
        return sorted(dirs)

    @classmethod
    def extract_hdmap(cls, container_name: str, sn: str,
                      current_user: dict, target_user: str = None) -> dict:
        logger.info(f"开始提取地图: container={container_name}, sn={sn}, user={current_user.get('username')}")

        cls._ensure_ros2_container(container_name)
        sn = cls._sanitize_sn(sn)

        bag_storage = cls._get_bag_storage(current_user, target_user)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tar_name = f"hdmap_{sn}_{timestamp}.tar.gz"
        host_tar_path = os.path.join(bag_storage, tar_name)

        container_hdmap_dir = f"{cls.HDMAP_BASE}/{sn}/hdmap"
        container_tar_path = f"/tmp/{tar_name}"

        exec_cmd = f"cd {container_hdmap_dir} && tar -czf {container_tar_path} -- ./*.pb.bin"
        logger.debug(f"容器内打包命令: {exec_cmd}")
        rc, out, err = DockerManager.exec_command(container_name, exec_cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"容器内打包失败: {err or out or '未知错误'}")

        logger.info(f"容器内打包成功，开始拷贝到宿主机: {container_tar_path} -> {host_tar_path}")
        copy_cmd = DockerManager._docker("cp", f"{container_name}:{container_tar_path}", host_tar_path)
        rc, out, err = DockerManager.run_cmd(copy_cmd, timeout=60)
        if rc != 0:
            raise RuntimeError(f"拷贝到宿主机失败: {err or out or '未知错误'}")

        try:
            DockerManager.exec_command(container_name, f"rm -f {container_tar_path}", timeout=10)
        except Exception:
            pass

        file_size = os.path.getsize(host_tar_path) if os.path.isfile(host_tar_path) else 0
        logger.info(f"地图提取完成: {host_tar_path}, size={file_size}")

        return {
            "success": True,
            "message": "地图提取成功",
            "file_path": host_tar_path,
            "file_name": tar_name,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2),
        }

    # ---------- Bag 录制 ----------
    @classmethod
    def start_bag_record(cls, container_name: str,
                         current_user: dict, target_user: str = None) -> dict:
        logger.info(f"开始录制Bag: container={container_name}, user={current_user.get('username')}")

        cls._ensure_ros2_container(container_name)

        with _bag_sessions_lock:
            if container_name in _bag_sessions:
                session = _bag_sessions[container_name]
                if session.get("status") == "recording":
                    raise RuntimeError(f"容器 '{container_name}' 已有录制任务进行中")

        exec_cmd = cls.BAG_RECORD_CMD
        logger.debug(f"后台启动录制: {exec_cmd}")
        rc, out, err = DockerManager.exec_command(container_name, exec_cmd, detach=True, timeout=10)

        if rc != 0:
            raise RuntimeError(f"启动录制失败: {err or out or '未知错误'}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session = {
            "container_name": container_name,
            "started_at": time.time(),
            "timestamp": timestamp,
            "status": "recording",
            "pid_info": out.strip() if out else "",
        }
        with _bag_sessions_lock:
            _bag_sessions[container_name] = session

        logger.info(f"Bag录制已启动: container={container_name}, timestamp={timestamp}")
        return {
            "success": True,
            "message": "录制已启动",
            "container_name": container_name,
            "timestamp": timestamp,
            "status": "recording",
        }

    @classmethod
    def stop_bag_record(cls, container_name: str,
                        current_user: dict, target_user: str = None) -> dict:
        logger.info(f"停止录制Bag: container={container_name}")

        with _bag_sessions_lock:
            session = _bag_sessions.get(container_name)

        if not session or session.get("status") != "recording":
            raise RuntimeError(f"容器 '{container_name}' 没有进行中的录制任务")

        try:
            pkill_cmd = "pkill -f 'ros2 bag record' 2>/dev/null || true; sleep 3; pgrep -f 'ros2 bag record' || true"
            rc, out, err = DockerManager.exec_command(container_name, pkill_cmd, timeout=15)
            if rc == 0 and out.strip():
                logger.warning(f"录制进程未能完全终止，强制 kill: {out.strip()}")
                DockerManager.exec_command(container_name,
                    f"pkill -9 -f 'ros2 bag record' 2>/dev/null || true", timeout=10)
                time.sleep(2)
            logger.info("录制进程已终止")
        except Exception as e:
            logger.warning(f"终止录制进程时出错: {e}")

        bag_storage = cls._get_bag_storage(current_user, target_user)

        timestamp = session.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
        bag_dir_name = f"rosbag2_{timestamp}"

        find_cmd = f"ls -dt {cls.CONTAINER_BAG_PATH}/rosbag2_* 2>/dev/null | head -1 || echo ''"
        rc, out, err = DockerManager.exec_command(container_name, find_cmd, timeout=10)
        container_bag_dir = out.strip().split("\n")[0].strip() if (rc == 0 and out.strip()) else ""

        if not container_bag_dir:
            raise RuntimeError(f"容器内未找到录制生成的bag目录 (rosbag2_*)")

        logger.info(f"找到bag目录: {container_bag_dir}")

        tar_name = f"{bag_dir_name}.tar.gz"
        host_tar_path = os.path.join(bag_storage, tar_name)

        container_tar_path = f"/tmp/{tar_name}"
        container_parent = os.path.dirname(container_bag_dir)
        container_basename = os.path.basename(container_bag_dir)

        tar_cmd = f"cd {container_parent} && tar -czf {container_tar_path} {container_basename}"
        rc, out, err = DockerManager.exec_command(container_name, tar_cmd, timeout=300)
        if rc != 0:
            raise RuntimeError(f"容器内打包失败: {err or out or '未知错误'}")

        copy_cmd = DockerManager._docker("cp", f"{container_name}:{container_tar_path}", host_tar_path)
        rc, out, err = DockerManager.run_cmd(copy_cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"拷贝到宿主机失败: {err or out or '未知错误'}")

        try:
            DockerManager.exec_command(container_name, f"rm -f {container_tar_path}", timeout=10)
        except Exception:
            pass

        file_size = os.path.getsize(host_tar_path) if os.path.isfile(host_tar_path) else 0

        with _bag_sessions_lock:
            if container_name in _bag_sessions:
                _bag_sessions[container_name]["status"] = "stopped"

        logger.info(f"Bag录制完成: {host_tar_path}, size={file_size}")
        return {
            "success": True,
            "message": "录制已停止并导出",
            "file_path": host_tar_path,
            "file_name": tar_name,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2),
            "duration_seconds": round(time.time() - session.get("started_at", time.time()), 1),
        }

    @classmethod
    def get_bag_status(cls, container_name: str) -> dict:
        with _bag_sessions_lock:
            session = _bag_sessions.get(container_name)

        if not session:
            return {
                "container_name": container_name,
                "status": "idle",
                "message": "无录制任务",
            }

        if session.get("status") == "recording":
            elapsed = round(time.time() - session.get("started_at", time.time()), 1)
            return {
                "container_name": container_name,
                "status": "recording",
                "elapsed_seconds": elapsed,
                "timestamp": session.get("timestamp"),
            }

        return {
            "container_name": container_name,
            "status": session.get("status", "unknown"),
            "timestamp": session.get("timestamp"),
        }

    @classmethod
    def list_bag_files(cls, current_user: dict, target_user: str = None) -> dict:
        bag_storage = cls._get_bag_storage(current_user, target_user)

        if not os.path.exists(bag_storage):
            return {"success": True, "files": [], "path": bag_storage}

        files = []
        try:
            for name in sorted(os.listdir(bag_storage)):
                p = os.path.join(bag_storage, name)
                if os.path.isfile(p):
                    st = os.stat(p)
                    files.append({
                        "name": name,
                        "size": st.st_size,
                        "size_mb": round(st.st_size / 1024 / 1024, 2),
                        "mtime": int(st.st_mtime),
                    })
        except PermissionError:
            raise RuntimeError("无权限访问bag目录")

        return {"success": True, "files": files, "path": bag_storage}
```

### 5.2 新增路由文件 `backend/routers/data_export.py`

按 README「解耦开发规范」第 2 条：「routers/ 只负责：接收请求 → 调用 service → 返回响应」。本路由文件不写任何业务逻辑。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出路由模块
@File    :  data_export.py
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  hdmap 提取 + ros2 bag 录制 REST API；仅做参数校验、调用 service、返回响应
            符合 README「解耦开发规范」：routers/ 不含业务逻辑
"""

from typing import Optional
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deps import require_permission
from services.data_export_service import DataExportService
from database import db
from logger import logger

router = APIRouter()


class HdmapExtractRequest(BaseModel):
    container_name: str
    sn: str
    target_user: Optional[str] = None


class BagRecordRequest(BaseModel):
    container_name: str
    target_user: Optional[str] = None


class BagStopRequest(BaseModel):
    container_name: str
    target_user: Optional[str] = None


@router.get("/api/data-export/hdmap/sn-list")
async def list_hdmap_sn(
    container_name: str,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        sn_list = DataExportService._list_sn_dirs(container_name)
        return {"success": True, "sn_list": sn_list}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/hdmap/extract")
async def extract_hdmap(
    data: HdmapExtractRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.extract_hdmap(
            container_name=data.container_name,
            sn=data.sn,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "extract_hdmap",
                         f"container={data.container_name} sn={data.sn} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"提取地图异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/bag/start")
async def start_bag_record(
    data: BagRecordRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.start_bag_record(
            container_name=data.container_name,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "start_bag_record",
                         f"container={data.container_name} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"启动录制异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/bag/stop")
async def stop_bag_record(
    data: BagStopRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.stop_bag_record(
            container_name=data.container_name,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "stop_bag_record",
                         f"container={data.container_name} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"停止录制异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/data-export/bag/status")
async def get_bag_status(
    container_name: str,
    current_user: dict = Depends(require_permission('data-export'))
):
    return DataExportService.get_bag_status(container_name)


@router.get("/api/data-export/bag/list")
async def list_bag_files(
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        return DataExportService.list_bag_files(current_user, target_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/data-export/bag/download")
async def download_bag_file(
    file: str,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    if not file or os.sep in file or '/' in file or '..' in file:
        raise HTTPException(status_code=400, detail="非法文件名")

    bag_storage = DataExportService._get_bag_storage(current_user, target_user)
    full_path = os.path.normpath(os.path.join(bag_storage, file))

    if not full_path.startswith(os.path.normpath(bag_storage)):
        raise HTTPException(status_code=400, detail="非法路径访问")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info(f"下载文件: {full_path}, user={current_user.get('username')}")
    return FileResponse(full_path, filename=os.path.basename(full_path))
```

### 5.3 路由注册（追加，不改动既有）

在 `backend/routers/api.py` **末尾**追加：

```python
# ============================================================
# 数据导出模块（新增功能，零侵入）
# 与 api.py 顶部注释「后续可按业务领域进一步拆分」预期一致，
# 落地为独立的 routers/data_export.py 路由文件
# ============================================================
from routers.data_export import router as data_export_router
router.include_router(data_export_router)
```

> 注：[`api.py:1-19`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/api.py#L1-L19) 顶部 docstring 已明确「后续可按业务领域进一步拆分为：auth.py / admin.py / system.py / docker.py / ros2.py 等」，本功能按此预期落地为 `data_export.py`。注册方式与既有 `tickets` / `fault` 模块一致。

### 5.4 权限面板追加

在 `backend/core/constants.py` 的 `ALL_PANELS` 列表**末尾**追加一项：

```python
ALL_PANELS = [
    "welcome", "scripts", "advanced-scripts", "vehicle", "docker", "advanced-docker",
    "images", "traffic", "advanced-fault", "tools", "monitor",
    "simulation", "topics", "nodes", "services", "actions",
    "advanced-extend",
    "api-manager", "theme", "settings", "tickets",
    "data-export"   # ★ 新增
]
```

> 这是纯追加，不修改任何已有项。管理员默认全权限，普通用户需在用户管理勾选。
> 本次实现将 `data-export` 作为统一权限，涵盖提取地图、录制 Bag、下载 Bags 全部子功能。

---

## 六、前端设计

### 6.1 在 `panel-tools` 内追加一个新 card [`frontend/index.html`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/frontend/index.html)

在 `panel-tools` 的「数据清理」card 之前插入：

```html
<!-- ============================================================
面板：数据导出（新增功能）
============================================================ -->
<div class="card" data-card-id="data-export" style="margin-bottom:12px;">
    <div class="card-title">📦 数据导出（地图 / Bag）</div>

    <!-- 公共：当前选中容器提示 -->
    <div id="dataExportContainerBar" style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">
        ⚠️ 请先在 Docker 面板选中一个运行中的 ROS2 容器
    </div>

    <!-- 模块 1：提取地图 -->
    <div style="margin-bottom:12px;padding:10px;border:1px solid #e0e0e0;border-radius:6px;">
        <div style="font-weight:bold;margin-bottom:6px;">🗺️ 提取地图 (hdmap)</div>
        <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap;">
            <button class="btn btn-sm" onclick="DataExport.refreshSns()">🔄 刷新 SN 列表</button>
            <select id="hdmapSnSelect" style="flex:1;min-width:160px;">
                <option value="">请先刷新 SN</option>
            </select>
            <button class="btn btn-sm btn-info" onclick="DataExport.previewHdmap()">👁 预览</button>
            <button class="btn btn-sm btn-success" onclick="DataExport.extractHdmap()">📦 提取</button>
        </div>
        <pre id="hdmapPreview" style="display:none;font-size:11px;max-height:120px;overflow:auto;background:var(--bg-input);padding:6px;border-radius:4px;"></pre>
    </div>

    <!-- 模块 2：录制 ROS2 Bag -->
    <div style="padding:10px;border:1px solid #e0e0e0;border-radius:6px;">
        <div style="font-weight:bold;margin-bottom:6px;">🎬 录制 ROS2 Bag</div>
        <div id="bagRecordStatus" style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;">空闲</div>
        <div class="btn-group" style="flex-wrap:wrap;gap:6px;">
            <button class="btn btn-sm btn-success" id="bagStartBtn" onclick="DataExport.startBag()">▶ 开始录制</button>
            <button class="btn btn-sm btn-warning" id="bagStopBtn" onclick="DataExport.stopBag()" disabled>⏹ 停止并导出</button>
            <button class="btn btn-sm btn-outline" id="bagCancelBtn" onclick="DataExport.cancelBag()" disabled>✕ 取消</button>
            <button class="btn btn-sm" onclick="DataExport.refreshBagStatus()">🔄 刷新状态</button>
        </div>
        <div id="bagRecordResult" style="display:none;margin-top:8px;font-size:12px;"></div>
    </div>

    <!-- 模块 3：已导出文件列表 + Web 下载 -->
    <div style="margin-top:12px;padding:10px;border:1px solid #e0e0e0;border-radius:6px;">
        <div style="font-weight:bold;margin-bottom:6px;">📥 已导出文件（仅显示您空间内的文件）</div>
        <div class="btn-group" style="margin-bottom:6px;">
            <button class="btn btn-sm" onclick="DataExport.refreshFileList()">🔄 刷新列表</button>
            <span id="dataExportTargetHint" style="font-size:11px;color:var(--text-secondary);align-self:center;"></span>
        </div>
        <div style="overflow-x:auto;max-height:200px;overflow-y:auto;">
            <table class="data-table">
                <thead><tr><th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead>
                <tbody id="dataExportFileList">
                    <tr><td colspan="4" style="text-align:center;color:var(--text-muted);">点击刷新列表</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>
```

### 6.2 新增前端逻辑文件 `frontend/js/panels/data_export.js`

```javascript
// ============================================================
// 数据导出面板逻辑（新增功能，零侵入）
// ============================================================
var DataExport = (function() {
    var bagStatusTimer = null;

    function getContainer() {
        // 复用既有全局变量 selectedContainerName
        if (typeof selectedContainerName === 'undefined' || !selectedContainerName) {
            if (typeof selectedContainerId !== 'undefined' && selectedContainerId) {
                return selectedContainerId;
            }
            return null;
        }
        return selectedContainerName;
    }

    function updateContainerBar() {
        var bar = document.getElementById('dataExportContainerBar');
        if (!bar) return;
        var name = getContainer();
        if (name) {
            bar.innerHTML = '✅ 当前容器：<strong>' + escapeHtml(name) + '</strong>';
            bar.style.color = '#2c5aa0';
        } else {
            bar.innerHTML = '⚠️ 请先在 Docker 面板选中一个运行中的 ROS2 容器';
            bar.style.color = 'var(--text-secondary)';
        }
    }

    function refreshSns() {
        var name = getContainer();
        if (!name) { showToast('请先选中容器', 'warning'); return; }
        var sel = document.getElementById('hdmapSnSelect');
        sel.innerHTML = '<option value="">加载中...</option>';
        apiPost('/api/data-export/hdmap/list-sns', { container_name: name }).then(function(d) {
            if (d.success) {
                sel.innerHTML = d.sns.length
                    ? d.sns.map(function(s){ return '<option value="'+escapeHtml(s)+'">'+escapeHtml(s)+'</option>'; }).join('')
                    : '<option value="">无 SN，请检查容器内 /home/boonray/resource_data/</option>';
            } else {
                sel.innerHTML = '<option value="">加载失败</option>';
            }
        });
    }

    function previewHdmap() {
        var name = getContainer();
        var sn = document.getElementById('hdmapSnSelect').value;
        if (!name || !sn) { showToast('请先选择容器和 SN', 'warning'); return; }
        apiPost('/api/data-export/hdmap/preview', { container_name: name, sn: sn }).then(function(d) {
            var pre = document.getElementById('hdmapPreview');
            pre.style.display = 'block';
            pre.textContent = d.success ? (d.files || '无 .pb.bin 文件') : ('错误: ' + (d.error||''));
        });
    }

    function extractHdmap() {
        var name = getContainer();
        var sn = document.getElementById('hdmapSnSelect').value;
        if (!name || !sn) { showToast('请先选择容器和 SN', 'warning'); return; }
        customConfirm('确认从容器 ' + name + ' 提取 SN=' + sn + ' 的 hdmap？', function() {
            showToast('正在打包并拷贝，请稍候...', 'info');
            apiPost('/api/data-export/hdmap/extract', { container_name: name, sn: sn }).then(function(d) {
                if (d.success) {
                    showToast('✅ 已导出: ' + d.host_path + ' (' + d.size_mb + ' MB)', 'success');
                } else {
                    showToast('❌ 导出失败: ' + (d.error || d.detail || ''), 'error');
                }
            });
        });
    }

    function startBag() {
        var name = getContainer();
        if (!name) { showToast('请先选中容器', 'warning'); return; }
        customConfirm('确认在容器 ' + name + ' 中启动 ros2 bag record -a？', function() {
            apiPost('/api/data-export/bag/start', { container_name: name }).then(function(d) {
                if (d.success) {
                    showToast('录制已启动: ' + d.bag_name, 'success');
                    toggleBagButtons(true);
                    startBagStatusPolling();
                } else {
                    showToast('启动失败: ' + (d.error || d.detail || ''), 'error');
                }
            });
        });
    }

    function stopBag() {
        var name = getContainer();
        if (!name) return;
        customConfirm('确认停止录制并导出？大文件打包可能耗时较长。', function() {
            showToast('正在停止并打包...', 'info');
            stopBagStatusPolling();
            apiPost('/api/data-export/bag/stop', { container_name: name }).then(function(d) {
                if (d.success) {
                    var r = document.getElementById('bagRecordResult');
                    r.style.display = 'block';
                    r.innerHTML = '✅ 已导出: <code>' + escapeHtml(d.host_path) + '</code> (' + d.size_mb + ' MB)';
                    showToast('已导出: ' + d.bag_name, 'success');
                } else {
                    showToast('停止失败: ' + (d.error || d.detail || ''), 'error');
                }
                toggleBagButtons(false);
            });
        });
    }

    function cancelBag() {
        var name = getContainer();
        if (!name) return;
        customConfirm('确认取消录制？此次录制将不导出。', function() {
            apiPost('/api/data-export/bag/cancel', { container_name: name }).then(function(d) {
                showToast('已取消', 'info');
                stopBagStatusPolling();
                toggleBagButtons(false);
            });
        });
    }

    function refreshBagStatus() {
        var name = getContainer();
        if (!name) return;
        apiGet('/api/data-export/bag/status?container_name=' + encodeURIComponent(name)).then(function(d) {
            renderBagStatus(d);
        });
    }

    function renderBagStatus(d) {
        var el = document.getElementById('bagRecordStatus');
        if (!el) return;
        var map = { idle: '⚪ 空闲', recording: '🔴 录制中', stopped: '⏹ 已停止', exporting: '📦 导出中', done: '✅ 已完成' };
        var txt = map[d.state] || d.state;
        if (d.state === 'recording' && d.elapsed_seconds != null) {
            txt += '（已录 ' + d.elapsed_seconds + ' 秒）';
        }
        el.textContent = txt;
        el.style.color = d.state === 'recording' ? '#c0392b' : 'var(--text-secondary)';
    }

    function startBagStatusPolling() {
        stopBagStatusPolling();
        bagStatusTimer = setInterval(refreshBagStatus, 3000);
    }
    function stopBagStatusPolling() {
        if (bagStatusTimer) { clearInterval(bagStatusTimer); bagStatusTimer = null; }
    }

    function toggleBagButtons(recording) {
        document.getElementById('bagStartBtn').disabled = recording;
        document.getElementById('bagStopBtn').disabled = !recording;
        document.getElementById('bagCancelBtn').disabled = !recording;
    }

    // ============================================================
    // 模块 3：已导出文件列表 + Web 下载（完全复用既有接口）
    // ============================================================

    /**
     * 构造带 target_user 的查询串。
     * 普通用户的 currentTargetUser 由既有逻辑控制为 null，无法越权。
     */
    function _targetUserQS() {
        return (typeof currentTargetUser !== 'undefined' && currentTargetUser)
            ? '&target_user=' + encodeURIComponent(currentTargetUser)
            : '';
    }

    /**
     * 拉取当前用户 bag_storage 下的文件列表。
     * 既有 /api/files/list 已内置用户隔离与路径校验。
     */
    function refreshFileList() {
        var tbody = document.getElementById('dataExportFileList');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;">加载中...</td></tr>';
        // 既有接口，自动按 currentTargetUser（管理员切换）切换空间
        apiGet('/api/files/list?folder_type=bags&subpath=' + (typeof currentTargetUser !== 'undefined' && currentTargetUser ? '&target_user=' + encodeURIComponent(currentTargetUser) : ''))
            .then(function(d) {
                renderFileList(d);
                // 更新空间提示
                var hint = document.getElementById('dataExportTargetHint');
                if (hint) {
                    hint.textContent = (typeof currentTargetUser !== 'undefined' && currentTargetUser)
                        ? '📍 当前空间：' + currentTargetUser
                        : '📍 当前空间：我的工作空间';
                }
            });
    }

    function renderFileList(d) {
        var tbody = document.getElementById('dataExportFileList');
        if (!tbody) return;
        if (!d || !d.success || !d.items || !d.items.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">暂无文件，请先导出</td></tr>';
            return;
        }
        // 仅显示 .tar.gz，避免显示其他无关文件
        var files = d.items.filter(function(it){ return !it.is_dir && /\.tar\.gz$/i.test(it.name); });
        if (!files.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">暂无 .tar.gz 文件</td></tr>';
            return;
        }
        tbody.innerHTML = files.map(function(it) {
            return '<tr>'
                + '<td style="font-family:monospace;font-size:12px;">' + escapeHtml(it.name) + '</td>'
                + '<td>' + _humanSize(it.size) + '</td>'
                + '<td>' + _fmtTime(it.mtime) + '</td>'
                + '<td>'
                + '  <button class="btn btn-sm btn-info" onclick="DataExport.downloadFile(\'' + escapeHtml(it.name) + '\')">⬇ 下载</button>'
                + '  <button class="btn btn-sm btn-warning" onclick="DataExport.deleteFile(\'' + escapeHtml(it.name) + '\')">🗑 删除</button>'
                + '</td>'
                + '</tr>';
        }).join('');
    }

    function _humanSize(b) {
        if (!b) return '0 B';
        var u = ['B','KB','MB','GB']; var i = 0;
        while (b >= 1024 && i < u.length-1) { b /= 1024; i++; }
        return b.toFixed(1) + ' ' + u[i];
    }
    function _fmtTime(ts) {
        if (!ts) return '-';
        var d = new Date(ts * 1000);
        return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0')
             + ' ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
    }

    /**
     * 触发浏览器下载。
     * 复用既有 GET /api/files/download，自动带 JWT（既有 apiGet 同源 cookie/Header）。
     * 为带 JWT 的鉴权下载，使用 fetch + Blob 方案。
     */
    function downloadFile(filename) {
        var url = '/api/files/download?folder_type=bags&subpath=' + encodeURIComponent(filename) + _targetUserQS();
        // 既有 apiGet 已封装 JWT Header；fetch 流式拿 Blob 触发浏览器保存对话框
        fetch(url, {
            method: 'GET',
            credentials: 'same-origin',
            headers: (typeof authToken !== 'undefined' && authToken)
                ? { 'Authorization': 'Bearer ' + authToken }
                : {}
        }).then(function(resp) {
            if (!resp.ok) {
                return resp.json().then(function(e) { throw new Error(e.detail || '下载失败'); });
            }
            return resp.blob();
        }).then(function(blob) {
            // 触发浏览器原生下载对话框，用户可选择保存路径
            var a = document.createElement('a');
            var objUrl = URL.createObjectURL(blob);
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(function(){ URL.revokeObjectURL(objUrl); a.remove(); }, 0);
            showToast('已开始下载: ' + filename, 'success');
        }).catch(function(e) {
            showToast('下载失败: ' + e.message, 'error');
        });
    }

    /**
     * 删除文件，复用既有 /api/files/delete。
     * 删除同样走用户隔离，普通用户只能删自己的。
     */
    function deleteFile(filename) {
        customConfirm('确认删除文件 ' + filename + '？此操作不可撤销。', function() {
            apiPost('/api/files/delete', {
                folder_type: 'bags',
                subpath: filename,
                target_user: (typeof currentTargetUser !== 'undefined' && currentTargetUser) ? currentTargetUser : null
            }).then(function(d) {
                showToast(d.success ? '已删除' : ('删除失败: ' + (d.detail||'')), d.success ? 'success' : 'error');
                if (d.success) refreshFileList();
            });
        });
    }

    // 监听容器选择变化（复用既有 deselectContainer / selectContainer 钩子）
    // 通过 MutationObserver 或在 switchPanel('tools') 时主动刷新
    function onPanelEnter() {
        updateContainerBar();
        refreshBagStatus();
        refreshFileList();   // 进入面板时刷新已导出文件列表
    }

    return {
        refreshSns: refreshSns,
        previewHdmap: previewHdmap,
        extractHdmap: extractHdmap,
        startBag: startBag,
        stopBag: stopBag,
        cancelBag: cancelBag,
        refreshBagStatus: refreshBagStatus,
        refreshFileList: refreshFileList,
        downloadFile: downloadFile,
        deleteFile: deleteFile,
        onPanelEnter: onPanelEnter
    };
})();

// 暴露给全局 onclick 调用
window.DataExport = DataExport;
```

### 6.3 引入新 JS 文件 [`frontend/index.html`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/frontend/index.html)

在 `</body>` 前既有 `<script src="js/panels/terminal.js"></script>` 之后追加一行：

```html
<script src="js/panels/data_export.js"></script>
```

### 6.4 进入面板时刷新容器状态

在 `sj_script.js` 的 `switchPanel` 函数（[L742](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/frontend/js/sj_script.js#L742)）已有 `if (panel === 'tools') {...}` 分支，**不修改该分支**，改为在新 JS 文件内监听 `switchPanel` 调用：

> 方案 A（推荐）：在 `data_export.js` 末尾追加对 `switchPanel` 的包装：
> ```javascript
> var _origSwitchPanel = window.switchPanel;
> window.switchPanel = function(p) {
>     _origSwitchPanel(p);
>     if (p === 'tools' && window.DataExport) { window.DataExport.onPanelEnter(); }
> };
> ```
> 这种「包装」方式不改 `sj_script.js`，符合「零侵入」要求。

---

## 七、关键流程时序

### 7.1 提取地图时序

```
用户           前端                后端                 容器
 │ 选中容器     │                   │                    │
 │ 刷新SN列表   │──POST list-sns──▶│──docker exec ls──▶│
 │              │◀──sns[]──────────│                    │
 │ 选SN+预览    │──POST preview───▶│──docker exec ls──▶│
 │              │◀──files──────────│                    │
 │ 点提取       │──POST extract───▶│                    │
 │              │                   │─docker exec tar──▶│
 │              │                   │◀────tar.gz ok─────│
 │              │                   │─docker cp────────▶│ (到宿主机)
 │              │                   │─docker exec rm───▶│ (清理)
 │              │◀──host_path──────│                    │
 │ 看到结果     │                   │                    │
```

### 7.2 录制 Bag 时序

```
用户           前端                后端                 容器
 │ 选中容器     │                   │                    │
 │ 点开始录制   │──POST bag/start─▶│                    │
 │              │                   │─docker exec -d───▶│ ros2 bag record (后台)
 │              │◀──bag_name───────│                    │
 │ 前端轮询状态  │──GET bag/status─▶│──pgrep 探活──────▶│
 │              │◀──recording──────│                    │
 │ ...录制中... │                   │                    │
 │ 点停止并导出 │──POST bag/stop──▶│                    │
 │              │                   │─pkill SIGINT─────▶│ (优雅停止)
 │              │                   │   sleep 3          │
 │              │                   │─pkill SIGKILL────▶│ (兜底)
 │              │                   │─docker exec tar──▶│ (打包)
 │              │                   │─docker cp────────▶│ (到宿主机)
 │              │                   │─docker exec rm───▶│ (清理)
 │              │◀──host_path──────│                    │
 │ 看到结果     │                   │                    │
```

---

## 八、安全与异常处理

### 8.1 命令注入防护
- SN 严格正则 `^[A-Za-z0-9_-]+$`，并用 `shlex.quote` 二次转义
- 所有动态路径片段经 `shlex.quote` 处理
- 容器名校验：必须为 `ros2_` 前缀且在运行列表中（复用 `list_containers`）

### 8.2 路径越权防护
- 宿主机落地路径必须经 `validate_user_path(bag_storage, current_user, target_user)` 校验
- 管理员可指定 `target_user` 操作目标用户空间，普通用户只能操作自身

### 8.3 资源与并发
- 录制 session 表 `_bag_sessions` 为进程内字典，**同一容器同时只允许一个录制任务**
- 打包大 bag 可能耗时几分钟，`run_cmd` timeout 设为 180~300 秒
- 容器内临时文件无论成败都清理（`finally` 或显式调用）

### 8.4 失败回滚
| 步骤 | 失败处理 |
|------|----------|
| 容器内打包失败 | 直接返回错误，无残留 |
| docker cp 失败 | 删除容器内临时文件后返回错误 |
| 落地目录创建失败 | 返回 500，不启动打包 |

### 8.5 审计
所有操作均写 `db.add_audit_log`，与既有 `sync_bags` / `clean` 等保持一致风格。

### 8.6 下载链路用户隔离（复用既有，重点说明）

下载链路完全复用既有 `/api/files/download`，其用户隔离已在 [`_resolve_user_dir`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/api.py#L624-L643) + [`validate_user_path`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/core/workspace.py) 中实现，新功能不重复造轮子：

| 攻击场景 | 防护点 | 结果 |
|----------|--------|------|
| 普通用户 `honglan_wang` 传 `target_user=ke_yunxiao` 试图下载他人 bag | `get_user_workspace_paths` 中 `if target_user and role=='admin'` 不满足，`effective_user` 仍为 honglan_wang | **静默降级**到自己的空间，无法触及 ke_yunxiao 文件 |
| 普通用户 `honglan_wang` 传 `subpath=../ke_yunxiao/Docker/bags/x.tar.gz` 试图跨目录 | `_safe_join` 检查路径前缀必须仍在 `honglan_wang.home_folder_path` 下 | 400 |
| 任意用户传 `subpath=../../../etc/passwd` | `_safe_join` 检查路径前缀 | 400 |
| 任意用户传 `folder_type=bags` 之外的值 | `_resolve_user_dir` mapping 校验 | 400 |
| 未登录用户访问下载接口 | `require_permission('tools')` | 401 |
| 未授予 `tools` 面板权限的普通用户 | `require_permission('tools')` | 403 |

### 8.7 导出落地路径双重校验

新功能在导出阶段额外显式校验一次，防止 service 层逻辑漏洞：

```python
# data_export.py 路由层
workspace_paths = get_user_workspace_paths(current_user, target_user=data.target_user)
bag_storage = workspace_paths["bag_storage"]
validate_user_path(bag_storage, current_user, data.target_user)   # 第 1 道：用户隔离
# service 层 extract_hdmap / stop_and_export_bag 收到 bag_storage 后
# 仅在其下拼接时间戳文件名，不再接受外部 subpath，杜绝路径注入
```

> 即使前端构造恶意请求，service 层也只接受 `host_bag_storage` 这个根目录，文件名由后端按 `hdmap_<SN>_<时间戳>.tar.gz` / `rosbag2_<时间戳>.tar.gz` 规则生成，**不接受外部传入的文件名**。

---

## 九、文件改动清单

### 新增文件（4 个）
| 路径 | 用途 |
|------|------|
| `backend/services/data_export_service.py` | 业务服务层 |
| `backend/routers/data_export.py` | API 路由层 |
| `frontend/js/panels/data_export.js` | 前端逻辑（含下载/删除按钮） |
| `docs/hdmap-bag-export-plan.md` | 本方案文档 |

### 追加修改（4 处，均为「末尾追加」或「列表加一项」，不改既有逻辑）
| 路径 | 改动 |
|------|------|
| `backend/routers/api.py` | 文件末尾追加 `include_router(data_export_router)` |
| `backend/core/constants.py` | `ALL_PANELS` 末尾追加 `"data-export"` |
| `frontend/index.html` | `panel-tools` 内插入一个新 card（含下载列表）；底部追加 `<script>` 引用 |
| `frontend/js/sj_script.js` | **不改**；通过 `data_export.js` 包装 `switchPanel` 实现联动 |

### 完全复用既有接口（零改动）
| 接口 | 用途 |
|------|------|
| `GET /api/files/download?folder_type=bags&subpath=...` | Web 下载 bag/hdmap 文件到用户电脑 |
| `GET /api/files/list?folder_type=bags` | 列出用户 `bag_storage` 下的文件 |
| `POST /api/files/delete` | 删除已导出的文件 |
| `DockerManager.exec_command(detach=True)` | bag 后台录制 |
| `DockerManager._docker("cp", ...)` | 容器 → 宿主机拷贝 |
| `get_user_workspace_paths` + `validate_user_path` | 用户隔离路径解析 |

---

## 十、验收清单

### 10.1 基本功能
- [ ] 未选中容器时，所有按钮提示「请先选中容器」
- [ ] 选中非 `ros2_` 前缀容器时，后端返回 400
- [ ] 提取地图：SN 列表正确加载；预览显示 `.pb.bin` 文件；导出后宿主机存在 tar.gz 且可解压
- [ ] 录制 Bag：启动后状态变 `recording`，3 秒轮询刷新已录时长；停止后宿主机存在 tar.gz
- [ ] 录制中刷新页面：`bag/status` 能识别「进程已退出」状态
- [ ] 同一容器重复启动录制：返回「已有录制任务进行中」

### 10.2 用户隔离（重点验收）
- [ ] 普通用户 `honglan_wang` 导出的文件，**只**出现在 `~/robotruck_ros2/honglan_wang/Docker/bags/`，不会落到 `ke_yunxiao` 空间
- [ ] 普通用户 `honglan_wang` 调用 `/api/data-export/hdmap/extract` 携带 `target_user=ke_yunxiao` → 文件**仍落地到** `honglan_wang` 自己空间（静默降级，不报错）
- [ ] 普通用户 `honglan_wang` 调用 `/api/data-export/bag/stop` 携带 `target_user=ke_yunxiao` → 文件**仍落地到** `honglan_wang` 自己空间
- [ ] 普通用户 `honglan_wang` 调用 `/api/files/download?folder_type=bags&subpath=x&target_user=ke_yunxiao` → 实际只能下载 `honglan_wang` 自己空间内的 `x` 文件，若 `x` 不在自己空间则 404
- [ ] 普通用户 `honglan_wang` 调用 `/api/files/list?folder_type=bags&target_user=ke_yunxiao` → 返回的 `items` 仍是 `honglan_wang` 自己空间的文件
- [ ] 普通用户 `honglan_wang` 传 `subpath=../ke_yunxiao/Docker/bags/x.tar.gz` → 返回 400（`_safe_join` 拒绝）
- [ ] 管理员调用上述接口携带 `target_user=ke_yunxiao` → 正确切换到 ke_yunxiao 空间操作
- [ ] 普通用户的 `currentTargetUser` 全局变量始终为 null，前端无法绕过

### 10.3 Web 下载
- [ ] 导出完成后，文件列表自动刷新出现新文件
- [ ] 点击「下载」按钮，浏览器弹出保存对话框，下载到本地电脑
- [ ] 下载大文件（>100MB）时不阻塞 UI，可取消
- [ ] 下载链接带 JWT 鉴权，未登录或 token 失效返回 401
- [ ] 下载不存在的文件返回 404
- [ ] 路径遍历攻击 `subpath=../../../etc/passwd` 被拒绝

### 10.4 审计
- [ ] 所有导出操作在 `audit_logs` 表有记录，包含操作者、容器名、目标用户、文件路径
- [ ] 下载与删除操作复用既有 `/api/files/*` 的审计

---

## 十一、后续可选增强（非本期范围）

1. **进度条**：bag 打包时通过 `docker exec` 跟踪 tar 输出字节数估算进度
2. **主题筛选**：前端提供 topic 多选框，调用 `ros2 topic list` 预填
3. **录制时长预设**：支持「录 60 秒后自动停止」
4. **FTP 上传**：导出后一键上传到既有 `ftpServerInput` 配置的 FTP 服务器
5. **下载限速/分片**：超大文件支持 Range 请求与断点续传

---

## 十二、解耦架构符合性说明

本功能严格遵循 [`redame/README.txt`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/redame/README.txt)「解耦开发规范」章节，对照如下：

| 规范条目 | README 要求 | 本功能落地 |
|----------|-------------|------------|
| 第 1 条 | 新增功能先在 services/ 实现业务逻辑 | ✅ `backend/services/data_export_service.py` |
| 第 2 条 | routers/ 只接收请求→调用 service→返回响应 | ✅ `backend/routers/data_export.py` 无业务逻辑 |
| 第 3 条 | 公共工具放入 core/，禁止跨模块复制 | ✅ 复用 `core/workspace.py`、`core/security.py` |
| 第 4 条 | 禁止在 app.py 直接写业务代码 | ✅ 仅在 `api.py` 末尾 `include_router` |
| 第 5 条 | 数据库访问统一通过 database/ | ✅ `from database import db` + `db.add_audit_log` |
| 第 6 条 | 日志统一使用 logger.py | ✅ `from logger import logger` |

### 12.1 四层架构依赖关系

```
┌──────────────────────────────────────────────────────┐
│  routers/data_export.py    (新增，仅做接口层)        │
│    ↓ 调用                                              │
│  services/data_export_service.py (新增，业务逻辑层)   │
│    ↓ 调用                                              │
│  services/docker_manager.py  (既有，Docker 操作)      │
│    ↓ 调用                                              │
│  core/workspace.py           (既有，路径与用户隔离)    │
│  core/security.py            (既有，JWT/命令过滤)      │
│    ↓ 调用                                              │
│  database/                   (既有，db.add_audit_log)  │
└──────────────────────────────────────────────────────┘
```

### 12.2 与 api.py 顶部 docstring 的契合

[`backend/routers/api.py:1-19`](file:///run/user/1000/gvfs/sftp:host=192.168.9.150/home/fox/ros2_web/backend/routers/api.py#L1-L19) 顶部明确：

> 后续可按业务领域进一步拆分为：
> - auth.py      认证相关
> - admin.py     管理员后台
> - ...
> - files.py     文件管理

本功能的 `data_export.py` 即按此预期落地为独立路由文件，是「过渡方案」向「按领域拆分」演进的合理一步。

### 12.3 文件命名规范

- Python 文件统一 `snake_case`：`data_export_service.py`、`data_export.py`
- JavaScript 文件统一 `snake_case`：`data_export.js`（与既有 `terminal.js` 风格一致）
- 常量追加项：`'data-export'`（kebab-case，与 `panel-tools` / `advanced-docker` 等既有面板 ID 一致）

### 12.4 不修改既有代码的边界声明

| 文件 | 改动类型 | 边界说明 |
|------|----------|----------|
| `backend/routers/api.py` | **末尾追加** 2 行 | 仅在文件末尾追加 `import` + `include_router`，不修改任何既有函数 |
| `backend/core/constants.py` | **列表追加** 1 项 | `ALL_PANELS` 末尾追加 `'data-export'`，不修改任何既有项 |
| `frontend/index.html` | **插入** 1 个 card + 1 行 `<script>` | 在 `panel-tools` 内追加；底部 script 区域追加 1 行引用 |
| `frontend/js/sj_script.js` | **不改** | 通过 `data_export.js` 包装 `switchPanel` 实现联动，零侵入 |
| `backend/app.py` | **不改** | 路由通过 `api.py` 的 `include_router` 自动挂载，无需修改 `app.py` |

### 12.5 向后兼容性

- 所有新增 API 路径前缀 `/api/data-export/`，与既有 `/api/files/`、`/api/docker/` 等不冲突
- 新增面板 `data-export` 仅在 `ALL_PANELS` 末尾追加，不影响既有面板的权限校验
- 未被授予 `data-export` 权限的用户不会看到该 card（前端 `hasPermission('data-export')` 失败时隐藏）

================================================================================

                          技术支持

© Boonray 伯镭科技
版本: 4.0-decoupled
日期: 2026-08-21
作者: Fox

================================================================================
