#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS2 功能 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）

router = APIRouter()

# ---------- ROS2 命令 ----------
@router.post("/api/ros2/simulation/start")
async def start_simulation(data: Dict[str, str], current_user: dict = Depends(require_permission('simulation'))):
    """在容器中启动Mock Truck仿真"""
    container_id = data.get("container_id")
    cmd = data.get("command")
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    if not cmd:
        raise HTTPException(400, "缺少命令")
    # 使用 shlex.split 正确处理带引号的命令参数，避免破坏包含空格/引号的参数
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        raise HTTPException(400, f"命令格式错误: {e}")
    rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=60)
    db.add_audit_log(current_user["username"], "start_simulation", f"容器 {container_id}: {cmd}")
    if rc == 0:
        await broadcast_log("info", f"Mock Truck 仿真启动成功 (容器 {container_id}): {cmd}")
    else:
        await broadcast_log("error", f"Mock Truck 仿真启动失败 (容器 {container_id}): {err}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/ros2/cmd_vel")
async def publish_cmd_vel(data: Dict[str, Any], current_user: dict = Depends(require_permission('simulation'))):
    """发布速度控制指令"""
    topic = data.get("topic", "/cmd_vel")
    linear = data.get("linear_x", 0.0)
    angular = data.get("angular_z", 0.0)
    msg = f"linear: {{x: {linear}, y: 0.0, z: 0.0}}, angular: {{x: 0.0, y: 0.0, z: {angular}}}"
    rc, out, err = run_ros2_cmd(["ros2", "topic", "pub", "--once", topic, "geometry_msgs/msg/Twist", msg], timeout=5)
    db.add_audit_log(current_user["username"], "cmd_vel", f"{topic} lx={linear} az={angular}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

@router.post("/api/ros2/topic/pub")
async def topic_pub(data: Dict[str, Any], current_user: dict = Depends(require_permission('topics'))):
    """在容器中发布话题消息"""
    container_id = data.get("container_id")
    topic = data.get("topic")
    msg_type = data.get("msg_type", "std_msgs/msg/String")
    msg_data = data.get("data", "{}")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not topic:
        raise HTTPException(400, "缺少话题名")
    if not topic.startswith('/'):
        topic = '/' + topic
    cmd_parts = ["ros2", "topic", "pub", "--once", topic, msg_type, msg_data]
    rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=10)
    db.add_audit_log(current_user["username"], "topic_pub", f"{topic} -> {msg_data}")
    if rc == 0:
        return {"success": True, "stdout": out or "✅ 发布成功", "stderr": err}
    else:
        return {"success": False, "error": err or "发布失败", "stdout": out}

@router.post("/api/ros2/topic/kill")
async def topic_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('topics'))):
    """杀死发布指定话题的节点"""
    container_id = data.get("container_id")
    topic = data.get("topic")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not topic:
        raise HTTPException(400, "缺少话题名")
    if not topic.startswith('/'):
        topic = '/' + topic
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "info", topic], timeout=10)
    if rc != 0:
        return {"success": False, "error": f"无法获取话题 {topic} 的信息: {err}"}
    nodes = re.findall(r"Publisher: (/\S+)", out)
    if not nodes:
        return {"success": False, "error": f"未找到发布话题 {topic} 的节点", "info": out}
    results = []
    for node in nodes:
        rc2, out2, err2 = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
        results.append({"node": node, "success": rc2 == 0, "output": out2 if rc2 == 0 else err2})
    success_count = sum(1 for r in results if r["success"])
    db.add_audit_log(current_user["username"], "topic_kill", f"{topic} killed {success_count} nodes")
    return {"success": True, "results": results, "message": f"已尝试杀死 {len(results)} 个发布者节点，成功 {success_count} 个"}

