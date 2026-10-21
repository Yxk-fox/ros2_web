#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本管理 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）
from core.cache import _memory_cache  # noqa: F401  -- import * 不导出下划线名称，需显式导入
from core.utils import _prune_backups  # noqa: F401  -- 删除版本时清理 .deleted.* 备份

router = APIRouter()

# ---------- 脚本管理 ----------
@router.get("/api/scripts/launch-files")
async def get_launch_files(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取 launch 文件列表（按用户工作空间隔离）"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    launch_dir = workspace_paths["launch_dir"]
    if not os.path.isdir(launch_dir):
        return {"success": False, "error": f"目录不存在: {launch_dir}"}
    files = [f for f in os.listdir(launch_dir) if f.endswith('.py')]
    return {"success": True, "files": [{"name": f} for f in files], "launch_dir": launch_dir}

@router.post("/api/scripts/generate")
async def generate_scripts(data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """生成 ROS2 启动脚本（固定端口映射 + 索引管理 + 角色配额）

    安全：launch_dir / scripts_dir / logs_dir 强制使用用户工作空间路径，
    不接受客户端传入的值，防止越权访问其他用户的 install 目录。
    配额：管理员最多 26 辆，普通用户最多 15 辆（simulation_launch.py 不计入数量），全局上限 100 辆。
    端口：VNC = 5900 + 车辆索引，Web = 6080 + 车辆索引。
    """
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]

    if not os.path.isdir(host_install):
        return {"success": False, "error": f"安装目录不存在: {host_install}，请先上传 install.zip 安装包"}

    # ★★★ 安全修复：路径强制使用工作空间路径，不接受客户端覆盖 ★★★
    launch_dir = workspace_paths["launch_dir"]
    scripts_dir = workspace_paths["scripts_dir"]
    logs_dir = workspace_paths["logs_dir"]
    # 校验所有路径均在用户工作空间内
    validate_user_path(launch_dir, current_user, target_user=target_user)
    validate_user_path(scripts_dir, current_user, target_user=target_user)
    validate_user_path(logs_dir, current_user, target_user=target_user)
    validate_user_path(host_install, current_user, target_user=target_user)

    cfg = {
        "launch_dir": launch_dir,
        "scripts_dir": scripts_dir,
        "logs_dir": logs_dir,
        "host_install": host_install,
        "host_ws": workspace_paths["host_ws"],
        "container_install": workspace_paths["container_install"],
        "bag_storage": workspace_paths["bag_storage"],
        "container_bag_path": workspace_paths["container_bag_path"],
        "container_bag_path_alt": workspace_paths["container_bag_path_alt"],
        "docker_image": data.get("docker_image", ROS2_DEFAULT["docker_image"]),
        # v5.0：缺失 ROS2 包补全源改为管理员当前生效版本（版本感知）
        "default_host_install": get_admin_install_dir(),
    }
    try:
        user_role = current_user.get("role", "user")
        gen = ROS2ScriptGenerator(cfg, user_paths=workspace_paths, user_role=user_role)
        # v5.1：按当前生效版本生成脚本（多版本共存，其他版本脚本保留）
        version = workspace_paths.get("current_version") or ""
        ids, port_warnings = gen.generate(version=version or None)
        db.add_audit_log(current_user["username"], "generate_scripts",
                         f"{len(ids)} scripts, version={version or '(旧版install)'}")
        # 容器名带 owner 段（与脚本生成器派生规则一致）；v5.1 版本脚本名/容器名带版本标签
        owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
        vtag = ROS2ScriptGenerator._version_tag(version) if version else ""
        generated = []
        for id_ in ids:
            safe = re.sub(r'[^a-zA-Z0-9_]', '_', id_)
            if version:
                generated.append({
                    "name": f"start_docker_ros2_{safe}__{vtag}.sh",
                    "container": f"ros2_{owner}_{vtag}_{safe}",
                    "domain_id": "auto",
                })
            else:
                generated.append({
                    "name": f"start_docker_ros2_{safe}.sh",
                    "container": f"ros2_{owner}_{safe}",
                    "domain_id": "auto",
                })
        return {
            "success": True,
            "warnings": port_warnings,
            "host_install": host_install,
            "version": version or None,
            "generated": generated
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# 安装包上传、检测、目录树
# ============================================================
@router.get("/api/install/status")
def get_install_status(target_user: Optional[str] = None, refresh: Optional[bool] = False, current_user: dict = Depends(get_current_user)):
    """检测当前用户 install 目录状态（带 5 秒缓存）

    v3.6：管理员可通过 ``target_user`` 切换到目标用户空间。
    ``refresh=true`` 时强制跳过缓存，切换用户等场景使用。

    ★ 性能优化：同步 def —— 目录树扫描等阻塞 IO 放入线程池
    """
    cache_key = f"install_status:{current_user['email']}:{target_user or 'self'}"
    if not refresh:
        cached = _memory_cache.get(cache_key)
        if cached:
            return cached

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]
    host_ws = workspace_paths["host_ws"]

    exists = os.path.isdir(host_install)
    has_setup_bash = os.path.isfile(os.path.join(host_install, "setup.bash")) if exists else False
    tree = build_dir_tree(host_install, max_depth=2) if exists else None

    # v3.6：检测各工作目录的存在状态，用于前端提示
    dirs_status = {
        "install": {"path": host_install, "exists": exists},
        "bk":      {"path": workspace_paths["backup_dir"],   "exists": os.path.isdir(workspace_paths["backup_dir"])},
        "bags":    {"path": workspace_paths["bag_storage"],  "exists": os.path.isdir(workspace_paths["bag_storage"])},
        "logs":    {"path": workspace_paths["logs_dir"],     "exists": os.path.isdir(workspace_paths["logs_dir"])},
        "scripts": {"path": workspace_paths["scripts_dir"],  "exists": os.path.isdir(workspace_paths["scripts_dir"])},
    }

    # v5.0：版本目录信息（当前版本 / 可用版本列表 / 旧版 install 是否存在）
    versions = workspace_paths.get("versions")
    if versions is None:
        versions = list_user_versions(host_ws)
    legacy_available = os.path.isdir(os.path.join(host_ws, "install"))

    result = {
        "success": True,
        "exists": exists,
        "has_setup_bash": has_setup_bash,
        "host_install": host_install,
        "host_ws": host_ws,
        "host_bk": workspace_paths["backup_dir"],
        "host_bags": workspace_paths["bag_storage"],
        "host_logs": workspace_paths["logs_dir"],
        "host_scripts": workspace_paths["scripts_dir"],
        "host_bk_backups": workspace_paths["bk_backups_dir"],
        "dirs_status": dirs_status,
        "tree": tree,
        "target_user": workspace_paths.get("target_user"),
        # v5.0 版本管理字段
        "current_version": workspace_paths.get("current_version"),
        "is_versioned": workspace_paths.get("is_versioned", False),
        "versions": versions,
        "legacy_available": legacy_available,
        "message": "安装包已就绪" if has_setup_bash else ("install目录存在但setup.bash缺失，请重新上传" if exists else "未检测到安装包，请上传 install.zip / .tar.gz / .tgz / .tar.bz2")
    }
    _memory_cache.set(cache_key, result, ttl=5)
    return result


# v5.0：Supabase users.current_version 列缺失时的统一提示（PostgREST 不支持 DDL，必须手动执行）
_VERSION_COLUMN_MISSING_HINT = (
    "数据库缺少 current_version 字段，版本选择无法保存。"
    "请管理员在 Supabase SQL Editor 执行："
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS current_version TEXT DEFAULT '';"
)


def _version_column_ready() -> bool:
    """v5.0：检查数据库 users.current_version 列是否就绪（JSON 模式恒为 True）

    Supabase 模式下若启动时探测为缺失，每次调用实时复查一次，
    使管理员在 SQL Editor 补列后无需重启服务即可恢复。
    """
    if not hasattr(db, "current_version_column_ok"):
        return True
    if db.current_version_column_ok:
        return True
    recheck = getattr(db, "recheck_version_column", None)
    if callable(recheck):
        return bool(recheck())
    return False


def _get_target_user_record(current_user: dict, target_user: Optional[str]):
    """获取实际操作目标的用户记录（管理员指定目标用户或当前用户自身）"""
    if target_user:
        return db.get_user(target_user) or db.get_user_by_id(target_user)
    return db.get_user(current_user.get("email")) or db.get_user_by_id(current_user.get("id", ""))


def _set_user_current_version(current_user: dict, target_user: Optional[str], version: str,
                              record_previous: bool = True):
    """v5.0：持久化用户当前选择的 install 版本（写入用户表 current_version 字段）

    v5.1：record_previous=True 时同步记录回滚信息 previous_version
    （{"version": 切换前版本, "switched_at": ISO时间}），供一键回滚使用。

    :param target_user: 管理员操作目标用户空间时为该用户（邮箱/用户名/ID），否则为当前用户自身
    :return: (是否成功, 错误信息)
    """
    if not _version_column_ready():
        return False, _VERSION_COLUMN_MISSING_HINT
    record = _get_target_user_record(current_user, target_user)
    if not record or not record.get("id"):
        logger.warning(f"未找到用户记录，无法保存版本选择: target={target_user or current_user.get('email')}")
        return False, "未找到用户记录，无法保存版本选择（请重新登录后重试）"
    try:
        updates = {"current_version": version or ""}
        if record_previous:
            updates["previous_version"] = {
                "version": record.get("current_version") or "",
                "switched_at": datetime.now().isoformat(timespec="seconds"),
            }
        ok = bool(db.update_user(record["id"], updates))
        if not ok:
            # 再次探测列状态（可能在本次调用中被标记为缺失）
            if not _version_column_ready():
                return False, _VERSION_COLUMN_MISSING_HINT
            return False, "版本切换保存失败，请重试"
        return True, None
    except Exception as e:
        logger.error(f"保存用户版本选择失败: {e}")
        return False, "版本切换保存失败，请重试"


def _get_version_notes(current_user: dict, target_user: Optional[str]) -> Dict[str, str]:
    """v5.1：读取用户版本备注（{版本名: 备注文本}），字段缺失时返回空 dict"""
    record = _get_target_user_record(current_user, target_user)
    if not record:
        return {}
    notes = record.get("version_notes") or {}
    if isinstance(notes, str):
        try:
            notes = json.loads(notes)
        except Exception:
            notes = {}
    return notes if isinstance(notes, dict) else {}


@router.post("/api/install/upload")
async def upload_install_package(
    file: UploadFile = File(...),
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission("scripts"))
):
    """上传并解压 install 安装包

    v3.6：支持 .zip / .tar.gz / .tgz / .tar.bz2 多种压缩格式；
    管理员可通过 ``target_user`` 切换到目标用户空间代为上传。

    v5.0：版本化解压 —— 压缩包解压为 <工作空间>/<版本名>/install/，
    版本名优先取压缩包顶层目录名（如 test_install20260904_x86_ros2_5.0），
    顶层无版本目录时以压缩包文件名命名。上传成功后自动切换到新版本。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]

    filename = (file.filename or "").lower()
    supported_ext = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar")
    if not filename.endswith(supported_ext):
        return {"success": False, "error": f"仅支持以下格式压缩包: {', '.join(supported_ext)}"}

    os.makedirs(host_ws, exist_ok=True)

    # 根据扩展名生成临时文件名（保留原扩展，便于解压器识别）
    ext = ".zip"
    for cand in (".tar.gz", ".tar.bz2", ".tgz", ".tar", ".zip"):
        if filename.endswith(cand):
            ext = cand
            break
    tmp_path = os.path.join(host_ws, f"_upload_{uuid.uuid4().hex}{ext}")
    try:
        size = 0
        with open(tmp_path, "wb") as f:
            while chunk := await file.read(8 * 1024 * 1024):
                f.write(chunk)
                size += len(chunk)
                if size > 5 * 1024 * 1024 * 1024:
                    raise HTTPException(413, "安装包大小超过 5GB 限制")

        # v5.0：版本化解压为 <host_ws>/<版本名>/install/
        # 版本名优先取压缩包顶层目录名，否则使用压缩包文件名（去扩展名）
        base_name = os.path.splitext(os.path.basename(file.filename or "install_version"))[0]
        if ext != ".zip" and base_name.endswith(".tar"):
            base_name = base_name[:-4]
        try:
            version_name = extract_versioned_install(tmp_path, host_ws, base_name)
        except (zipfile.BadZipFile, tarfile.TarError, ValueError) as e:
            return {"success": False, "error": f"压缩包损坏或格式不正确: {e}"}

        new_install = os.path.join(host_ws, version_name, "install")
        if not os.path.isfile(os.path.join(new_install, "setup.bash")):
            return {
                "success": False,
                "error": "解压后未找到 setup.bash，请确保压缩包为正确的 ROS2 install 目录结构",
                "host_install": new_install
            }

        # v5.0：上传成功后自动切换到新版本并持久化
        auto_switched, switch_error = _set_user_current_version(current_user, target_user, version_name)

        # v5.1：失效并后台补算新版本目录大小
        invalidate_version_size_cache(host_ws, version_name)
        queue_version_size_computation(host_ws, [{"version": version_name}])

        _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")

        tree = build_dir_tree(new_install, max_depth=2)
        audit_target = workspace_paths.get("target_user")
        audit_details = f"size={size}, version={version_name}, target={audit_target or 'self'}, auto_switched={auto_switched}"
        db.add_audit_log(current_user["username"], "install_upload", audit_details)
        message = f"安装包上传成功，已生成版本 {version_name}"
        if auto_switched:
            message += " 并自动切换"
        elif switch_error:
            # 文件已解压成功，仅版本选择持久化失败（如 Supabase 缺列）——警告但不抹掉上传成功的事实
            message += f"，但自动切换失败：{switch_error}"
        return {
            "success": True,
            "message": message,
            "version": version_name,
            "auto_switched": auto_switched,
            "host_install": new_install,
            "target_user": audit_target,
            "tree": tree
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传安装包失败: {e}", exc_info=True)
        return {"success": False, "error": f"处理失败: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ============================================================
# v5.0 install 版本管理：版本列表 / 版本切换
# ============================================================
@router.get("/api/install/versions")
def list_install_versions(target_user: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """获取工作空间下的 install 版本列表及当前生效版本

    v5.1：附带版本元数据（mtime/大小，大小后台计算下次请求生效）、
    版本备注（version_notes）、上一版本回滚信息（previous_version）。
    管理员可通过 ``target_user`` 查看目标用户空间的版本。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    versions = workspace_paths.get("versions")
    if versions is None:
        versions = list_user_versions(host_ws)

    # v5.1：合并备注 + 后台补算目录大小（首次请求 size_bytes 为 null，稍后轮询生效）
    notes = _get_version_notes(current_user, target_user)
    for v in versions:
        v["note"] = notes.get(v.get("version") or "", "")
    queue_version_size_computation(host_ws, versions)

    record = _get_target_user_record(current_user, target_user)
    previous = record.get("previous_version") if record else None
    if isinstance(previous, str):
        try:
            previous = json.loads(previous)
        except Exception:
            previous = None

    return {
        "success": True,
        "versions": versions,
        "current_version": workspace_paths.get("current_version"),
        "is_versioned": workspace_paths.get("is_versioned", False),
        "legacy_available": os.path.isdir(os.path.join(host_ws, "install")),
        "host_ws": host_ws,
        "target_user": workspace_paths.get("target_user"),
        # v5.1 版本元数据
        "version_notes": notes,
        "previous_version": previous if isinstance(previous, dict) else None,
    }


