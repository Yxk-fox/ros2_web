#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Docker 镜像 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）

router = APIRouter()

# ---------- Docker 镜像 ----------
@router.get("/api/docker/images")
def list_images(current_user: dict = Depends(require_permission('docker'))):
    """列出 Docker 镜像

    ★ 性能优化：同步 def —— docker 子进程调用放入线程池
    """
    cmd = DockerManager._docker("images", "--format", "json")
    rc, out, err = DockerManager.run_cmd(cmd)
    if rc != 0:
        return {"success": False, "error": err}
    images = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            img = json.loads(line)
            repo = img.get("Repository", "")
            tag = img.get("Tag", "")
            if repo == "<none>" and tag == "<none>":
                continue
            tags = [f"{repo}:{tag}"]
            img_id = img.get("ID", "")
            size_bytes = parse_size(img.get("Size", "0B"))
            images.append({"tags": tags, "id": img_id, "size": size_bytes})
        except json.JSONDecodeError:
            continue
    return {"success": True, "images": images}

@router.post("/api/docker/images/load")
async def load_image(
    file: UploadFile = File(None),
    path: str = Body(None),
    current_user: dict = Depends(require_permission('images'))
):
    """加载 Docker 镜像，支持文件上传或本地路径"""
    # 优先处理文件上传
    if file is not None:
        suffix = os.path.splitext(file.filename or "")[1].lower()
        if suffix not in ('.tar', '.tgz'):
            raise HTTPException(400, "仅支持 .tar 或 .tgz 文件")
        tmp_path = os.path.join(tempfile.gettempdir(), f"docker_load_{int(time.time())}{suffix}")
        try:
            # 大文件复制与 docker load 均为耗时同步操作，
            # 放入线程池执行，避免阻塞事件循环导致整个后端无响应
            with open(tmp_path, 'wb') as f:
                await asyncio.to_thread(shutil.copyfileobj, file.file, f)
            rc, out, err = await asyncio.to_thread(DockerManager.load_image, tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        db.add_audit_log(current_user["username"], "load_image", file.filename)
        return {"success": rc == 0, "message": out or err}

    # 兼容本地路径方式
    if not path or not os.path.isfile(path):
        raise HTTPException(400, "文件不存在")
    # docker load 可能耗时数分钟，放入线程池避免阻塞事件循环
    rc, out, err = await asyncio.to_thread(DockerManager.load_image, path)
    db.add_audit_log(current_user["username"], "load_image", path)
    return {"success": rc == 0, "message": out or err}

@router.delete("/api/docker/images/{name}")
async def delete_image(name: str, current_user: dict = Depends(require_permission('images'))):
    """删除 Docker 镜像"""
    rc, out, err = DockerManager.remove_image(name)
    db.add_audit_log(current_user["username"], "delete_image", name)
    return {"success": rc == 0, "message": out or err}
