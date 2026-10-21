#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仿真车管理 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）

router = APIRouter()

# ---------- 仿真车管理 ----------
def get_current_cloud_ip():
    """获取当前配置的云平台IP（优先从配置文件获取）"""
    current_ip = CONFIG["cloud_env"]["current_ip"]
    if current_ip:
        return current_ip
    
    config_dir = os.path.expanduser("~/robotruck_ros2/install/simulation_launches/share/simulation_launches/config")
    if not os.path.isdir(config_dir):
        config_dir = os.path.expanduser("~/robotruck_ros2/Docker/bk/simulation_launches/config")
    if not os.path.isdir(config_dir):
        return None
    
    cloud_file = os.path.join(config_dir, "cloud.yaml")
    if os.path.isfile(cloud_file):
        try:
            with open(cloud_file, 'r', encoding='utf-8') as f:
                content = f.read()
                match = re.search(r'udp_server_url:\s*(\d+\.\d+\.\d+\.\d+)', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
    return None

def get_cloud_ip_from_host_mount(container_name):
    """从容器在宿主机的挂载点读取实际云IP配置"""
    try:
        mount_cmd = DOCKER_PREFIX.split() + [
            "docker", "inspect", container_name,
            "--format", "{{range .Mounts}}{{if eq .Destination \"/home/boonray/install\"}}{{.Source}}{{end}}{{end}}"
        ]
        rc, mount_src, _ = DockerManager.run_cmd(mount_cmd, timeout=5)
        if rc == 0 and mount_src.strip():
            cloud_yaml = os.path.join(
                mount_src.strip(),
                "simulation_launches/share/simulation_launches/config/cloud.yaml"
            )
            if os.path.isfile(cloud_yaml):
                with open(cloud_yaml, 'r', encoding='utf-8') as f:
                    content = f.read()
                m = re.search(r'udp_server_url:\s*([\d\.]+)', content)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def get_cloud_ip_from_container(container_name):
    """从容器提取云平台IP
    优先顺序：
    1. 运行中容器：从宿主机挂载点读取实际cloud.yaml配置（最准确，无需docker exec）
    2. 运行中容器（回退）：docker exec进入容器读取配置
    3. 标签读取：从 --label ros2.cloud_ip 读取启动时记录的IP
    4. 回退到当前全局配置的IP
    """
    label_ip = None
    try:
        cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "--format", "{{index .Config.Labels \"ros2.cloud_ip\"}}", container_name]
        rc, out, _ = DockerManager.run_cmd(cmd)
        if rc == 0 and out.strip() and out.strip() != "<no value>":
            label_ip = out.strip()
    except Exception:
        pass

    try:
        state_cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "-f", "{{.State.Running}}", container_name]
        rc_state, state_out, _ = DockerManager.run_cmd(state_cmd, timeout=5)
        is_running = rc_state == 0 and "true" in state_out.lower()

        if is_running:
            host_ip = get_cloud_ip_from_host_mount(container_name)
            if host_ip and re.match(r'^\d+\.\d+\.\d+\.\d+$', host_ip):
                return host_ip

            grep_cmd = ["bash", "-c",
                f"docker exec {shlex.quote(container_name)} bash -c "
                f"\"grep -oP 'udp_server_url:\\s*\\K[\\d\\.]+' "
                f"/home/boonray/install/simulation_launches/share/simulation_launches/config/cloud.yaml 2>/dev/null || true\""]
            rc_ip, ip_out, _ = DockerManager.run_cmd(grep_cmd, timeout=5)
            if rc_ip == 0 and ip_out.strip():
                actual_ip = ip_out.strip().split('\n')[0].strip()
                if re.match(r'^\d+\.\d+\.\d+\.\d+$', actual_ip):
                    return actual_ip
    except Exception:
        pass

    if label_ip:
        return label_ip

    return get_current_cloud_ip()