@router.post("/api/install/versions/note")
async def set_install_version_note(data: Dict[str, str], current_user: dict = Depends(require_permission("scripts"))):
    """v5.1：编辑版本备注（写入用户表 version_notes JSONB 字段）

    请求体: {"version": "<版本目录名>", "note": "<备注文本，最长500字>", "target_user": "<可选>"}
    """
    version = (data.get("version") or "").strip()
    note = (data.get("note") or "").strip()[:500]
    target_user = data.get("target_user") or None

    if target_user and current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作其他用户的版本备注")
    if not version or not is_valid_version_name(version):
        return {"success": False, "error": "无效的版本名"}

    record = _get_target_user_record(current_user, target_user)
    if not record or not record.get("id"):
        return {"success": False, "error": "未找到用户记录"}

    notes = _get_version_notes(current_user, target_user)
    if note:
        notes[version] = note
    else:
        notes.pop(version, None)

    ok = bool(db.update_user(record["id"], {"version_notes": notes}))
    if not ok:
        return {"success": False, "error": "备注保存失败（数据库可能缺少 version_notes 字段，请先执行 v5.1 迁移 SQL）"}

    owner_label = target_user or current_user.get("username") or "self"
    db.add_audit_log(current_user["username"], "install_version_note",
                     f"target={owner_label}, version={version}, note={note[:50]}{'…' if len(note) > 50 else ''}")
    return {"success": True, "message": "备注已保存", "version": version, "note": note}


@router.post("/api/install/versions/rollback")
async def rollback_install_version(data: Dict[str, str], current_user: dict = Depends(require_permission("scripts"))):
    """v5.1：一键回滚到上一版本（复用版本切换异步联动任务）

    请求体: {"target_user": "<可选，管理员指定>"}
    回滚信息来自最近一次切换时记录的 previous_version；
    回滚本身也是一次切换（被回滚的版本成为新的"上一版本"，支持再次回滚）。
    """
    target_user = data.get("target_user") or None
    if target_user and current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作其他用户的版本")

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    current_version = workspace_paths.get("current_version") or ""

    record = _get_target_user_record(current_user, target_user)
    previous = record.get("previous_version") if record else None
    if isinstance(previous, str):
        try:
            previous = json.loads(previous)
        except Exception:
            previous = None
    if not isinstance(previous, dict) or not previous.get("version", ""):
        return {"success": False, "error": "暂无可回滚的上一版本（首次使用或尚未切换过版本）"}

    rollback_to = previous.get("version") or ""
    if rollback_to == current_version:
        return {"success": False, "error": f"上一版本与当前版本相同（{rollback_to or '旧版 install'}），无需回滚"}

    # 校验回滚目标仍然存在
    if rollback_to and not any(v["version"] == rollback_to for v in list_user_versions(host_ws)):
        return {"success": False, "error": f"上一版本 {rollback_to} 已被删除，无法回滚"}

    owner_label = target_user or current_user.get("username") or "self"
    db.add_audit_log(current_user["username"], "install_version_rollback",
                     f"target={owner_label}, from={current_version or '(旧版install)'}, to={rollback_to or '(旧版install)'}")

    # 复用切换联动任务（回滚目标版本 + 脚本重生成）
    body = {"version": rollback_to}
    if target_user:
        body["target_user"] = target_user
    return await switch_install_version(body, current_user)


