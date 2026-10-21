#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工单系统 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/logger/get_current_user 等）

router = APIRouter()

# ---------- 工单系统模块 API ----------

# 工单附件存储目录
TICKET_ATTACHMENTS_DIR = os.path.expanduser("~/ros2_web/data/ticket_attachments")
ALLOWED_ATTACHMENT_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
                           ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                           ".txt", ".log", ".csv", ".md", ".json", ".yaml", ".yml",
                           ".zip", ".tar", ".gz", ".bz2", ".7z"}
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50MB

# 工单状态机：状态 -> 允许的下一状态
TICKET_STATUS_TRANSITIONS = {
    "pending":    ["processing", "resolved", "closed"],
    "processing": ["resolved", "closed", "pending"],
    "resolved":   ["closed", "processing"],
    "closed":     ["processing"],  # 允许重新打开
}

# 工单分类列表
TICKET_CATEGORIES = [
    "车辆控制", "容器异常", "仿真启动", "脚本生成", "证书同步",
    "车辆配置", "环境配置", "权限问题", "其他"
]

def _ticket_user_filter(current_user: dict) -> Optional[Dict[str, Any]]:
    """普通用户只看自己的工单；管理员看全部"""
    if current_user.get("role") == "admin":
        return None
    return {"customer_id": current_user.get("id")}

async def _broadcast_ticket_event(event: str, ticket_id: str, payload: dict = None):
    """向所有 WebSocket 客户端广播工单事件"""
    msg = json.dumps({
        "type": "ticket_event",
        "event": event,                # create/update/reply/delete/status_change
        "ticket_id": ticket_id,
        "data": payload or {},
        "timestamp": time.time()
    })
    for client in ws_clients[:]:
        try:
            await client.send_text(msg)
        except Exception:
            if client in ws_clients:
                ws_clients.remove(client)


# ---------- 工单元信息接口 ----------

@router.get("/api/tickets/meta")
async def get_tickets_meta(current_user: dict = Depends(get_current_user)):
    """获取工单元信息（分类、状态、优先级、权限）"""
    return {
        "success": True,
        "categories": TICKET_CATEGORIES,
        "statuses": ["pending", "processing", "resolved", "closed"],
        "priorities": [1, 2, 3, 4, 5],
        "transitions": TICKET_STATUS_TRANSITIONS,
        "is_admin": current_user.get("role") == "admin",
        "current_user_id": current_user.get("id"),
        "current_username": current_user.get("username") or current_user.get("email", "")
    }


# ---------- 工单 CRUD ----------