@router.post("/api/ros2/node/kill")
async def node_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('nodes'))):
    """杀死指定节点"""
    container_id = data.get("container_id")
    node = data.get("node")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not node:
        raise HTTPException(400, "缺少节点名")
    if not node.startswith('/'):
        node = '/' + node
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
    db.add_audit_log(current_user["username"], "node_kill", node)
    if rc == 0:
        return {"success": True, "stdout": out or f"✅ 节点 {node} 已停止", "stderr": err}
    else:
        return {"success": False, "error": err or f"无法停止节点 {node}"}

@router.post("/api/ros2/service/kill")
async def service_kill(data: Dict[str, Any], current_user: dict = Depends(require_permission('services'))):
    """杀死提供指定服务的节点"""
    container_id = data.get("container_id")
    service = data.get("service")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    if not service:
        raise HTTPException(400, "缺少服务名")
    if not service.startswith('/'):
        service = '/' + service
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "info", service], timeout=10)
    if rc != 0:
        return {"success": False, "error": f"无法获取服务 {service} 的信息: {err}"}
    nodes = re.findall(r"Node: (/\S+)", out)
    if not nodes:
        return {"success": False, "error": f"未找到提供服务 {service} 的节点", "info": out}
    results = []
    for node in nodes:
        rc2, out2, err2 = run_ros2_cmd_in_container(container_id, ["ros2", "node", "kill", node], timeout=10)
        results.append({"node": node, "success": rc2 == 0, "output": out2 if rc2 == 0 else err2})
    success_count = sum(1 for r in results if r["success"])
    db.add_audit_log(current_user["username"], "service_kill", f"{service} killed {success_count} nodes")
    return {"success": True, "results": results, "message": f"已尝试杀死 {len(results)} 个提供服务的节点，成功 {success_count} 个"}

# ---------- ROS2 话题 ----------
@router.get("/api/ros2/topics")
async def list_topics(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 话题"""
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    # 权限检查：topics 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "topics" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问话题列表")
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "list"])
    if rc != 0:
        return {"success": False, "error": err}
    topics = [t for t in out.splitlines() if t]
    db.add_audit_log(current_user["username"], "list_topics", f"容器 {container_id}")
    return {"success": True, "topics": topics}

@router.get("/api/ros2/topic/{name:path}/info")
async def topic_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('topics'))):
    """获取话题详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "topic", "info", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "topic", "info", name], timeout=10)
    if rc == 0:
        return {"success": True, "info": out if out else "✅ 话题存在（无额外信息）"}
    else:
        return {"success": False, "error": err or f"无法获取话题 {name} 的信息"}

@router.get("/api/ros2/topic/{name:path}/echo")
async def topic_echo(name: str, once: bool = True, container_id: str = None, current_user: dict = Depends(require_permission('topics'))):
    """获取话题最新一条消息"""
    if container_id:
        cmd_parts = ["ros2", "topic", "echo", name]
        if once:
            cmd_parts.append("--once")
        rc, out, err = run_ros2_cmd_in_container(container_id, cmd_parts, timeout=10)
    else:
        cmd_parts = ["ros2", "topic", "echo", name]
        if once:
            cmd_parts.append("--once")
        rc, out, err = run_ros2_cmd(cmd_parts, timeout=10)
    db.add_audit_log(current_user["username"], "topic_echo", name)
    if rc == 0:
        return {"success": True, "data": out if out else "✅ 执行成功（无数据输出）"}
    else:
        return {"success": False, "error": err or "执行失败"}

# ---------- ROS2 节点 ----------
@router.get("/api/ros2/nodes")
async def list_nodes(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 节点"""
    if not container_id:
        raise HTTPException(400, "请先选中一个容器")
    # 权限检查：nodes 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "nodes" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问节点列表")
    rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "list"])
    if rc != 0:
        return {"success": False, "error": err or "容器内执行失败"}
    nodes = [n for n in out.splitlines() if n and n not in ("/rosout", "/parameter_events")]
    db.add_audit_log(current_user["username"], "list_nodes", f"容器 {container_id}")
    return {"success": True, "nodes": nodes}

@router.get("/api/ros2/node/{name:path}/info")
async def node_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('nodes'))):
    """获取节点详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "node", "info", name], timeout=15)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "node", "info", name], timeout=15)
    db.add_audit_log(current_user["username"], "node_info", name)
    if rc == 0:
        return {"success": True, "info": out if out else "✅ 节点存在（无额外信息）"}
    else:
        return {"success": False, "error": err or f"无法找到节点 {name}"}