@router.get("/api/docker/containers")
def list_containers(all: bool = True, filter_name: str = None, filter_image: str = None, current_user: dict = Depends(require_permission('docker'))):
    """列出 Docker 容器（普通用户仅可见自己启动的容器，管理员可看全部）

    ★★★ 性能优化：
    1. 端点改为同步 def —— FastAPI 自动放入线程池执行，内部的 docker 子进程调用
       不再阻塞 asyncio 事件循环（旧版 async def + 阻塞 subprocess 会让所有并发
       请求串行排队，页面加载 8 个请求实测总耗时 1.9s+）。
    2. 合并原先 2 次 docker ps 子进程（基本信息 + ID/云IP label）为 1 次调用。
    ★★★ Bug 修复：is_ros2 判定以容器名前缀 ros2_ 为准（镜像可能显示为未打标签的
    镜像 ID，如 88fc0f0bc583，按镜像名过滤会导致用户的 ROS2 容器全部不可见）。
    """
    try:
        if filter_image:
            import urllib.parse
            filter_image = urllib.parse.unquote(filter_image)
        if filter_name:
            import urllib.parse
            filter_name = urllib.parse.unquote(filter_name)
        # 普通用户权限隔离：只列出当前用户创建的容器
        visible_names = db.get_visible_container_names(current_user)
        containers = DockerManager.list_containers_detailed(running_only=not all, filter_name=filter_name, filter_image=filter_image)

        # 过滤可见容器
        filtered = []
        for c in containers:
            name = c["name"]
            if visible_names is not None and name not in visible_names:
                continue
            filtered.append(c)

        # 批量获取运行中容器的真实启动时间（State.StartedAt）
        # —— 用于前端“运行时长”权威展示，停止的容器不返回该字段（自动归零）
        started_at_map = {}
        running_names = [c["name"] for c in filtered if "up" in c["status"].lower()]
        if running_names:
            inspect_fmt = "{{.Name}}\t{{.State.StartedAt}}"
            cmd = DOCKER_PREFIX.split() + ["docker", "inspect", "--format", inspect_fmt] + running_names
            rc, out, _ = DockerManager.run_cmd(cmd, timeout=15)
            if rc == 0:
                for line in out.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        nm = parts[0].lstrip("/")
                        started_at_map[nm] = parts[1]

        # 批量获取容器归属（避免 N+1 查询）
        owner_map = {}
        if visible_names is None and filtered:
            try:
                names_list = [c["name"] for c in filtered]
                resp = db._client.table("containers").select("name,created_by").in_("name", names_list).execute()
                for row in resp.data:
                    owner_map[row["name"]] = row.get("created_by", "")
            except Exception:
                pass

        result = []
        for c in filtered:
            name = c["name"]
            cid = c.get("id", "")
            status_lower = c["status"].lower()
            state = "running" if "up" in status_lower else "exited"
            # 云平台连接仅对 ROS2 容器有意义：优先读取容器启动时记录的 label，
            # 缺失时（旧 ROS2 容器未设置 label）回退到当前配置 IP。
            # 非 ROS2 容器（grafana/prometheus 等）不返回 cloud_ip，避免误显示。
            image_lower = (c.get("image") or "").lower()
            is_ros2 = name.startswith("ros2_") or any(k in image_lower for k in ("ros2", "humble", "foxy"))
            cloud_ip = c.get("cloud_ip") or ""
            if not cloud_ip and is_ros2:
                cloud_ip = get_current_cloud_ip()
            owner = "self" if (visible_names is not None) else owner_map.get(name, "")
            # 运行中容器返回真实启动时间（ISO8601），停止容器不返回（前端据此归零）
            started_at = started_at_map.get(name) if state == "running" else None
            result.append({
                "id": cid,
                "name": name,
                "status": c["status"],
                "image": c["image"],
                "created": c.get("created", ""),
                "state": state,
                "cloud_ip": cloud_ip,
                "owner": owner,
                "started_at": started_at,
                "is_ros2": is_ros2
            })
        return {"success": True, "containers": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _check_container_access(container_name_or_id: str, current_user: dict):
    """校验当前用户是否有权操作容器（管理员直接通过；普通用户需为创建者）"""
    if current_user.get("role") == "admin":
        return True
    # 先按 name 查；如果传的是 ID，尝试从 DockerManager 获取 name
    owner = db.get_container_owner(container_name_or_id)
    if owner is None:
        # 尝试按容器 ID 反查 name
        rc, out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", container_name_or_id))
        if rc == 0 and out.strip():
            name = out.strip().lstrip("/")
            owner = db.get_container_owner(name)
    if owner is None:
        return True  # 未记录归属的旧容器，放行避免误拦
    return str(owner) == str(current_user.get("id"))

@router.post("/api/docker/container/{id}/start")
async def start_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """启动 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("start", id))
    db.add_audit_log(current_user["username"], "start_container", id)
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/stop")
async def stop_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """停止 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("kill", id))
    # 尝试更新容器状态
    rc_name, name_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", id))
    cname = name_out.strip().lstrip("/") if rc_name == 0 and name_out.strip() else ""
    if rc_name == 0 and name_out.strip():
        db.update_container_state(cname, "exited")
    db.add_audit_log(current_user["username"], "stop_container", id)
    # T-5.2-04：记录运行事件
    from services.run_records import record_run
    record_run("stop", current_user.get("username", ""), container_name=cname,
               success=(rc == 0), error=(err or "")[:500])
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/restart")
async def restart_container(id: str, current_user: dict = Depends(require_permission('docker'))):
    """重启 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("restart", id))
    db.add_audit_log(current_user["username"], "restart_container", id)
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/container/{id}/rviz")
async def open_rviz(id: str, current_user: dict = Depends(require_permission('docker'))):
    """在容器中启动 RVIZ2 可视化工具（参考 ros2_docker_manager.py 的 open_rviz2 实现）"""
    try:
        import time
        debug_info = []

        # 获取容器默认用户
        rc_u, user_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", "whoami"))
        container_user = user_out.strip() if rc_u == 0 and user_out.strip() else "boonray"

        # 获取容器环境变量以获取 ROS_DOMAIN_ID
        rc, env_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Config.Env}}", id))
        domain_id = "0"
        if rc == 0 and env_out:
            match = re.search(r'ROS_DOMAIN_ID=(\d+)', env_out)
            if match:
                domain_id = match.group(1)
                debug_info.append(f"ROS_DOMAIN_ID={domain_id}")

        # 确保容器内有 X 服务器运行（rviz2 需要图形环境）
        rc_x, x_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "ps aux | grep -E '[X]vfb|[X]tigervnc|[X]org' | awk '{for(i=11;i<=NF;i++) if($i ~ /^:[0-9]+$/){print $i; exit}}'"
        ))
        if rc_x == 0 and x_out.strip().startswith(":"):
            display_num = x_out.strip()
            debug_info.append(f"复用已有 X server: DISPLAY={display_num}")
        else:
            display_num = ":99"
            # 从配置中读取 VNC 分辨率，默认 1920x1080
            vnc_geometry = CONFIG.get("visualization", {}).get("methods", {}).get("vnc", {}).get("geometry", "1920x1080")
            # 解析分辨率，Xvfb 需要 宽x高x色深 格式
            xvfb_screen = f"{vnc_geometry}x24" if 'x' in vnc_geometry and vnc_geometry.count('x') == 1 else "1920x1080x24"
            debug_info.append(f"未检测到 X 服务器，启动 Xvfb :99 ({xvfb_screen})...")
            DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", "-d", id, "bash", "-c",
                f"rm -f /tmp/.X{display_num.lstrip(':')}-lock && "
                f"Xvfb {display_num} -screen 0 {xvfb_screen} -ac +extension GLX +render -noreset > /log/xvfb.log 2>&1 &"))
            time.sleep(2)

        # 确保 xdotool/wmctrl 可用（用于最大化窗口）
        DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "export DEBIAN_FRONTEND=noninteractive && "
            "which wmctrl xdotool >/dev/null 2>&1 || "
            "(apt-get update -qq && apt-get install -y -qq wmctrl xdotool >/log/wmtools_install.log 2>&1)"
        ), timeout=120)

        # 查找/注入 rviz 配置（容器内 -> 宿主机 install -> 项目 data/simu.rviz）
        rviz_config = _resolve_rviz_config(id, container_user)
        if rviz_config:
            debug_info.append(f"使用 rviz 配置: {rviz_config}")
        else:
            debug_info.append("未找到 simu.rviz，使用默认空配置启动")

        # 如果 rviz2 已经在跑（连到任意 DISPLAY），先杀掉避免多窗口
        DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", container_user, id, "bash", "-c", "pkill -f rviz2 2>/dev/null || true"
        ))
        time.sleep(1)

        if rviz_config:
            rviz_cmd = (
                f"cd /home/boonray && source install/setup.bash && "
                f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                f"export LIBGL_ALWAYS_SOFTWARE=1 && export OGRE_RENDER_SYSTEM=OpenGL && "
                f"export QT_X11_NO_MITSHM=1 && "
                f"nohup rviz2 -d {rviz_config} > /log/rviz2.log 2>&1 &"
            )
        else:
            rviz_cmd = (
                f"cd /home/boonray && source install/setup.bash && "
                f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                f"export LIBGL_ALWAYS_SOFTWARE=1 && export OGRE_RENDER_SYSTEM=OpenGL && "
                f"export QT_X11_NO_MITSHM=1 && "
                f"nohup rviz2 > /log/rviz2.log 2>&1 &"
            )

        debug_info.append(f"执行命令: {rviz_cmd}")
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", container_user, "-d", id, "bash", "-c", rviz_cmd))

        # 等待 rviz 窗口出现后最大化
        _maximize_rviz(id, container_user, display_num, wait_seconds=8)
        time.sleep(1)

        # 检查 rviz2 进程是否启动
        rc_ps, ps_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", "ps aux | grep rviz2 | grep -v grep || echo NOT_RUNNING"))
        rviz_running = not ps_out.strip().endswith('NOT_RUNNING')

        db.add_audit_log(current_user["username"], "open_rviz", f"{id} - {' | '.join(debug_info)}")

        if rviz_running:
            debug_info.append("RVIZ2 进程已启动")
            return {"success": True, "message": f"已启动 RVIZ2 (domain_id={domain_id}, display={display_num})", "debug": debug_info}
        else:
            rc_log, log_out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "cat", "/log/rviz2.log"))
            debug_info.append(f"进程未启动，日志内容: {log_out[:500]}")
            return {"success": False, "error": "RVIZ2 进程未启动，请检查日志", "debug": debug_info}
    except Exception as e:
        logger.error(f"启动 RVIZ2 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

@router.delete("/api/docker/container/{id}")
async def delete_container(id: str, force: bool = False, current_user: dict = Depends(require_permission('docker'))):
    """删除 Docker 容器"""
    if not _check_container_access(id, current_user):
        raise HTTPException(403, "无权操作此容器")
    # 反查容器名，删除后同步清理 containers 表
    rc_name, name_out, _ = DockerManager.run_cmd(DockerManager._docker("inspect", "--format", "{{.Name}}", id))
    cmd = DockerManager._docker("rm") + (["-f"] if force else []) + [id]
    rc, out, err = DockerManager.run_cmd(cmd)
    if rc == 0 and rc_name == 0 and name_out.strip():
        db.remove_container_record(name_out.strip().lstrip("/"))
    db.add_audit_log(current_user["username"], "delete_container", f"{id} force={force}")
    return {"success": rc == 0, "message": out or err}

@router.get("/api/docker/container/{id}/logs")
async def container_logs(id: str, tail: int = 100, current_user: dict = Depends(require_permission('docker'))):
    """获取容器日志"""
    rc, out, err = DockerManager.run_cmd(DockerManager._docker("logs", "--tail", str(tail), id))
    return {"success": rc == 0, "logs": out if rc == 0 else err}

@router.post("/api/docker/container/{id}/exec")
async def container_exec(id: str, data: Dict[str, str], current_user: dict = Depends(require_permission('docker'))):
    """在容器内执行命令"""
    if not id or id == "undefined":
        raise HTTPException(status_code=400, detail="无效的容器 ID")
    cmd = data.get("command")
    if not cmd:
        raise HTTPException(status_code=400, detail="缺少命令")
    # ★ bug2 修复：ros2 topic echo 需自动补 --once，避免持续输出导致终端阻塞
    stripped = cmd.strip()
    if stripped.startswith("ros2 topic echo") and "--once" not in cmd and "--head" not in cmd and "-n " not in cmd:
        # 仅在末尾无管道/重定向时补 --once
        if not any(op in cmd for op in ["|", ">", "<", "&"]):
            cmd = cmd + " --once"
    if not cmd.startswith("source"):
        container_install = ROS2_DEFAULT["container_install"]
        full_cmd = f"bash -c 'source {container_install}/setup.bash && {cmd}'"
    else:
        full_cmd = f"bash -c '{cmd}'"
    rc, out, err = DockerManager.exec_command(id, full_cmd)
    db.add_audit_log(current_user["username"], "container_exec", f"{id} -> {cmd}")
    return {"success": rc == 0, "stdout": out, "stderr": err}


@router.get("/api/docker/container/{id}/roslogs")
async def container_roslogs(id: str, tail: int = 200, current_user: dict = Depends(require_permission('docker'))):
    """读取容器对应的宿主机 ROS2 日志文件（~/robotruck_ros2/Docker/logs/{容器名}_*.log）

    用于解决 `docker logs` 仅显示容器 stdout/stderr 而无法读取 ROS2 节点日志的问题。
    """
    rc, name_out, name_err = DockerManager.run_cmd(
        DockerManager._docker("inspect", "--format", "{{.Name}}", id)
    )
    container_name = (name_out or "").strip().lstrip("/") if rc == 0 else ""

    workspace_paths = get_user_workspace_paths(current_user)
    logs_dir = workspace_paths["logs_dir"]
    candidates: List[str] = []
    if container_name:
        named_logs = glob.glob(os.path.join(logs_dir, f"{container_name}_*.log"))
        named_logs += glob.glob(os.path.join(logs_dir, f"{container_name}.log"))
        named_logs_sorted = sorted(named_logs, key=lambda p: os.path.getmtime(p), reverse=True)
        candidates.extend(named_logs_sorted)
    all_logs = sorted(
        glob.glob(os.path.join(logs_dir, "*.log")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for f in all_logs:
        if f not in candidates:
            candidates.append(f)

    logs_content = ""
    used_file = ""
    for cand in candidates[:5]:
        try:
            if not os.path.isfile(cand):
                continue
            with open(cand, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail_lines = lines[-tail:] if tail > 0 else lines
            logs_content += f"\n===== {os.path.basename(cand)} =====\n" + "".join(tail_lines)
            used_file = cand
            break
        except Exception as e:
            logger.warning(f"读取容器日志文件失败: {cand}, {e}")
            continue

    if not logs_content:
        return {
            "success": False,
            "error": f"未找到容器 {container_name or id} 对应的日志文件（查找目录: {logs_dir}）",
            "logs_dir": logs_dir,
            "container_name": container_name,
        }

    return {
        "success": True,
        "logs": logs_content,
        "log_file": used_file,
        "container_name": container_name,
        "logs_dir": logs_dir,
    }

@router.post("/api/docker/container/{id}/update")
async def container_update(id: str, data: Dict[str, Any], current_user: dict = Depends(require_permission('docker'))):
    """更新容器资源限制"""
    cpus = data.get("cpus")
    mem = data.get("memory_gb")
    rc, out, err = DockerManager.update_resources(id, cpus, mem)
    db.add_audit_log(current_user["username"], "container_update", f"{id} cpu={cpus} mem={mem}GB")
    return {"success": rc == 0, "message": out or err}

@router.post("/api/docker/stop-all-ros2")
async def stop_all_ros2(current_user: dict = Depends(require_permission('docker'))):
    """停止所有 ROS2 容器（普通用户仅停止自己启动的容器，管理员停止全部）"""
    # 普通用户权限隔离：只停止当前用户创建的容器
    visible_names = db.get_visible_container_names(current_user)
    if visible_names is None:
        # admin 或 JSON 模式：停止所有 ros2_ 前缀容器
        results = DockerManager.stop_all_ros2_containers()
        scope = f"{len(results)} containers (all)"
    else:
        # 普通用户：仅停止自己启动的 ros2_ 前缀容器
        results = DockerManager.stop_all_ros2_containers(container_names=list(visible_names))
        scope = f"{len(results)} containers (own)"
    db.add_audit_log(current_user["username"], "stop_all_ros2", scope)
    # T-5.2-04：批量记录停止事件
    from services.run_records import record_run
    for name, ok, errmsg in results:
        record_run("stop", current_user.get("username", ""), container_name=name,
                   success=ok, error=(errmsg or "")[:500])
    return {"success": True, "results": [{"name": r[0], "ok": r[1]} for r in results]}

@router.post("/api/docker/sync-time")
async def sync_time(current_user: dict = Depends(require_permission('docker'))):
    """同步宿主机时间到所有运行中容器"""
    containers = DockerManager.list_containers(running_only=True)
    success = []
    failed = []
    for c in containers:
        name = c["name"]
        cmd = DockerManager._docker("cp", "/etc/localtime", f"{name}:/etc/localtime")
        rc, out, err = DockerManager.run_cmd(cmd)
        if rc == 0:
            success.append(name)
        else:
            failed.append(name)
    db.add_audit_log(current_user["username"], "sync_time", f"success={len(success)}, failed={len(failed)}")
    return {"success": True, "success_list": success, "failed_list": failed}

@router.post("/api/docker/container/{id}/commit")
async def commit_container(id: str, data: Dict[str, str], current_user: dict = Depends(require_permission('advanced-docker'))):
    """将容器变更提交为新镜像"""
    repo = data.get("repository", "custom_image")
    tag = data.get("tag", "latest")
    message = data.get("message", "")
    image_name = f"{repo}:{tag}"
    cmd = DockerManager._docker("commit")
    if message:
        cmd.extend(["-m", message])
    cmd.extend([id, image_name])
    rc, out, err = DockerManager.run_cmd(cmd, timeout=60)
    db.add_audit_log(current_user["username"], "commit_container", f"{id} -> {image_name}")
    return {"success": rc == 0, "image": image_name if rc == 0 else "", "message": out or err}

@router.get("/api/docker/container/{id}/foxglove-url")
async def get_foxglove_url(id: str, current_user: dict = Depends(require_permission('docker'))):
    """获取 Foxglove Studio 可视化 URL"""
    container_ip = DockerManager.get_container_info(id, "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
    if not container_ip:
        return {"success": False, "error": "无法获取容器IP"}
    
    host_ip = get_host_ip()
    config = VISUALIZATION_METHODS.get("foxglove", {})
    container_port = config.get("container_port", config.get("port", 9090))
    host_port = get_host_port(id, container_port)
    if not host_port:
        host_port = str(config.get("port", 9090))
    
    bridge_url = f"ws://{host_ip}:{host_port}"
    foxglove_url = f"https://studio.foxglove.dev/?ds=foxglove-websocket&ds.url={bridge_url}"
    return {"success": True, "foxglove_url": foxglove_url, "bridge_url": bridge_url, "container_ip": container_ip.strip(), "host_ip": host_ip, "host_port": host_port}