@router.post("/api/tickets")
async def create_ticket_api(req: Dict[str, Any] = None, current_user: dict = Depends(get_current_user)):
    """创建工单（普通用户 + 管理员均可）"""
    req = req or {}
    title = (req.get("title") or "").strip()
    content = (req.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(400, "标题和内容不能为空")
    if len(title) > 200:
        raise HTTPException(400, "标题不能超过 200 字符")
    category = (req.get("category") or "其他").strip()
    priority = int(req.get("priority", 3))
    if priority < 1 or priority > 5:
        priority = 3
    attachments = req.get("attachments") or []
    customer_name = current_user.get("username") or current_user.get("email", "")
    # v3.6：默认处理人 = 登录用户（创建人）
    assignee_id = req.get("assignee_id") or current_user.get("id")
    assignee_name = req.get("assignee_name") or current_user.get("username") or customer_name

    ticket = db.create_ticket(
        customer_id=current_user.get("id"),
        customer_name=customer_name,
        title=title,
        content=content,
        category=category,
        priority=priority,
        attachments=attachments,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
    )
    if not ticket:
        raise HTTPException(500, "创建工单失败")

    await _broadcast_ticket_event("create", ticket.get("id"), {
        "ticket_no": ticket.get("ticket_no"),
        "title": title,
        "customer_name": customer_name,
        "status": "pending",
    })
    logger.info(f"用户 {customer_name} 创建工单 {ticket.get('ticket_no')}")
    return {"success": True, "ticket": ticket}


@router.get("/api/tickets")
async def list_tickets_api(
    status: str = None, category: str = None, priority: int = None,
    keyword: str = None, start_date: str = None, end_date: str = None,
    assignee_id: str = None, page: int = 1, limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """查询工单列表（普通用户仅看自己；管理员看全部）"""
    if page < 1: page = 1
    if limit < 1 or limit > 100: limit = 20
    filters = {
        "status": status, "category": category, "priority": priority,
        "keyword": keyword, "start_date": start_date, "end_date": end_date,
        "assignee_id": assignee_id,
    }
    user_filter = _ticket_user_filter(current_user)
    result = db.list_tickets(filters=filters, user_filter=user_filter, page=page, limit=limit)
    return {
        "success": True,
        "items": result["items"],
        "total": result["total"],
        "page": result["page"],
        "limit": result["limit"],
        "is_admin": current_user.get("role") == "admin",
    }


@router.get("/api/tickets/{ticket_id}")
async def get_ticket_api(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """获取工单详情 + 回复列表"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    # 权限校验：普通用户只能查看自己的工单
    if current_user.get("role") != "admin" and ticket.get("customer_id") != current_user.get("id"):
        raise HTTPException(403, "无权访问该工单")
    replies = db.list_replies(ticket_id)
    return {
        "success": True,
        "ticket": ticket,
        "replies": replies,
        "is_admin": current_user.get("role") == "admin",
        "current_user_id": current_user.get("id"),
    }


@router.put("/api/tickets/{ticket_id}")
@router.patch("/api/tickets/{ticket_id}")
async def update_ticket_api(ticket_id: str, req: Dict[str, Any] = None,
                            current_user: dict = Depends(get_current_user)):
    """更新工单（标题/内容/分类/优先级/状态/处理人）

    同时支持 PUT 和 PATCH 方法，便于不同前端客户端调用。
    """
    req = req or {}
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    is_admin = current_user.get("role") == "admin"
    is_owner = ticket.get("customer_id") == current_user.get("id")
    if not is_admin and not is_owner:
        raise HTTPException(403, "无权修改该工单")

    updates: Dict[str, Any] = {}
    # 普通字段：标题/内容/分类/优先级，仅创建者或管理员可改
    for field in ["title", "content", "category"]:
        if field in req:
            if not is_admin and not is_owner:
                raise HTTPException(403, f"无权修改 {field}")
            val = (req.get(field) or "").strip() if field != "category" else (req.get(field) or "").strip()
            if field == "title" and not val:
                raise HTTPException(400, "标题不能为空")
            if field == "content" and not val:
                raise HTTPException(400, "内容不能为空")
            updates[field] = val
    if "priority" in req:
        if not is_admin and not is_owner:
            raise HTTPException(403, "无权修改优先级")
        try:
            p = int(req["priority"])
            if 1 <= p <= 5:
                updates["priority"] = p
        except Exception:
            pass

    # 状态机：仅管理员可改状态
    if "status" in req:
        if not is_admin:
            raise HTTPException(403, "仅管理员可修改工单状态")
        new_status = req["status"]
        if new_status not in TICKET_STATUS_TRANSITIONS:
            raise HTTPException(400, f"无效的状态: {new_status}")
        old_status = ticket.get("status")
        if new_status != old_status:
            allowed = TICKET_STATUS_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise HTTPException(400, f"状态流转不允许: {old_status} -> {new_status}")
            updates["status"] = new_status
            if new_status == "resolved":
                updates["resolved_at"] = datetime.utcnow().isoformat()
            elif new_status == "closed":
                updates["closed_at"] = datetime.utcnow().isoformat()

    # 处理人：仅管理员可指派
    if "assignee_id" in req:
        if not is_admin:
            raise HTTPException(403, "仅管理员可指派工单")
        assignee_id = req["assignee_id"]
        assignee_name = req.get("assignee_name", "")
        updates["assignee_id"] = assignee_id
        updates["assignee_name"] = assignee_name

    if not updates:
        return {"success": True, "ticket": ticket, "message": "无更新字段"}

    ok = db.update_ticket(ticket_id, updates)
    if not ok:
        raise HTTPException(500, "更新失败")

    updated = db.get_ticket(ticket_id)
    await _broadcast_ticket_event("update", ticket_id, {
        "updates": updates,
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
    })
    # 状态变更单独广播事件
    if "status" in updates:
        await _broadcast_ticket_event("status_change", ticket_id, {
            "old_status": ticket.get("status"),
            "new_status": updates["status"],
            "ticket_no": ticket.get("ticket_no"),
            "title": ticket.get("title"),
        })
    return {"success": True, "ticket": updated}


@router.delete("/api/tickets/{ticket_id}")
async def delete_ticket_api(ticket_id: str, current_user: dict = Depends(require_admin)):
    """软删除工单（仅管理员）"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    db.soft_delete_ticket(ticket_id)
    await _broadcast_ticket_event("delete", ticket_id, {
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
    })
    return {"success": True, "message": "工单已删除"}


# ---------- 工单回复 ----------

@router.post("/api/tickets/{ticket_id}/replies")
async def add_reply_api(ticket_id: str, req: Dict[str, Any] = None,
                        current_user: dict = Depends(get_current_user)):
    """添加工单回复"""
    req = req or {}
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    # 权限校验：普通用户只能回复自己的工单；管理员可回复任意
    is_admin = current_user.get("role") == "admin"
    is_owner = ticket.get("customer_id") == current_user.get("id")
    if not is_admin and not is_owner:
        raise HTTPException(403, "无权回复该工单")

    content = (req.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "回复内容不能为空")
    attachments = req.get("attachments") or []
    reply_user_name = current_user.get("username") or current_user.get("email", "")
    reply_user_type = "admin" if is_admin else "customer"

    reply = db.add_reply(
        ticket_id=ticket_id,
        reply_user_id=current_user.get("id"),
        reply_user_name=reply_user_name,
        reply_user_type=reply_user_type,
        content=content,
        attachments=attachments,
    )
    if not reply:
        raise HTTPException(500, "回复失败")

    await _broadcast_ticket_event("reply", ticket_id, {
        "ticket_no": ticket.get("ticket_no"),
        "title": ticket.get("title"),
        "reply_user_name": reply_user_name,
        "reply_user_type": reply_user_type,
        "content_preview": content[:100],
    })
    return {"success": True, "reply": reply}


@router.get("/api/tickets/{ticket_id}/replies")
async def list_replies_api(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """获取工单的所有回复"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if current_user.get("role") != "admin" and ticket.get("customer_id") != current_user.get("id"):
        raise HTTPException(403, "无权访问该工单")
    replies = db.list_replies(ticket_id)
    return {"success": True, "replies": replies}


# ---------- 工单附件上传 ----------

@router.post("/api/tickets/attachments")
async def upload_attachment_api(file: UploadFile = File(...),
                                current_user: dict = Depends(get_current_user)):
    """上传附件到本地存储，返回附件信息"""
    if not file.filename:
        raise HTTPException(400, "未提供文件")
    filename = os.path.basename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    # 读取并校验大小
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(400, f"文件大小超过限制 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB")

    # 按日期/用户分目录存储
    today = datetime.utcnow().strftime("%Y%m%d")
    user_dir = os.path.join(TICKET_ATTACHMENTS_DIR, today, current_user.get("id", "anon"))
    os.makedirs(user_dir, exist_ok=True)
    # 避免文件名冲突
    unique_name = f"{int(time.time() * 1000)}_{filename}"
    file_path = os.path.join(user_dir, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)

    # 返回附件元数据（前端存到工单 attachments 字段）
    attachment = {
        "filename": filename,
        "saved_name": unique_name,
        "size": len(content),
        "ext": ext,
        "path": file_path,
        "url": f"/api/tickets/attachments/{today}/{current_user.get('id', 'anon')}/{unique_name}",
        "uploaded_at": datetime.utcnow().isoformat(),
        "uploaded_by": current_user.get("username") or current_user.get("email", ""),
    }
    return {"success": True, "attachment": attachment}


@router.get("/api/tickets/attachments/{date_dir}/{user_id}/{filename}")
async def download_attachment_api(date_dir: str, user_id: str, filename: str,
                                  current_user: dict = Depends(get_current_user)):
    """下载工单附件"""
    # 安全：禁止路径穿越
    if "/" in date_dir or "/" in user_id or "/" in filename:
        raise HTTPException(400, "非法请求")
    if ".." in date_dir or ".." in user_id or ".." in filename:
        raise HTTPException(400, "非法请求")
    file_path = os.path.join(TICKET_ATTACHMENTS_DIR, date_dir, user_id, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "附件不存在")
    return FileResponse(file_path, filename=filename)


# ============================================================
# 工单系统模块 END
# ============================================================