# ---------- ROS2 服务 ----------
@router.get("/api/ros2/services")
async def list_services(container_id: str = None, current_user: dict = Depends(get_current_user)):
    """列出容器中的 ROS2 服务"""
    # 权限检查：services 权限或 advanced-fault 权限都可访问
    if current_user["role"] != "admin":
        permissions = db.get_user_permissions(current_user["username"])
        if "services" not in permissions and "advanced-fault" not in permissions:
            raise HTTPException(status_code=403, detail="无权限访问服务列表")
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "list"], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "list"], timeout=10)
    if rc != 0:
        raise HTTPException(500, err)
    services = [s for s in out.splitlines() if s]
    db.add_audit_log(current_user["username"], "list_services", f"容器 {container_id}")
    return {"success": True, "services": services}

@router.get("/api/ros2/service/{name:path}/type")
async def service_type(name: str, container_id: str = None, current_user: dict = Depends(require_permission('services'))):
    """获取服务类型"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "type", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "type", name], timeout=10)
    return {"success": rc == 0, "type": out if rc == 0 else err}

@router.post("/api/ros2/service/{name:path}/call")
async def call_service(name: str, data: Dict[str, Any], container_id: str = None, current_user: dict = Depends(require_permission('services'))):
    """调用 ROS2 服务"""
    srv_type = data.get("srv_type")
    req = data.get("data", "{}")
    if not srv_type:
        raise HTTPException(400, "缺少服务类型")
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "service", "call", name, srv_type, req], timeout=15)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "service", "call", name, srv_type, req], timeout=15)
    db.add_audit_log(current_user["username"], "call_service", f"{name} -> {srv_type}")
    return {"success": rc == 0, "stdout": out, "stderr": err}

# ---------- ROS2 Action ----------
@router.get("/api/ros2/actions")
async def list_actions(container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """列出容器中的 ROS2 Action"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "list"], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "action", "list"], timeout=10)
    if rc != 0:
        raise HTTPException(500, err)
    actions = [a for a in out.splitlines() if a]
    db.add_audit_log(current_user["username"], "list_actions", f"容器 {container_id}")
    return {"success": True, "actions": actions}

@router.get("/api/ros2/action/{name}/info")
async def action_info(name: str, container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """获取 Action 详细信息"""
    if container_id:
        rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "info", name], timeout=10)
    else:
        rc, out, err = run_ros2_cmd(["ros2", "action", "info", name], timeout=10)
    db.add_audit_log(current_user["username"], "action_info", name)
    return {"success": rc == 0, "info": out if rc == 0 else err}

@router.post("/api/ros2/action/{name}/send_goal")
async def send_action_goal(name: str, data: Dict[str, Any], container_id: str = None, current_user: dict = Depends(require_permission('docker'))):
    """发送 Action 目标"""
    action_type = data.get("action_type")
    goal = data.get("data", "{}")
    if container_id:
        if action_type:
            rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "send_goal", name, action_type, goal], timeout=15)
        else:
            rc, out, err = run_ros2_cmd_in_container(container_id, ["ros2", "action", "send_goal", name, goal], timeout=15)
    else:
        if action_type:
            rc, out, err = run_ros2_cmd(["ros2", "action", "send_goal", name, action_type, goal], timeout=15)
        else:
            rc, out, err = run_ros2_cmd(["ros2", "action", "send_goal", name, goal], timeout=15)
    db.add_audit_log(current_user["username"], "send_action_goal", f"{name} -> {goal}")
    return {"success": rc == 0, "stdout": out, "stderr": err}