# ============================================================
# v5.1 备份目录可视化管理（.deleted/.bak/.replaced.<时间戳>）
# ============================================================
@router.get("/api/install/backups")
def list_install_backups(target_user: Optional[str] = None,
                         current_user: dict = Depends(require_permission("scripts"))):
    """v5.1：列出工作空间下的版本备份目录（删除/替换 install 时自动产生）"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    backups = list_version_backups(host_ws)
    # 后台补算备份目录大小（首次为 null，稍后轮询生效）
    queue_version_size_computation(host_ws, [{"version": b["entry"]} for b in backups])
    return {
        "success": True,
        "backups": backups,
        "host_ws": host_ws,
        "target_user": workspace_paths.get("target_user"),
        "current_version": workspace_paths.get("current_version"),
    }


@router.post("/api/install/backups/restore")
async def restore_install_backup(data: Dict[str, str],
                                 current_user: dict = Depends(require_permission("scripts"))):
    """v5.1：恢复备份目录为可用版本（<备份目录> → <原版本名>）

    请求体: {"entry": "<备份目录名>", "target_user": "<可选>"}
    原版本目录已存在时拒绝恢复（请先删除现有版本）；恢复后不自动切换版本。
    """
    entry = (data.get("entry") or "").strip()
    target_user = data.get("target_user") or None

    if target_user and current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作其他用户空间的备份")

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]

    if not entry or not is_version_backup_entry(entry) or "/" in entry or ".." in entry:
        return {"success": False, "error": "无效的备份目录名"}

    src = os.path.join(host_ws, entry)
    if not os.path.isdir(src):
        return {"success": False, "error": f"备份目录不存在: {entry}"}

    # 从备份目录名解析原版本名（去掉 .deleted/.bak/.replaced.<时间戳> 后缀）
    m = re.match(r"^(.*?)\.(deleted|bak|replaced)\.\d{14}$", entry)
    origin = m.group(1) if m else entry
    dst = os.path.join(host_ws, origin)

    if os.path.exists(dst):
        return {"success": False, "error": f"版本 {origin} 已存在，请先删除该版本再恢复备份"}

    try:
        shutil.move(src, dst)
    except Exception as e:
        return {"success": False, "error": f"恢复失败: {e}"}

    invalidate_version_size_cache(host_ws, origin)
    invalidate_version_size_cache(host_ws, entry)
    _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")

    owner_label = target_user or current_user.get("username") or "self"
    db.add_audit_log(current_user["username"], "install_backup_restore",
                     f"target={owner_label}, entry={entry}, restored_as={origin}")
    return {
        "success": True,
        "message": f"备份已恢复为版本 {origin}（未自动切换，如需使用请在版本列表中切换）",
        "restored_version": origin,
    }


@router.post("/api/install/backups/delete")
async def delete_install_backup(data: Dict[str, str],
                                current_user: dict = Depends(require_permission("scripts"))):
    """v5.1：彻底删除备份目录（不可恢复）

    请求体: {"entry": "<备份目录名>", "target_user": "<可选>"}
    """
    entry = (data.get("entry") or "").strip()
    target_user = data.get("target_user") or None

    if target_user and current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作其他用户空间的备份")

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]

    if not entry or not is_version_backup_entry(entry) or "/" in entry or ".." in entry:
        return {"success": False, "error": "无效的备份目录名"}

    target_dir = os.path.join(host_ws, entry)
    if not os.path.isdir(target_dir):
        return {"success": False, "error": f"备份目录不存在: {entry}"}

    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return {"success": False, "error": f"删除失败: {e}"}

    invalidate_version_size_cache(host_ws, entry)
    _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")

    owner_label = target_user or current_user.get("username") or "self"
    db.add_audit_log(current_user["username"], "install_backup_delete", f"target={owner_label}, entry={entry}")
    return {"success": True, "message": f"备份 {entry} 已彻底删除"}


# ============================================================
# v5.1 版本切换异步联动任务（脚本重生成，耗时 20~30s，进度条轮询）
# ============================================================
_SWITCH_TASK_TTL = 600  # 已完成任务保留 10 分钟供前端轮询
_switch_tasks: Dict[str, dict] = {}
_switch_tasks_lock = threading.Lock()


def _prune_switch_tasks():
    """清理过期/超额的切换任务记录（已完成且超过 TTL）"""
    now = time.time()
    with _switch_tasks_lock:
        stale = [tid for tid, t in _switch_tasks.items()
                 if t.get("status") != "running" and now - t.get("finished_at", now) > _SWITCH_TASK_TTL]
        for tid in stale:
            _switch_tasks.pop(tid, None)
        # 运行中任务数量保护（防泄漏，正常不会触发）
        running = [tid for tid, t in _switch_tasks.items() if t.get("status") == "running"]
        for tid in running[20:]:
            _switch_tasks.pop(tid, None)


def _switch_task_update(task_id: str, **fields):
    with _switch_tasks_lock:
        task = _switch_tasks.get(task_id)
        if task is not None:
            task.update(fields)


def _run_version_switch_task(task_id: str, current_user: dict, target_user: Optional[str],
                             version: str, owner_label: str):
    """v5.1：版本切换联动任务（后台线程执行）

    步骤：保存版本选择（含回滚记录）→ 按新版本重新生成启动脚本 → 失效缓存。
    多版本共存：旧版本脚本/容器不动，新脚本指向新版本路径。
    """
    def _update(pct, message):
        _switch_task_update(task_id, percent=pct, message=message)

    switched = False
    try:
        _update(10, "保存版本选择…")
        ok, error = _set_user_current_version(current_user, target_user, version)
        if not ok:
            raise RuntimeError(error or "版本选择保存失败")
        switched = True

        # 重新解析工作空间路径（按新版本解析 install/launch 目录）
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        host_install = workspace_paths["host_install"]
        host_ws = workspace_paths["host_ws"]
        scripts_dir = workspace_paths["scripts_dir"]

        _update(25, "扫描新版本 launch 文件…")
        if not os.path.isdir(host_install):
            raise RuntimeError(f"新版本 install 目录不存在: {host_install}")

        validate_user_path(host_install, current_user, target_user=target_user)
        validate_user_path(scripts_dir, current_user, target_user=target_user)

        cfg = {
            "launch_dir": workspace_paths["launch_dir"],
            "scripts_dir": scripts_dir,
            "logs_dir": workspace_paths["logs_dir"],
            "host_install": host_install,
            "host_ws": host_ws,
            "container_install": workspace_paths["container_install"],
            "bag_storage": workspace_paths["bag_storage"],
            "container_bag_path": workspace_paths["container_bag_path"],
            "container_bag_path_alt": workspace_paths["container_bag_path_alt"],
            "docker_image": ROS2_DEFAULT["docker_image"],
            "default_host_install": get_admin_install_dir(),
        }

        _update(35, "重新生成启动脚本…")
        gen = ROS2ScriptGenerator(cfg, user_paths=workspace_paths,
                                  user_role=current_user.get("role", "user"))

        def _gen_progress(pct, message):
            # 脚本生成进度映射到 35~90 区间
            _update(35 + int(pct * 0.55), message)

        identifiers, _warnings = gen.generate(version=version or None, progress_cb=_gen_progress)

        _update(95, "刷新缓存…")
        invalidate_version_size_cache(host_ws)
        for email in {current_user["email"], owner_label}:
            _memory_cache.invalidate(prefix=f"install_status:{email}")

        db.add_audit_log(current_user["username"], "install_version_switch",
                         f"target={owner_label}, version={version or '(旧版install)'}, "
                         f"scripts={len(identifiers)}, task_id={task_id}")

        _switch_task_update(task_id, status="done", percent=100,
                            message=f"已切换到{'版本 ' + version if version else '旧版 install 目录'}，"
                                    f"已重新生成 {len(identifiers)} 个启动脚本（旧版本脚本保留）",
                            finished_at=time.time())
    except Exception as e:
        logger.error(f"版本切换联动任务失败 task={task_id}: {e}", exc_info=True)
        if switched:
            message = (f"版本已切换，但启动脚本生成失败：{e}。"
                       f"可手动在「脚本与启动」页面重新生成。")
        else:
            message = f"版本切换失败：{e}"
        _switch_task_update(task_id, status="error", percent=100, message=message,
                            error=str(e), finished_at=time.time())


@router.post("/api/install/versions/switch")
async def switch_install_version(data: Dict[str, str], current_user: dict = Depends(get_current_user)):
    """切换当前用户（或管理员指定的目标用户）的 install 版本（v5.1 异步联动）

    请求体: {"version": "<版本目录名，空串表示回退旧版 install>", "target_user": "<可选，管理员指定>"}

    v5.1：切换后自动按新版本重新生成启动脚本（旧版本脚本/容器保留，多版本共存）。
    脚本生成耗时 20~30s，立即返回 task_id，前端轮询 /api/install/switch-task 展示进度条，
    任务完成后再刷新页面。
    """
    version = (data.get("version") or "").strip()
    target_user = data.get("target_user") or None

    if target_user and current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作其他用户的版本")

    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    owner_label = target_user or current_user.get("username") or "self"
    current_version = workspace_paths.get("current_version") or ""

    if version:
        # 切换到指定版本：校验版本名合法且目录存在
        if not is_valid_version_name(version):
            return {"success": False, "error": f"无效的版本名: {version}"}
        if not any(v["version"] == version for v in list_user_versions(host_ws)):
            return {"success": False, "error": f"版本 {version} 不存在，请刷新版本列表"}
    # 空版本 = 回退旧版 install 路径（目录可能不存在，等同于"未上传安装包"状态，始终允许）

    # 目标与当前一致：无需联动，直接成功
    if version == current_version:
        return {
            "success": True,
            "current_version": version or None,
            "message": f"当前已是{'版本 ' + version if version else '旧版 install 目录'}，无需切换",
            "need_refresh": False,
        }

    _prune_switch_tasks()
    task_id = uuid.uuid4().hex
    with _switch_tasks_lock:
        _switch_tasks[task_id] = {
            "status": "running",
            "percent": 0,
            "message": "正在启动切换任务…",
            "error": None,
            "created_at": time.time(),
            "finished_at": None,
            "version": version,
            "from_version": current_version,
            "target_user": target_user,
            "owner_email": current_user["email"],
            "created_by": current_user.get("username"),
        }

    threading.Thread(
        target=_run_version_switch_task,
        args=(task_id, current_user, target_user, version, owner_label),
        daemon=True, name=f"version-switch-{task_id[:8]}",
    ).start()

    ver_label = f"版本 {version}" if version else "旧版 install 目录"
    return {
        "success": True,
        "task_id": task_id,
        "current_version": version or None,
        "message": f"正在切换到{ver_label}，将自动重新生成启动脚本…",
        "need_refresh": True,
    }


@router.get("/api/install/switch-task")
def get_switch_task_status(task_id: str, current_user: dict = Depends(get_current_user)):
    """v5.1：查询版本切换联动任务进度（前端进度条轮询）"""
    with _switch_tasks_lock:
        task = _switch_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "切换任务不存在或已过期")
        task = dict(task)
    # 权限：任务创建者本人或管理员
    if task.get("owner_email") != current_user.get("email") and current_user.get("role") != "admin":
        raise HTTPException(403, "无权查看该切换任务")
    return {
        "success": True,
        "task_id": task_id,
        "status": task.get("status"),
        "percent": task.get("percent", 0),
        "message": task.get("message", ""),
        "error": task.get("error"),
        "version": task.get("version"),
        "from_version": task.get("from_version"),
        "finished": task.get("status") in ("done", "error"),
    }


@router.get("/api/install/tree")
async def get_install_tree(target_user: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """获取 install 目录树"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_install = workspace_paths["host_install"]
    if not os.path.isdir(host_install):
        return {"success": False, "error": "install 目录不存在"}
    return {"success": True, "tree": build_dir_tree(host_install, max_depth=3), "host_install": host_install}


