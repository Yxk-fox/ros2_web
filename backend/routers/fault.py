#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""故障注入 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/logger/get_current_user 等）

router = APIRouter()

# ---------- 故障注入 ----------
FAULT_HISTORY_FILE = os.path.expanduser("~/.ros2_docker_manager_fault_history.json")

@router.post("/api/fault/inject")
async def inject_fault(data: Dict[str, Any], current_user: dict = Depends(require_permission('advanced-fault'))):
    """注入故障（网络延迟/节点杀死/CPU压力等）"""
    container_id = data.get("container_id", "")
    fault_type = data.get("fault_type", "")
    params = data.get("params", {})
    if not container_id:
        raise HTTPException(400, "请先选中容器")
    if not fault_type:
        raise HTTPException(400, "缺少故障类型")
    results = {"success": True, "faults": []}
    if fault_type == "topic_stop":
        topic = params.get("topic", "")
        if not topic:
            return {"success": False, "error": "缺少话题名"}
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'source /home/boonray/install/setup.bash && ros2 topic pub {topic} --once std_msgs/msg/String \"data: FAULT_STOP\"'")
        results["faults"].append({"type": "topic_stop", "topic": topic, "ok": rc == 0, "output": out or err})
    elif fault_type == "topic_delay":
        topic = params.get("topic", "")
        delay_ms = params.get("delay_ms", 1000)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc del dev eth0 root 2>/dev/null; tc qdisc add dev eth0 root netem delay {delay_ms}ms'")
        results["faults"].append({"type": "topic_delay", "delay_ms": delay_ms, "ok": rc == 0, "output": out or err})
    elif fault_type == "node_kill":
        node = params.get("node", "")
        if not node:
            return {"success": False, "error": "缺少节点名"}
        # ROS2 没有 ros2 node kill 命令，通过进程名杀掉节点
        # 节点名格式如 /ipp_controller，去掉开头的/作为进程名关键词
        node_name = node.lstrip('/')
        # 先查找进程PID，然后kill
        kill_cmd = f"bash -c 'pids=$(pgrep -f \"{node_name}\"); if [ -n \"$pids\" ]; then kill $pids && echo \"Killed nodes: $pids\"; else echo \"Node process not found\"; fi'"
        rc, out, err = DockerManager.exec_command(container_id, kill_cmd, timeout=15)
        results["faults"].append({"type": "node_kill", "node": node, "ok": rc == 0, "output": out or err})
    elif fault_type == "service_timeout":
        service = params.get("service", "")
        timeout_ms = params.get("timeout_ms", 5000)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc del dev eth0 root 2>/dev/null; tc qdisc add dev eth0 root netem delay {timeout_ms}ms'")
        results["faults"].append({"type": "service_timeout", "service": service, "timeout_ms": timeout_ms, "ok": rc == 0, "output": out or err})
    elif fault_type == "cpu_stress":
        cpu_count = params.get("cpu_count", 1)
        duration = params.get("duration", 30)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'stress --cpu {cpu_count} --timeout {duration}s &'", detach=True)
        results["faults"].append({"type": "cpu_stress", "cpu_count": cpu_count, "duration": duration, "ok": rc == 0})
    elif fault_type == "memory_leak":
        mem_mb = params.get("mem_mb", 256)
        duration = params.get("duration", 30)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'stress --vm 1 --vm-bytes {mem_mb}M --timeout {duration}s &'", detach=True)
        results["faults"].append({"type": "memory_leak", "mem_mb": mem_mb, "duration": duration, "ok": rc == 0})
    elif fault_type == "network_loss":
        loss_pct = params.get("loss_pct", 10)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'tc qdisc del dev eth0 root 2>/dev/null; tc qdisc add dev eth0 root netem loss {loss_pct}%'")
        results["faults"].append({"type": "network_loss", "loss_pct": loss_pct, "ok": rc == 0, "output": out or err})
    elif fault_type == "gps_drift":
        topic = params.get("topic", "/gps/fix")
        drift_m = params.get("drift_m", 5.0)
        rc, out, err = DockerManager.exec_command(container_id, f"bash -c 'source /home/boonray/install/setup.bash && ros2 topic pub {topic} --once sensor_msgs/msg/NavSatFix \"{{latitude: 31.0, longitude: 121.0, altitude: {drift_m}}}\"'")
        results["faults"].append({"type": "gps_drift", "topic": topic, "drift_m": drift_m, "ok": rc == 0, "output": out or err})
    else:
        return {"success": False, "error": f"未知故障类型: {fault_type}"}
    history = []
    if os.path.exists(FAULT_HISTORY_FILE):
        try:
            with open(FAULT_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except:
            pass
    history.append({
        "timestamp": datetime.now().isoformat(),
        "container_id": container_id,
        "fault_type": fault_type,
        "params": params,
        "results": results["faults"]
    })
    with open(FAULT_HISTORY_FILE, 'w') as f:
        json.dump(history[-100:], f, indent=2, ensure_ascii=False)
    db.add_audit_log(current_user["username"], "inject_fault", f"{fault_type} -> {container_id}")
    await broadcast_log("warning", f"故障注入: {fault_type} -> 容器 {container_id}")
    return results

@router.post("/api/fault/clear")
async def clear_fault(data: Dict[str, str], current_user: dict = Depends(require_permission('advanced-fault'))):
    """清除容器上的所有故障注入"""
    container_id = data.get("container_id", "")
    if not container_id:
        raise HTTPException(400, "缺少容器ID")
    results = []
    rc1, out1, err1 = DockerManager.exec_command(container_id, "bash -c 'tc qdisc del dev eth0 root 2>&1'")
    # tc del 在无规则时返回非零但属于正常情况，检查是否真正清除
    net_ok = rc1 == 0 or "No such file" in (err1 or "") or "not exist" in (err1 or "")
    results.append({"action": "clear_network", "ok": net_ok, "output": "已清除网络故障" if net_ok else f"清除失败: {err1 or out1}"})
    rc2, out2, err2 = DockerManager.exec_command(container_id, "bash -c 'pkill -9 stress 2>&1'")
    stress_ok = rc2 == 0 or "no process" in (err2 or "").lower() or "not found" in (err2 or "").lower()
    results.append({"action": "clear_stress", "ok": stress_ok, "output": "已停止压力测试" if stress_ok else f"清除失败: {err2 or out2}"})
    db.add_audit_log(current_user["username"], "clear_fault", container_id)
    await broadcast_log("info", f"已清除容器 {container_id} 的所有故障")
    return {"success": True, "results": results}

@router.get("/api/fault/list")
async def fault_list(container_id: str = None, current_user: dict = Depends(require_permission('advanced-fault'))):
    """列出容器上的活跃故障"""
    active_faults = []
    if container_id:
        rc, out, _ = DockerManager.exec_command(container_id, "bash -c 'tc qdisc show dev eth0 2>/dev/null'")
        if "netem" in (out or ""):
            active_faults.append({"type": "network_fault", "detail": out.strip()})
        rc2, out2, _ = DockerManager.exec_command(container_id, "bash -c 'pgrep -a stress 2>/dev/null'")
        if out2 and out2.strip():
            active_faults.append({"type": "stress", "detail": out2.strip()})
    return {"success": True, "active_faults": active_faults}

@router.get("/api/fault/history")
async def fault_history(current_user: dict = Depends(require_permission('advanced-fault'))):
    """获取故障注入历史记录"""
    try:
        if os.path.exists(FAULT_HISTORY_FILE):
            with open(FAULT_HISTORY_FILE, 'r') as f:
                history = json.load(f)
            return {"success": True, "history": history}
        return {"success": True, "history": []}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/fault/history/clear")
async def clear_fault_history(current_user: dict = Depends(require_permission('advanced-fault'))):
    """清除故障注入历史记录"""
    try:
        if os.path.exists(FAULT_HISTORY_FILE):
            os.remove(FAULT_HISTORY_FILE)
        db.add_audit_log(current_user["username"], "clear_fault_history", "已清除故障历史")
        await broadcast_log("info", "故障注入历史已清除")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
