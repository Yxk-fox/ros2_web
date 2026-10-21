#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件管理 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）

router = APIRouter()

# ============================================================
# v3.6 Web 文件管理器（在浏览器中浏览/下载/删除/上传文件）
# ============================================================

def _resolve_user_dir(folder_type: str, current_user: dict, target_user: Optional[str]) -> str:
    """根据 folder_type 解析目标根目录，并校验合法性。

    支持的 folder_type:
        - bags / logs / install / bk / scripts
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    mapping = {
        "bags":    workspace_paths["bag_storage"],
        "logs":    workspace_paths["logs_dir"],
        "install": workspace_paths["host_install"],
        "bk":      workspace_paths["backup_dir"],
        "scripts": workspace_paths["scripts_dir"],
    }
    if folder_type not in mapping:
        raise HTTPException(400, "未知目录类型")
    root = mapping[folder_type]
    validate_user_path(root, current_user, target_user=target_user)
    return root


def _safe_join(root: str, subpath: str) -> str:
    """将 subpath 安全拼接到 root 下，防止路径遍历。"""
    if subpath is None:
        subpath = ""
    # 统一正斜杠
    subpath = subpath.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(root, subpath))
    root_norm = os.path.normpath(root)
    # 必须仍在 root 之下（或就是 root）
    if full != root_norm and not full.startswith(root_norm + os.sep):
        raise HTTPException(400, "非法路径访问")
    return full


@router.get("/api/files/list")
async def list_files(
    folder_type: str,
    subpath: Optional[str] = "",
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('tools'))
):
    """列出指定目录下的文件和子目录。

    返回结构：``{success, items:[{name,type,size,mtime,is_dir}], path, parent, exists}``
    """
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)

    if not os.path.exists(full):
        return {"success": True, "exists": False, "items": [], "path": full, "parent": None}
    if not os.path.isdir(full):
        raise HTTPException(400, "指定路径不是目录")

    items = []
    try:
        for name in sorted(os.listdir(full), key=lambda n: (not os.path.isdir(os.path.join(full, n)), n.lower())):
            p = os.path.join(full, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append({
                "name": name,
                "is_dir": os.path.isdir(p),
                "size": st.st_size if os.path.isfile(p) else 0,
                "mtime": int(st.st_mtime),
            })
    except PermissionError:
        raise HTTPException(403, "无权限访问该目录")

    rel = os.path.relpath(full, root)
    if rel == ".":
        rel = ""
    parent = os.path.dirname(rel) if rel else None
    if parent == "":
        parent = None
    return {
        "success": True,
        "exists": True,
        "items": items,
        "path": full,
        "rel": rel,
        "parent": parent,
        "root_type": folder_type,
        "target_user": target_user,
    }


@router.get("/api/files/download")
async def download_file(
    folder_type: str,
    subpath: str,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('tools'))
):
    """下载文件。"""
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.isfile(full):
        raise HTTPException(404, "文件不存在")
    return FileResponse(full, filename=os.path.basename(full))


@router.post("/api/files/delete")
async def delete_file(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """删除文件或空目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    target_user = data.get("target_user")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.exists(full):
        raise HTTPException(404, "路径不存在")
    if os.path.isdir(full):
        # 防止误删根目录
        if os.path.normpath(full) == os.path.normpath(root):
            raise HTTPException(400, "不允许删除根目录")
        shutil.rmtree(full)
        db.add_audit_log(current_user["username"], "file_delete",
                         f"dir {subpath} target={target_user or 'self'}")
    else:
        os.unlink(full)
        db.add_audit_log(current_user["username"], "file_delete",
                         f"file {subpath} target={target_user or 'self'}")
    return {"success": True, "message": "已删除"}