def _cleanup_user_docker_dir(workspace_paths: dict, keep_scripts: bool = False) -> dict:
    """删除 install 后同步清理用户 Docker 目录（bug修复）

    保证目录结构干净，与初始模板一致：
      Docker/
      ├── bags/          （清空内容）
      ├── bk/
      │   ├── 106证书/139证书/192证书      （.pem 证书保留）
      │   ├── mock_truck/{config,launch}           （生成的 .yaml/.py 删除）
      │   ├── simulation_launches/{config,launch}  （生成的 .yaml/.py 删除）
      │   └── start_docker_template.sh             （模板保留）
      ├── logs/          （清空内容）
      └── scripts/       （清空生成的启动/批量脚本）
    同时清理 bk/.bk_backups 历史备份和 Docker 根目录杂项文件（log.zip 等）。

    v5.1：keep_scripts=True 时保留 scripts 目录（多版本共存——删除当前版本
    时其他版本的脚本需保留，调用方自行清理被删版本的脚本）。
    """
    cleaned = {"bags": 0, "logs": 0, "scripts": 0, "bk_files": 0, "bk_backups": 0, "root_files": 0}
    key_map = {"bag_storage": "bags", "logs_dir": "logs"}
    if not keep_scripts:
        key_map["scripts_dir"] = "scripts"

    # 1) 清空 bags / logs / scripts 目录内容（保留目录本身）
    for key, stat_key in key_map.items():
        d = workspace_paths.get(key)
        if not d or not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            p = os.path.join(d, entry)
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                cleaned[stat_key] += 1
            except Exception as e:
                logger.warning(f"清理 {p} 失败: {e}")

    bk_dir = workspace_paths.get("backup_dir")
    if bk_dir and os.path.isdir(bk_dir):
        # 2) bk 下递归删除生成的 .yaml/.yml/.py/.sh（保留 start_docker_template.sh 模板、
        #    .pem 证书、.rviz 及目录结构；这些生成文件会在下次部署 install 时重新生成）
        for root, _dirs, files in os.walk(bk_dir):
            for f in files:
                if f == "start_docker_template.sh":
                    continue
                if f.endswith((".yaml", ".yml", ".py", ".sh")):
                    p = os.path.join(root, f)
                    try:
                        os.remove(p)
                        cleaned["bk_files"] += 1
                    except Exception as e:
                        logger.warning(f"清理 {p} 失败: {e}")

        # 3) bk/.bk_backups 历史备份（tar.gz）一并清理
        bk_backups = workspace_paths.get("bk_backups_dir")
        if bk_backups and os.path.isdir(bk_backups):
            try:
                shutil.rmtree(bk_backups)
                cleaned["bk_backups"] = 1
            except Exception as e:
                logger.warning(f"清理 {bk_backups} 失败: {e}")

        # 4) Docker 根目录杂项文件（log.zip、误放的脚本等）一并清理，仅保留四个标准目录
        docker_root = os.path.dirname(bk_dir)
        keep_dirs = {"bags", "bk", "logs", "scripts"}
        if os.path.isdir(docker_root):
            for entry in os.listdir(docker_root):
                if entry in keep_dirs:
                    continue
                p = os.path.join(docker_root, entry)
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                    cleaned["root_files"] += 1
                except Exception as e:
                    logger.warning(f"清理 {p} 失败: {e}")

    return cleaned


@router.post("/api/install/delete")
async def delete_install_package(
    target_user: Optional[str] = None,
    version: Optional[str] = None,
    current_user: dict = Depends(require_permission("scripts"))
):
    """删除用户空间的 install 安装包/版本目录

    普通用户只能删除自己空间的 install，管理员可通过target_user删除指定用户的install

    v5.0：``version`` 指定版本目录时删除该版本（<工作空间>/<版本目录>/）；
    不指定时删除当前生效的 install（版本化则为当前版本目录，否则为旧版 install 目录）。
    删除当前生效版本后自动切换到剩余版本（若有），并同步清理 Docker 目录。

    ★★★ bug修复：删除 install 后同步清空用户 Docker 目录下的 bags/logs/scripts
    及 bk 下生成的 .yaml/.py/.sh 文件（含 .bk_backups 历史备份与根目录杂项），
    保证目录结构干净。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    host_ws = workspace_paths["host_ws"]
    current_version = workspace_paths.get("current_version")

    # 检查是否是删除自己的空间，或者是管理员
    is_admin = current_user.get("role") == "admin"
    target = workspace_paths.get("target_user")
    if target and not is_admin:
        return {"success": False, "error": "普通用户只能删除自己空间的install"}

    version = (version or "").strip()
    if version and not is_valid_version_name(version):
        return {"success": False, "error": f"无效的版本名: {version}"}

    # 解析删除目标：指定版本 → <ws>/<version>/install；未指定 → 当前生效 install
    if version:
        delete_target = os.path.join(host_ws, version, "install")
        is_active = (version == current_version)
    else:
        delete_target = workspace_paths["host_install"]
        is_active = True
        if current_version:
            version = current_version

    if not os.path.isdir(delete_target):
        return {"success": False, "error": "install目录不存在，无需删除"}

    try:
        import glob
        if version:
            # v5.0：删除版本目录（备份 <版本名>.deleted.<时间戳>，保留最近2个）
            version_dir = os.path.dirname(delete_target)
            _prune_backups(f"{version}.deleted.", host_ws, keep=2)
            backup_dir = os.path.join(host_ws, f"{version}.deleted.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.move(version_dir, backup_dir)
        else:
            # 旧版 install：备份 install.deleted.<时间戳>（保留最近2个备份）
            backup_pattern = os.path.join(host_ws, "install.bak.*")
            existing_backups = sorted(glob.glob(backup_pattern), reverse=True)
            for old_backup in existing_backups[2:]:  # 只保留最近2个备份
                try:
                    shutil.rmtree(old_backup)
                except Exception:
                    pass

            backup_dir = os.path.join(host_ws, f"install.deleted.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.move(delete_target, backup_dir)

        cleaned = {}
        new_current = None
        # 仅删除当前生效版本时才同步清理 Docker 目录并重选版本
        if is_active:
            if version:
                # v5.1：版本化删除当前版本——保留其他版本脚本，仅清理被删版本的脚本
                cleaned = _cleanup_user_docker_dir(workspace_paths, keep_scripts=True)
                removed_scripts = ROS2ScriptGenerator.remove_version_scripts(
                    workspace_paths["scripts_dir"], version)
                if removed_scripts:
                    cleaned["version_scripts"] = removed_scripts
            else:
                # ★★★ 同步清理 Docker 目录（bags/logs/scripts/bk 生成文件/历史备份/杂项）
                cleaned = _cleanup_user_docker_dir(workspace_paths)

            # v5.0：自动切换到剩余版本（按目录名取最新），无剩余版本则回退旧版 install
            remaining = list_user_versions(host_ws)
            new_current = remaining[-1]["version"] if remaining else ""
            switched, switch_error = _set_user_current_version(current_user, target_user, new_current)
            if not switched:
                logger.warning(f"删除当前版本后自动切换保存失败: {switch_error}")
        elif version:
            # v5.1：删除非当前版本时，联动清理该版本的启动脚本（多版本共存遗留）
            removed_scripts = ROS2ScriptGenerator.remove_version_scripts(
                workspace_paths["scripts_dir"], version)
            if removed_scripts:
                cleaned = {"version_scripts": removed_scripts}

        # v5.1：失效版本目录与备份目录的大小缓存
        invalidate_version_size_cache(host_ws)
        _memory_cache.invalidate(prefix=f"install_status:{current_user['email']}")

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(current_user["username"], "install_delete",
                         f"target={audit_target or 'self'}, version={version or '(旧版)'}, cleaned={cleaned}")

        message = "安装包已删除（已自动备份）"
        if is_active:
            message += "，Docker目录已同步清理"
            if new_current:
                message += f"，已自动切换到版本 {new_current}"
        else:
            message = f"版本 {version} 已删除（已自动备份）"

        return {
            "success": True,
            "message": message,
            "backup_dir": backup_dir,
            "cleaned": cleaned,
            "current_version": new_current if is_active else current_version,
        }
    except Exception as e:
        logger.error(f"删除install失败: {e}", exc_info=True)
        return {"success": False, "error": f"删除失败: {str(e)}"}


# ============================================================
# v3.6 安装目录管理 & 文件夹同步增强 & 备份回滚 & 操作历史
# ============================================================

# install/ -> Docker/bk/ 部署映射表
# 说明：mock_truck 与 simulation_launches 使用完全一致的"整目录复制"逻辑，
# 确保 *_Supervisor_001.yaml / *_Supervisor_001.py 等附加文件也能被复制；
# .pem 证书由 _copy_install_to_bk 统一跳过，不会被覆盖。
INSTALL_TO_BK_MAPPINGS: List[Dict[str, str]] = [
    {
        # 整个 mock_truck/config 目录（含 mock_truck.yaml、mock_truck_Supervisor_001.yaml）
        "src_dir": "mock_truck/share/mock_truck/config",
        "dst_dir": "mock_truck/config",
        "glob": "*",
    },
    {
        # 整个 mock_truck/launch 目录（含 mock_truck_launch.py、mock_truck_Supervisor_001.py）
        "src_dir": "mock_truck/share/mock_truck/launch",
        "dst_dir": "mock_truck/launch",
        "glob": "*",
    },
    {
        # 整个 simulation_launches/config 目录
        "src_dir": "simulation_launches/share/simulation_launches/config",
        "dst_dir": "simulation_launches/config",
        "glob": "*",
    },
    {
        # 整个 simulation_launches/launch 目录（含 simulation_launch.py、Supervisor_001.py）
        "src_dir": "simulation_launches/share/simulation_launches/launch",
        "dst_dir": "simulation_launches/launch",
        "glob": "*",
    },
]

# ============================================================
# bk 目录白名单：以下文件/目录在任何部署/清空/回滚操作中都不应被修改或删除
# 证书目录（106证书/139证书/192证书）和启动模板由管理员手动维护，
# 部署流程只负责镜像更新 mock_truck 和 simulation_launches。
# ============================================================

# bk 根目录下受保护的文件/目录名（精确匹配）
BK_PROTECTED_NAMES = {
    "106证书",
    "139证书",
    "192证书",
    "start_docker_template.sh",
}

# 受保护的文件名模式（fnmatch 语法，在任意子目录下匹配）
BK_PROTECTED_PATTERNS = ("*.pem",)

# 允许部署/清空/回滚操作的子目录（白名单之外的子目录一律不动）
BK_DEPLOYABLE_SUBDIRS = (
    "mock_truck/config",
    "mock_truck/launch",
    "simulation_launches/config",
    "simulation_launches/launch",
    "mock_truck",
    "simulation_launches",
)


def _is_bk_protected(name: str) -> bool:
    """判断 bk 目录下的文件/目录名是否受白名单保护（不应被修改或删除）。

    匹配规则：
    1. 精确命中 BK_PROTECTED_NAMES（如 ``106证书``、``start_docker_template.sh``）
    2. 通配命中 BK_PROTECTED_PATTERNS（如 ``*.pem``）
    """
    if name in BK_PROTECTED_NAMES:
        return True
    import fnmatch
    for pat in BK_PROTECTED_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


# 单次操作保留的最近备份数量
BK_BACKUP_KEEP = 5

# 视为"安装目录相关"操作的审计 action 白名单
INSTALL_AUDIT_ACTIONS = {
    "install_upload", "install_deploy", "bk_clean", "bk_copy_from_install",
    "bk_rollback", "sync_folder", "upload_install",
}


def _backup_bk_dir(bk_dir: str, backups_dir: str, op_type: str) -> Optional[str]:
    """将 Docker/bk 目录打包备份到 .bk_backups/bk_backup_<时间戳>_<op>.tar.gz。

    返回备份文件绝对路径；备份失败返回 None。
    """
    if not os.path.isdir(bk_dir):
        return None
    try:
        os.makedirs(backups_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"bk_backup_{ts}_{op_type}.tar.gz"
        backup_path = os.path.join(backups_dir, backup_name)
        def _exclude_backups(tarinfo):
            """排除 .bk_backups 目录及其内容，避免备份指数级膨胀。"""
            parts = tarinfo.name.split("/")
            if ".bk_backups" in parts:
                return None
            return tarinfo

        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(bk_dir, arcname="bk", filter=_exclude_backups)
        # 保留最近 BK_BACKUP_KEEP 个备份
        backups = sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
        )
        for old in backups[:-BK_BACKUP_KEEP]:
            try:
                os.remove(old)
            except Exception:
                pass
        return backup_path
    except Exception as e:
        logger.error(f"备份 bk 目录失败: {e}", exc_info=True)
        return None


def _restore_bk_dir(bk_dir: str, backup_path: str) -> bool:
    """从备份包恢复 Docker/bk 目录

    白名单保护：只回滚 ``mock_truck`` 和 ``simulation_launches`` 子目录，
    证书目录（106证书/139证书/192证书）和 ``start_docker_template.sh`` 保持不动。
    子目录内的 ``*.pem`` 文件同样受保护不被覆盖（证书由管理员单独维护）。
    """
    if not os.path.isfile(backup_path):
        return False
    try:
        import tempfile
        # 解压到临时目录，避免直接覆盖 bk_dir 中的受保护文件
        with tempfile.TemporaryDirectory(prefix="bk_restore_") as tmp_dir:
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(tmp_dir)
            # tar 包内根目录为 bk，定位到实际内容目录
            content_dir = os.path.join(tmp_dir, "bk")
            if not os.path.isdir(content_dir):
                content_dir = tmp_dir
            # 只恢复 mock_truck 和 simulation_launches 子目录
            os.makedirs(bk_dir, exist_ok=True)
            for sub in ("mock_truck", "simulation_launches"):
                src_sub = os.path.join(content_dir, sub)
                if not os.path.isdir(src_sub):
                    continue
                dst_sub = os.path.join(bk_dir, sub)
                # 清空目标子目录（白名单：保留 *.pem 证书文件）
                if os.path.isdir(dst_sub):
                    SystemUtils.clean_directory(dst_sub, keep_patterns=BK_PROTECTED_PATTERNS)
                else:
                    os.makedirs(dst_sub, exist_ok=True)
                # 从备份复制到 bk（白名单：跳过 *.pem）
                for root, _dirs, files in os.walk(src_sub):
                    rel = os.path.relpath(root, src_sub)
                    dst_root = dst_sub if rel == "." else os.path.join(dst_sub, rel)
                    os.makedirs(dst_root, exist_ok=True)
                    for fname in files:
                        if _is_bk_protected(fname):
                            continue
                        shutil.copy2(os.path.join(root, fname), os.path.join(dst_root, fname))
        return True
    except Exception as e:
        logger.error(f"恢复 bk 目录失败: {e}", exc_info=True)
        return False


def _copy_install_to_bk(host_install: str, bk_dir: str) -> Dict[str, Any]:
    """根据 INSTALL_TO_BK_MAPPINGS 把 install 目录中的文件复制到 Docker/bk。

    返回 ``{"success": True, "copied": [...], "skipped": [...]}``。

    白名单保护：命中 ``BK_PROTECTED_PATTERNS``（如 ``*.pem``）的文件一律跳过，
    避免敏感凭证被同步到 bk 目录。部署只镜像 mock_truck 和 simulation_launches。
    """
    copied: List[str] = []
    skipped: List[str] = []
    if not os.path.isdir(host_install):
        return {"success": False, "copied": copied, "skipped": skipped, "error": "install 目录不存在"}
    os.makedirs(bk_dir, exist_ok=True)
    for m in INSTALL_TO_BK_MAPPINGS:
        try:
            if "src_dir" in m:
                src_dir = os.path.join(host_install, m["src_dir"])
                dst_dir = os.path.join(bk_dir, m["dst_dir"])
                if not os.path.isdir(src_dir):
                    logger.warning(f"install -> bk: 源目录不存在: {src_dir}")
                    skipped.append(m["src_dir"])
                    continue
                os.makedirs(dst_dir, exist_ok=True)
                matches = glob.glob(os.path.join(src_dir, m.get("glob", "*")))
                if not matches:
                    logger.warning(f"install -> bk: 源目录为空或 glob 无匹配: {src_dir} (glob={m.get('glob', '*')})")
                    skipped.append(f"{m['src_dir']} (空目录)")
                    continue
                for f in matches:
                    if os.path.isfile(f):
                        fname = os.path.basename(f)
                        # 白名单：跳过受保护文件（*.pem 证书等）
                        if _is_bk_protected(fname):
                            skipped.append(os.path.relpath(f, host_install))
                            continue
                        dst = os.path.join(dst_dir, fname)
                        shutil.copy2(f, dst)
                        copied.append(os.path.relpath(dst, bk_dir))
            else:
                src = os.path.join(host_install, m["src"])
                dst = os.path.join(bk_dir, m["dst"])
                if not os.path.isfile(src):
                    logger.warning(f"install -> bk: 源文件不存在: {src}")
                    skipped.append(m["src"])
                    continue
                # 白名单：单文件映射也跳过受保护文件
                if _is_bk_protected(os.path.basename(src)):
                    skipped.append(m["src"])
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(os.path.relpath(dst, bk_dir))
        except Exception as e:
            logger.warning(f"复制 install -> bk 失败: {m}, {e}")
            skipped.append(f"{m.get('src', m.get('src_dir', '?'))}: {e}")
    if not copied:
        return {
            "success": False,
            "copied": copied,
            "skipped": skipped,
            "error": "未复制任何文件，请检查 install 包是否包含 mock_truck/simulation_launches 的 config 和 launch 目录",
        }
    return {"success": True, "copied": copied, "skipped": skipped}


def _clean_bk_subdir(bk_dir: str, sub: str) -> Dict[str, Any]:
    """清空 Docker/bk 下的指定子目录（mock_truck/config 等）。

    ``sub`` 取值：``mock_truck/config``、``mock_truck/launch``、
    ``simulation_launches/config``、``simulation_launches/launch``、``all``。
    """
    valid_subs = {
        "mock_truck/config", "mock_truck/launch",
        "simulation_launches/config", "simulation_launches/launch",
        "all",
    }
    if sub not in valid_subs:
        return {"success": False, "error": f"未知子目录: {sub}"}
    if not os.path.isdir(bk_dir):
        return {"success": False, "error": "bk 目录不存在"}
    targets = []
    if sub == "all":
        for s in valid_subs - {"all"}:
            targets.append(s)
    else:
        targets.append(sub)
    cleaned: List[str] = []
    for t in targets:
        path = os.path.join(bk_dir, t)
        if not os.path.isdir(path):
            cleaned.append(f"{t} (不存在)")
            continue
        try:
            # 白名单：清空目录时保留受保护文件（*.pem 证书等，部署不会重新复制证书）
            ok, msg = SystemUtils.clean_directory(path, keep_patterns=BK_PROTECTED_PATTERNS)
            cleaned.append(f"{t} ({'清空' if ok else '失败'})")
        except Exception as e:
            cleaned.append(f"{t} (失败: {e})")
    return {"success": True, "cleaned": cleaned}


@router.get("/api/install/workspace-users")
async def list_workspace_users(current_user: dict = Depends(require_admin)):
    """获取管理员下拉切换器可选用户列表（仅 role=user 的普通用户）。

    返回 ``[{username, email, home_folder_path}, ...]``，并附加 ``admin`` 自身。
    """
    try:
        users = db.get_all_users()
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        users = {}
    result = [{
        "username": "admin",
        "email": "admin",
        "home_folder_path": os.path.expanduser("~/robotruck_ros2"),
    }]
    for key, info in users.items():
        if not isinstance(info, dict):
            continue
        if info.get("role") != "user":
            continue
        username = info.get("username") or generate_username_from_email(info.get("email", ""))
        if not username:
            continue
        result.append({
            "username": username,
            "email": info.get("email", ""),
            "home_folder_path": info.get("home_folder_path") or os.path.expanduser(f"~/robotruck_ros2/{username}"),
        })
    return {"success": True, "users": result, "current_user": current_user.get("username")}


@router.post("/api/install/deploy")
async def deploy_install_to_bk(data: Dict[str, Any], current_user: dict = Depends(require_permission('scripts'))):
    """上传后的部署：从 install 复制新配置到 Docker/bk（覆盖同名文件，带备份）

    v3.8：默认 ``clean=False``，仅覆盖同名文件，不执行删除操作，
    符合"不要清空 bk，要替换（cp 过去）"的要求。
    保留 ``clean`` 参数供管理员显式启用旧清空流程（向后兼容）。

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "clean": false,                # 是否清空 bk 目录（默认 false，仅覆盖）
            "backup": true                 # 是否生成备份包（默认 true）
        }
    """
    target_user = data.get("target_user")
    clean = data.get("clean", False)
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        host_install = workspace_paths["host_install"]
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        if not os.path.isdir(host_install):
            return {"success": False, "error": f"install 目录不存在: {host_install}，请先上传安装包"}

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, "install_deploy")

        cleaned: List[str] = []
        if clean:
            if os.path.isdir(bk_dir):
                for sub in [
                    "mock_truck/config", "mock_truck/launch",
                    "simulation_launches/config", "simulation_launches/launch",
                ]:
                    path = os.path.join(bk_dir, sub)
                    if os.path.isdir(path):
                        for item in os.listdir(path):
                            p = os.path.join(path, item)
                            # 白名单：保留受保护文件（*.pem 证书等，部署不会重新复制证书）
                            if _is_bk_protected(item):
                                continue
                            try:
                                if os.path.isfile(p) or os.path.islink(p):
                                    os.unlink(p)
                                elif os.path.isdir(p):
                                    shutil.rmtree(p)
                            except Exception as e:
                                logger.warning(f"清理 {p} 失败: {e}")
                        cleaned.append(sub)

        copy_result = _copy_install_to_bk(host_install, bk_dir)

        audit_target = workspace_paths.get("target_user")
        audit_details = (
            f"target={audit_target or 'self'} clean={clean} backup={backup_path or 'none'} "
            f"copied={len(copy_result.get('copied', []))} skipped={len(copy_result.get('skipped', []))}"
        )
        db.add_audit_log(current_user["username"], "install_deploy", audit_details)

        if not copy_result["success"]:
            return {
                "success": False,
                "cleaned": cleaned,
                "copied": copy_result.get("copied", []),
                "skipped": copy_result.get("skipped", []),
                "backup": backup_path,
                "message": copy_result.get("error", "部署失败"),
                "target_user": audit_target,
            }
        return {
            "success": True,
            "cleaned": cleaned,
            "copied": copy_result.get("copied", []),
            "skipped": copy_result.get("skipped", []),
            "backup": backup_path,
            "message": "部署完成",
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"install_deploy 失败: {e}", exc_info=True)
        return {"success": False, "error": f"部署失败: {str(e)}"}


@router.post("/api/system/bk/clean")
async def bk_clean(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """清空 bk 子目录（mock_truck/config 等）

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "sub": "mock_truck/config",   # 或 "all"
            "backup": true
        }
    """
    target_user = data.get("target_user")
    sub = data.get("sub", "all")
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, f"bk_clean_{sub.replace('/', '_')}")

        result = _clean_bk_subdir(bk_dir, sub)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_clean",
            f"sub={sub} target={audit_target or 'self'} backup={backup_path or 'none'}",
        )
        return {
            "success": result["success"],
            "cleaned": result.get("cleaned", []),
            "error": result.get("error"),
            "backup": backup_path,
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_clean 失败: {e}", exc_info=True)
        return {"success": False, "error": f"清空失败: {str(e)}"}


@router.post("/api/system/bk/copy-from-install")
async def bk_copy_from_install(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """从 install 复制配置到 bk（不清空，仅覆盖同名文件）

    请求体::

        {
            "target_user": "shijie_guo",   # 可选，仅管理员
            "backup": true
        }
    """
    target_user = data.get("target_user")
    backup = data.get("backup", True)

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        host_install = workspace_paths["host_install"]
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]

        if not os.path.isdir(host_install):
            return {"success": False, "error": f"install 目录不存在: {host_install}"}

        backup_path = None
        if backup:
            backup_path = _backup_bk_dir(bk_dir, backups_dir, "bk_copy_from_install")

        result = _copy_install_to_bk(host_install, bk_dir)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_copy_from_install",
            f"target={audit_target or 'self'} backup={backup_path or 'none'} copied={len(result.get('copied', []))}",
        )
        return {
            "success": result["success"],
            "copied": result.get("copied", []),
            "skipped": result.get("skipped", []),
            "backup": backup_path,
            "target_user": audit_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_copy_from_install 失败: {e}", exc_info=True)
        return {"success": False, "error": f"复制失败: {str(e)}"}


@router.get("/api/system/bk/backups")
async def list_bk_backups(target_user: Optional[str] = None, current_user: dict = Depends(require_permission('tools'))):
    """列出当前（或目标）用户的所有 bk 备份包"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    backups_dir = workspace_paths["bk_backups_dir"]
    backups: List[Dict[str, Any]] = []
    if os.path.isdir(backups_dir):
        for f in sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        ):
            try:
                st = os.stat(f)
                backups.append({
                    "name": os.path.basename(f),
                    "path": f,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except Exception:
                continue
    return {"success": True, "backups": backups, "target_user": workspace_paths.get("target_user")}


@router.post("/api/system/bk/rollback")
async def bk_rollback(data: Dict[str, Any], current_user: dict = Depends(require_permission('tools'))):
    """回滚到指定备份包

    请求体::

        {
            "target_user": "shijie_guo",
            "backup": "bk_backup_20260720_120000_install_deploy.tar.gz"
        }
    """
    target_user = data.get("target_user")
    backup_name = data.get("backup")
    if not backup_name:
        return {"success": False, "error": "缺少 backup 参数"}

    # 防止路径遍历
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+", backup_name):
        return {"success": False, "error": "备份包名非法"}

    try:
        workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
        bk_dir = workspace_paths["backup_dir"]
        backups_dir = workspace_paths["bk_backups_dir"]
        backup_path = os.path.join(backups_dir, backup_name)
        if not os.path.isfile(backup_path):
            return {"success": False, "error": f"备份包不存在: {backup_name}"}

        ok = _restore_bk_dir(bk_dir, backup_path)

        audit_target = workspace_paths.get("target_user")
        db.add_audit_log(
            current_user["username"],
            "bk_rollback",
            f"backup={backup_name} target={audit_target or 'self'} result={'ok' if ok else 'fail'}",
        )
        return {
            "success": ok,
            "backup": backup_path,
            "target_user": audit_target,
            "message": "回滚成功" if ok else "回滚失败，请查看日志",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bk_rollback 失败: {e}", exc_info=True)
        return {"success": False, "error": f"回滚失败: {str(e)}"}


@router.get("/api/system/bk/history")
async def list_bk_history(
    target_user: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(require_permission('tools')),
):
    """获取当前（或目标）用户的安装目录相关操作历史

    合并审计日志和备份包信息，按时间倒序返回。
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    audit_target = workspace_paths.get("target_user")

    # 1. 取审计日志
    try:
        all_logs = db.get_audit_logs(limit=500)
    except Exception:
        all_logs = []

    # 2. 过滤相关 action
    target_filter = None
    if audit_target:
        target_filter = f"target={audit_target}"
    elif current_user.get("role") != "admin":
        # 非管理员仅看自己的记录
        target_filter = f"target=self"

    history: List[Dict[str, Any]] = []
    for log in all_logs:
        if not isinstance(log, dict):
            continue
        action = log.get("action", "")
        if action not in INSTALL_AUDIT_ACTIONS:
            continue
        details = log.get("details", "")
        # 简单按 target= 过滤
        if target_filter and target_filter not in details:
            # 对于无 target= 字段的旧日志，仅管理员能看见
            if current_user.get("role") == "admin" and "target=" not in details:
                pass
            else:
                continue
        history.append({
            "timestamp": log.get("timestamp"),
            "user": log.get("username"),
            "action": action,
            "details": details,
            "backup": _extract_backup_from_details(details),
        })

    history = history[:limit]

    # 3. 合并备份包信息
    backups_dir = workspace_paths["bk_backups_dir"]
    backup_files: List[Dict[str, Any]] = []
    if os.path.isdir(backups_dir):
        for f in sorted(
            glob.glob(os.path.join(backups_dir, "bk_backup_*.tar.gz")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        ):
            try:
                st = os.stat(f)
                backup_files.append({
                    "name": os.path.basename(f),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except Exception:
                continue

    return {
        "success": True,
        "history": history,
        "backups": backup_files,
        "target_user": audit_target,
    }


def _extract_backup_from_details(details: str) -> Optional[str]:
    """从审计 details 字符串中提取 backup=xxx 的备份文件名"""
    if not details:
        return None
    m = re.search(r"backup=([^\s]+)", details)
    if not m:
        return None
    val = m.group(1)
    if val in ("none", "None", "null"):
        return None
    return os.path.basename(val)


@router.get("/api/ports/used")
async def get_used_ports_api(current_user: dict = Depends(get_current_user)):
    """获取当前宿主机已占用端口列表（管理员可用）"""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可查看端口占用情况")
    used = sorted(get_used_ports())
    return {"success": True, "used_ports": used, "count": len(used)}


@router.get("/api/scripts/list")
def list_scripts(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """列出已生成的启动脚本

    ★ 性能优化：同步 def —— 目录扫描放入线程池
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    scripts = [f for f in os.listdir(scripts_dir) if f.startswith("start_docker_ros2_") and f.endswith(".sh")]
    scripts.sort(key=lambda n: [int(p) if p.isdigit() else p.lower()
                                for p in re.split(r'(\d+)', n)])
    return {"success": True, "scripts": scripts, "scripts_dir": scripts_dir}

@router.delete("/api/scripts/clear-all")
async def clear_all_scripts(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """清空所有已生成的启动脚本"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    removed = 0
    for f in os.listdir(scripts_dir):
        if f.endswith(".sh"):
            os.remove(os.path.join(scripts_dir, f))
            removed += 1
    db.add_audit_log(current_user["username"], "clear_scripts", f"清空 {removed} 个脚本")
    return {"success": True, "removed": removed, "message": f"已清空 {removed} 个脚本"}

@router.get("/api/scripts/default-paths")
def get_default_paths(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取默认路径配置（根据用户角色返回对应工作空间路径）

    ★ 性能优化：同步 def
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    return {
        "success": True,
        "host_install": workspace_paths["host_install"],
        "container_install": workspace_paths["container_install"],
        "bag_storage": workspace_paths["bag_storage"],
        "container_bag_path": workspace_paths.get("container_bag_path", "/root/robotruck_ros2/bags"),
        "launch_dir": workspace_paths["launch_dir"],
        "scripts_dir": workspace_paths["scripts_dir"],
        "logs_dir": workspace_paths["logs_dir"],
        "docker_image": ROS2_DEFAULT["docker_image"]
    }

@router.get("/api/scripts/quota")
def get_quota_status(target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """查询当前用户的配额使用情况

    ★ 性能优化：同步 def —— 端口扫描 + 全局脚本目录扫描放入线程池
    """
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    user_role = current_user.get("role", "user")

    from services.script_generator import ROS2ScriptGenerator as Gen
    # v5.1：角色配额按当前生效版本计数（多版本共存时其他版本脚本不占本版本配额）
    version = workspace_paths.get("current_version") or ""
    current_count = Gen._count_scripts_in_dir(scripts_dir, version=version)
    global_count = Gen.get_global_script_count()
    role_quota = Gen.ADMIN_QUOTA if user_role == "admin" else Gen.USER_QUOTA
    used_indices = Gen.get_all_used_indices()
    available_indices = [i for i in range(Gen.GLOBAL_MAX) if i not in used_indices]

    return {
        "success": True,
        "user_role": user_role,
        "role_quota": role_quota,
        "current_count": current_count,
        "role_remaining": max(0, role_quota - current_count),
        "global_max": Gen.GLOBAL_MAX,
        "global_count": global_count,
        "global_remaining": max(0, Gen.GLOBAL_MAX - global_count),
        "used_indices": sorted(used_indices),
        "available_indices": available_indices,
        "available_count": len(available_indices),
        # v5.1：当前版本口径说明
        "current_version": version or None,
    }

@router.get("/api/scripts/run-report")
def get_run_report(range: str = "7d", current_user: dict = Depends(require_permission('scripts'))):
    """运行报告聚合查询（T-5.2-04，v5.2）

    参数：
      range  时间范围：1h / 24h / 7d / 30d

    返回：汇总统计 + 按脚本/用户/版本分组 + 时间线 + 最近 20 条明细
    """
    from services.run_records import query_report, RANGE_CONFIG as RUN_RANGE_CONFIG
    try:
        report = query_report(range)
        return {"success": True, **report, "available_ranges": sorted(RUN_RANGE_CONFIG.keys())}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"运行报告查询失败: {e}", exc_info=True)
        return {"success": False, "error": f"运行报告查询失败: {str(e)}"}

@router.get("/api/scripts/{script_name}/content")
async def get_script_content(script_name: str, target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """获取脚本文件内容"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"success": True, "content": content}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.put("/api/scripts/{script_name}")
async def update_script(script_name: str, data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """更新脚本文件内容"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    new_content = data.get("content")
    if new_content is None:
        raise HTTPException(400, "缺少 content")
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.chmod(full_path, os.stat(full_path).st_mode | 0o111)
        db.add_audit_log(current_user["username"], "update_script", script_name)
        return {"success": True, "message": "已更新"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/api/scripts/{script_name}")
async def delete_script(script_name: str, target_user: str = None, current_user: dict = Depends(require_permission('scripts'))):
    """删除脚本文件"""
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script_name)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(404, "脚本不存在")
    try:
        os.remove(full_path)
        db.add_audit_log(current_user["username"], "delete_script", script_name)
        return {"success": True, "message": "已删除"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/api/scripts/batch-execute")
async def batch_execute_scripts(data: Dict[str, Any], current_user: dict = Depends(require_permission('scripts'))):
    """批量执行启动脚本（顺序/并行）"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts = data.get("scripts", [])
    mode = data.get("mode", "顺序")
    retry_count = int(data.get("retry_count", 0))
    retry_delay = int(data.get("retry_delay", 5))
    if not scripts:
        raise HTTPException(400, "未选择脚本")
    scripts_dir = workspace_paths["scripts_dir"]
    results = []
    def run_one_with_retry(name):
        """执行单个脚本（支持重试）"""
        full_path = os.path.join(scripts_dir, name)
        validate_user_path(full_path, current_user, target_user=target_user)
        if not os.path.isfile(full_path):
            return {"name": name, "success": False, "error": "文件不存在"}
        for attempt in range(retry_count + 1):
            rc, out, err = DockerManager.run_cmd(["bash", full_path], timeout=300)
            if rc == 0:
                return {"name": name, "success": True, "stdout": out, "stderr": err, "attempts": attempt + 1}
            if attempt < retry_count:
                logger.info(f"脚本 {name} 第 {attempt+1} 次执行失败，{retry_delay}s 后重试...")
                time.sleep(retry_delay)
        return {"name": name, "success": False, "stdout": out, "stderr": err, "attempts": retry_count + 1}
    if mode == "顺序":
        for name in scripts:
            results.append(run_one_with_retry(name))
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(scripts)) as executor:
            future_results = [executor.submit(run_one_with_retry, name) for name in scripts]
            for future in concurrent.futures.as_completed(future_results):
                results.append(future.result())
    db.add_audit_log(current_user["username"], "batch_execute_scripts", f"{len(scripts)} scripts, mode={mode}")
    # 批量登记容器归属（成功执行的脚本对应的容器归当前用户所有）
    for r in results:
        name = r.get("name", "")
        if r.get("success") and name.startswith("start_docker_ros2_") and name.endswith(".sh"):
            id_part = name[len("start_docker_ros2_"):-len(".sh")]
            owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
            container_name = f"ros2_{owner}_{id_part}"
            rc_cid, cid_out, _ = DockerManager.run_cmd(
                DOCKER_PREFIX.split() + ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}"]
            )
            cid = cid_out.strip()[:12] if rc_cid == 0 and cid_out.strip() else ""
            rc_img, img_out, _ = DockerManager.run_cmd(
                DockerManager._docker("inspect", "--format", "{{.Config.Image}}", container_name)
            )
            img = img_out.strip() if rc_img == 0 else ""
            db.register_container(cid, container_name, img, "running", current_user.get("id"))
    # T-5.2-04：批量记录运行事件
    from services.run_records import record_run
    for r in results:
        record_run("start", current_user.get("username", ""),
                   script_name=r.get("name", ""), success=r.get("success", False),
                   error=(r.get("stderr", "") or "")[:500])
    return {"success": True, "results": results}

@router.post("/api/scripts/execute")
async def execute_script(data: Dict[str, str], current_user: dict = Depends(require_permission('scripts'))):
    """执行单个启动脚本"""
    target_user = data.get("target_user")
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    script = data.get("script")
    scripts_dir = workspace_paths["scripts_dir"]
    full_path = os.path.join(scripts_dir, script)
    validate_user_path(full_path, current_user, target_user=target_user)
    if not os.path.isfile(full_path):
        raise HTTPException(400, "脚本不存在")
    rc, out, err = DockerManager.run_cmd(["bash", full_path], timeout=300)
    db.add_audit_log(current_user["username"], "execute_script", script)
    # 脚本执行成功后，根据脚本名登记容器归属
    if rc == 0:
        await broadcast_log("info", f"脚本 {script} 执行成功")
        # 从脚本名提取容器名（start_docker_ros2_xxx.sh -> ros2_{owner}_xxx）
        base = script
        if base.startswith("start_docker_ros2_") and base.endswith(".sh"):
            id_part = base[len("start_docker_ros2_"):-len(".sh")]
            owner = ROS2ScriptGenerator._owner_from_host_ws(workspace_paths["host_ws"])
            container_name = f"ros2_{owner}_{id_part}"
            # 反查容器 ID
            rc_cid, cid_out, _ = DockerManager.run_cmd(
                DOCKER_PREFIX.split() + ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}"]
            )
            cid = cid_out.strip()[:12] if rc_cid == 0 and cid_out.strip() else ""
            # 反查镜像
            rc_img, img_out, _ = DockerManager.run_cmd(
                DockerManager._docker("inspect", "--format", "{{.Config.Image}}", container_name)
            )
            img = img_out.strip() if rc_img == 0 else ""
            db.register_container(cid, container_name, img, "running", current_user.get("id"))
    else:
        await broadcast_log("error", f"脚本 {script} 执行失败: {err}")
    # T-5.2-04：记录运行事件（container_name 仅成功时赋值，用 locals 安全取值）
    from services.run_records import record_run
    record_run("start", current_user.get("username", ""), script_name=script,
               container_name=locals().get("container_name", ""),
               success=(rc == 0), error=(err or "")[:500])
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/scripts/remove-gpu")
async def remove_gpu_from_scripts(data: Dict[str, str] = None, current_user: dict = Depends(require_permission('scripts'))):
    """从启动脚本中移除 GPU 相关参数"""
    target_user = data.get("target_user") if data else None
    workspace_paths = get_user_workspace_paths(current_user, target_user=target_user)
    scripts_dir = workspace_paths["scripts_dir"]
    if not os.path.isdir(scripts_dir):
        return {"success": False, "error": "目录不存在"}
    scripts = [f for f in os.listdir(scripts_dir) if f.startswith("start_docker_ros2_") and f.endswith(".sh")]
    patterns = [
        r'\s*--cpus=[\d\.]+\s*\\?\s*',
        r'\s*--memory=[\d\.]+g\s*\\?\s*',
        r'\s*--gpus\s+all\s*\\?\s*',
        r'\s*--shm-size=[\d\.]+g\s*\\?\s*',
        r'\s*--env=NVIDIA_VISIBLE_DEVICES=all\s*\\?\s*',
        r'\s*--env=NVIDIA_DRIVER_CAPABILITIES=all\s*\\?\s*',
        r'\s*--env=CUDA_VISIBLE_DEVICES=[\d\.]+\s*\\?\s*',
        r'\s*--env=TF_GPU_ALLOCATOR=cuda_malloc_async\s*\\?\s*',
    ]
    modified = 0
    for script in scripts:
        path = os.path.join(scripts_dir, script)
        validate_user_path(path, current_user)
        with open(path, 'r') as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            matched = False
            for pat in patterns:
                if re.search(pat, line):
                    matched = True
                    break
            if not matched:
                new_lines.append(line)
        if len(new_lines) != len(lines):
            with open(path, 'w') as f:
                f.writelines(new_lines)
            os.chmod(path, os.stat(path).st_mode | 0o111)
            modified += 1
    db.add_audit_log(current_user["username"], "remove_gpu_from_scripts", f"{modified} scripts modified")
    return {"success": True, "modified": modified}