@router.post("/api/files/mkdir")
async def make_dir(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """在指定目录下创建子目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    target_user = data.get("target_user")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if os.path.exists(full):
        raise HTTPException(400, "路径已存在")
    os.makedirs(full, exist_ok=True)
    db.add_audit_log(current_user["username"], "file_mkdir",
                     f"dir {subpath} target={target_user or 'self'}")
    return {"success": True, "message": "已创建目录"}


@router.post("/api/files/upload")
async def upload_files(
    folder_type: str = Form(...),
    subpath: str = Form(""),
    target_user: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(require_permission('tools'))
):
    """上传一个或多个文件到指定目录。"""
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.isdir(full):
        # 若父目录不存在，自动创建（只到 root 之下）
        os.makedirs(full, exist_ok=True)

    saved = []
    for f in files:
        if not f.filename:
            continue
        # 仅取 basename，防止路径穿越
        safe_name = os.path.basename(f.filename)
        dest = os.path.join(full, safe_name)
        with open(dest, "wb") as out:
            while chunk := await f.read(8 * 1024 * 1024):
                out.write(chunk)
        saved.append(safe_name)
    db.add_audit_log(current_user["username"], "file_upload",
                     f"{len(saved)} files to {subpath} target={target_user or 'self'}")
    return {"success": True, "saved": saved, "count": len(saved)}


@router.post("/api/files/rename")
async def rename_file(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """重命名文件或目录。"""
    folder_type = data.get("folder_type")
    subpath = data.get("subpath", "")
    new_name = data.get("new_name", "").strip()
    target_user = data.get("target_user")
    if not new_name:
        raise HTTPException(400, "新名称不能为空")
    if '/' in new_name or '\\' in new_name:
        raise HTTPException(400, "名称不能包含路径分隔符")
    root = _resolve_user_dir(folder_type, current_user, target_user)
    full = _safe_join(root, subpath)
    if not os.path.exists(full):
        raise HTTPException(404, "路径不存在")
    parent = os.path.dirname(full)
    new_full = os.path.join(parent, new_name)
    if os.path.exists(new_full):
        raise HTTPException(400, "目标名称已存在")
    os.rename(full, new_full)
    db.add_audit_log(current_user["username"], "file_rename",
                     f"{subpath} -> {os.path.join(os.path.dirname(subpath), new_name)} target={target_user or 'self'}")
    return {"success": True, "message": "已重命名"}


@router.post("/api/files/sync-bags")
async def sync_bags_from_containers(
    data: Dict[str, Any],
    current_user: dict = Depends(require_permission('tools'))
):
    """从运行中的ROS2容器同步bag文件到宿主机用户bags目录"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    bag_storage = workspace_paths["bag_storage"]
    container_bag_path = workspace_paths["container_bag_path"]
    container_bag_path_alt = workspace_paths.get("container_bag_path_alt", "/home/boonray/.boonray/bagfiles")
    validate_user_path(bag_storage, current_user)
    os.makedirs(bag_storage, exist_ok=True)

    containers = DockerManager.list_containers(running_only=True, filter_name="ros2_")
    if not containers:
        return {"success": True, "message": "没有运行中的ROS2容器", "synced_count": 0}

    synced_count = 0
    errors = []
    bag_paths_to_check = [container_bag_path, container_bag_path_alt]

    for container in containers:
        container_name = container["name"]
        for bag_path in bag_paths_to_check:
            rc, out, err = DockerManager.run_cmd(
                DockerManager._docker("exec", container_name, "bash", "-c", f"ls -d {bag_path}/rosbag2_* 2>/dev/null || true"),
                timeout=10
            )
            if rc != 0 or not out.strip():
                continue
            bag_dirs = [d.strip() for d in out.strip().split('\n') if d.strip()]
            for bag_dir in bag_dirs:
                bag_name = os.path.basename(bag_dir)
                dest_dir = os.path.join(bag_storage, bag_name)
                if os.path.exists(dest_dir):
                    continue
                rc, out, err = DockerManager.run_cmd(
                    DockerManager._docker("cp", f"{container_name}:{bag_dir}", dest_dir),
                    timeout=120
                )
                if rc == 0:
                    synced_count += 1
                else:
                    errors.append(f"{container_name}:{bag_name} - {err[:200]}")

    msg = f"已同步 {synced_count} 个bag"
    if errors:
        msg += f"，{len(errors)} 个失败"
    db.add_audit_log(current_user["username"], "sync_bags",
                     f"{synced_count} bags target={target_user or 'self'}")
    return {"success": True, "message": msg, "synced_count": synced_count, "errors": errors}


@router.get("/api/system/cloud-env")
async def get_cloud_env():
    """获取当前云环境配置（优先从 cloud.yaml 读取真实 IP，防止配置不同步）"""
    config_dir = os.path.expanduser(CONFIG.get("paths", {}).get("config_dir",
        "~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config"))
    actual_ip = SystemUtils.get_cloud_ip_from_yaml(config_dir)
    if actual_ip and actual_ip != CONFIG["cloud_env"].get("current_ip"):
        CONFIG["cloud_env"]["current_ip"] = actual_ip
        for env_name, env_ip in CONFIG["cloud_env"]["ip_map"].items():
            if env_ip == actual_ip:
                CONFIG["cloud_env"]["current_env"] = env_name
                break
        save_config(CONFIG)
    return {
        "success": True,
        "current_env": CONFIG["cloud_env"]["current_env"],
        "current_ip": CONFIG["cloud_env"]["current_ip"],
        "ip_map": CONFIG["cloud_env"]["ip_map"]
    }

@router.get("/api/system/cloud-status")
async def check_cloud_status():
    """检查云平台连接状态"""
    cloud_ip = CONFIG["cloud_env"]["current_ip"] or "139.196.75.44"
    cloud_port = 9201
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((cloud_ip, cloud_port))
        sock.close()
        connected = result == 0
        return {"success": True, "connected": connected, "ip": cloud_ip, "port": cloud_port}
    except Exception as e:
        return {"success": True, "connected": False, "ip": cloud_ip, "port": cloud_port, "error": str(e)}
