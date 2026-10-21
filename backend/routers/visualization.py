#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可视化方案 路由模块（v6.0 从 api.py 按业务域拆分，T-6.0-01 批次2）。"""
from .common import *  # noqa: F401,F403  -- 共享依赖（db/DockerManager/logger 等）
from core.utils import _resolve_rviz_config, _maximize_rviz  # noqa: F401  -- import * 不导出下划线名称

router = APIRouter()

# ---------- 可视化方案 API ----------
@router.get("/api/visualization/methods")
async def get_visualization_methods(current_user: dict = Depends(require_permission('docker'))):
    """获取所有可用的可视化方案配置"""
    methods = {}
    for key, config in VISUALIZATION_METHODS.items():
        methods[key] = {
            "name": config.get("name", key),
            "description": config.get("description", ""),
            "enabled": config.get("enabled", False)
        }
    # 获取顺序配置，默认为所有方法的key列表
    order = VISUALIZATION_CONFIG.get("order", list(VISUALIZATION_METHODS.keys()))
    return {
        "success": True,
        "default_method": DEFAULT_VISUALIZATION_METHOD,
        "methods": methods,
        "order": order
    }

@router.post("/api/visualization/set-default")
async def set_default_visualization_method(method: str, current_user: dict = Depends(require_permission('admin'))):
    """设置默认可视化方案"""
    if method not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method}"}
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        cfg["visualization"]["default_method"] = method
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    
    global DEFAULT_VISUALIZATION_METHOD
    DEFAULT_VISUALIZATION_METHOD = method
    
    return {"success": True, "message": f"已设置默认可视化方案为: {VISUALIZATION_METHODS[method].get('name', method)}"}

@router.post("/api/visualization/method/{method_key}")
async def update_visualization_method(method_key: str, config: dict = Body(...), current_user: dict = Depends(require_permission('admin'))):
    """更新可视化方案配置"""
    if method_key not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method_key}"}
    
    # 更新内存中的配置
    if "enabled" in config:
        VISUALIZATION_METHODS[method_key]["enabled"] = config["enabled"]
    if "name" in config:
        VISUALIZATION_METHODS[method_key]["name"] = config["name"]
    if "description" in config:
        VISUALIZATION_METHODS[method_key]["description"] = config["description"]
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        if "methods" not in cfg["visualization"]:
            cfg["visualization"]["methods"] = {}
        if method_key not in cfg["visualization"]["methods"]:
            cfg["visualization"]["methods"][method_key] = {}
        
        if "enabled" in config:
            cfg["visualization"]["methods"][method_key]["enabled"] = config["enabled"]
        if "name" in config:
            cfg["visualization"]["methods"][method_key]["name"] = config["name"]
        if "description" in config:
            cfg["visualization"]["methods"][method_key]["description"] = config["description"]
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    
    return {
        "success": True, 
        "message": f"已更新可视化方案: {VISUALIZATION_METHODS[method_key].get('name', method_key)}",
        "method": {
            "key": method_key,
            "name": VISUALIZATION_METHODS[method_key].get("name", method_key),
            "description": VISUALIZATION_METHODS[method_key].get("description", ""),
            "enabled": VISUALIZATION_METHODS[method_key].get("enabled", False)
        }
    }

@router.post("/api/visualization/order")
async def update_visualization_order(order: list = Body(...), current_user: dict = Depends(require_permission('admin'))):
    """更新可视化方案顺序"""
    # 验证顺序中的所有key都有效
    for key in order:
        if key not in VISUALIZATION_METHODS:
            return {"success": False, "error": f"未知的可视化方案: {key}"}
    
    # 更新配置文件
    config_path = CONFIG_FILE
    if config_path.is_file():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if "visualization" not in cfg:
            cfg["visualization"] = {}
        cfg["visualization"]["order"] = order
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    
    return {"success": True, "message": "可视化方案顺序已更新", "order": order}

@router.post("/api/docker/container/{id}/visualize")
async def visualize_container(id: str, method: str = None, request: Request = None, current_user: dict = Depends(require_permission('docker'))):
    """启动容器可视化"""
    if method is None:
        method = DEFAULT_VISUALIZATION_METHOD
    
    if method not in VISUALIZATION_METHODS:
        return {"success": False, "error": f"未知的可视化方案: {method}"}
    
    method_config = VISUALIZATION_METHODS[method]
    if not method_config.get("enabled", False):
        return {"success": False, "error": f"可视化方案 {method} 未启用"}
    
    container_info = DockerManager.get_container_info(id, "{{.State.Running}}")
    if not container_info or "true" not in container_info.lower():
        return {"success": False, "error": "容器未运行，无法启动可视化"}

    scheme = "http"
    host_ip = get_host_ip()

    # v3.6: Foxglove 已注释，仅保留 vnc 和 rviz_x11（均通过容器内 noVNC 实现）
    # 两个方法共用容器内的 Xvfb + x11vnc + noVNC 方案，vnc 打开纯桌面，rviz_x11 自动启动 rviz2
    if method == "foxglove":
        # return await start_foxglove_visualization(id, container_ip, scheme)
        return {"success": False, "error": "Foxglove 已禁用，请使用 VNC 远程桌面或原生 RVIZ"}
    elif method == "vnc":
        return await start_vnc_visualization(id, host_ip, scheme, auto_start_rviz=False)
    elif method == "rviz_x11":
        return await start_vnc_visualization(id, host_ip, scheme, auto_start_rviz=True)
    else:
        return {"success": False, "error": f"未实现的可视化方案: {method}"}



async def start_foxglove_visualization(id, container_ip, scheme="http"):
    """启动 Foxglove Studio 可视化"""
    host_ip = get_host_ip()
    config = VISUALIZATION_METHODS["foxglove"]
    container_port = config.get("container_port", config.get("port", 9090))
    host_port = get_host_port(id, container_port)
    
    # 如果没有端口映射，尝试获取容器端口
    if not host_port:
        host_port = str(container_port)
    
    # 检查 rosbridge 是否运行
    rc, out, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", 
        f"source /opt/ros/humble/setup.bash && ros2 node list 2>/dev/null | grep -i rosbridge || true"))
    
    if not out.strip():
        # 检查 rosbridge 是否安装
        rc_check, out_check, _ = DockerManager.run_cmd(DockerManager._docker("exec", id, "bash", "-c", 
            "source /opt/ros/humble/setup.bash && ros2 pkg list 2>/dev/null | grep -i rosbridge || true"))
        if not out_check.strip():
            # 安装 rosbridge_server
            DockerManager.run_cmd(DockerManager._docker("exec", "-d", id, "bash", "-c", 
                "source /opt/ros/humble/setup.bash && apt-get update && apt-get install -y ros-humble-rosbridge-server"))
        
        # 启动 rosbridge_server
        cmd = f"source /opt/ros/humble/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml > /tmp/rosbridge.log 2>&1 &"
        DockerManager.run_cmd(DockerManager._docker("exec", "-d", id, "bash", "-c", cmd))
        # 等待启动
        import time
        time.sleep(5)
    
    # 根据请求协议生成正确的WebSocket URL
    ws_scheme = "wss" if scheme == "https" else "ws"
    bridge_url = f"{ws_scheme}://{host_ip}:{host_port}"
    foxglove_url = f"https://studio.foxglove.dev/?ds=foxglove-websocket&ds.url={bridge_url}"
    
    return {
        "success": True,
        "method": "foxglove",
        "name": "Foxglove Studio",
        "url": foxglove_url,
        "bridge_url": bridge_url,
        "container_ip": container_ip,
        "host_ip": host_ip,
        "host_port": host_port,
        "message": "Foxglove Studio URL 已生成，请点击链接打开。打开后在 Foxglove 中添加数据源选择 WebSocket 连接。"
    }

def find_available_port():
    """查找一个可用的空闲端口"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

def run_host_cmd(cmd, timeout=30, background=False):
    """在宿主机上执行命令（不添加docker前缀）"""
    import subprocess
    try:
        if isinstance(cmd, str):
            if background:
                pass
            else:
                cmd = cmd.split()
        if not background and USE_SUDO and cmd[0] not in ['sudo', 'which', 'bash']:
            cmd = ['sudo'] + cmd
        
        if background:
            if isinstance(cmd, list):
                cmd = ' '.join(cmd)
            full_cmd = cmd
            if USE_SUDO and not cmd.startswith('sudo ') and not cmd.startswith('which ') and not cmd.startswith('bash '):
                full_cmd = 'sudo ' + full_cmd
            proc = subprocess.Popen(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return 0, str(proc.pid), ""
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)

def check_host_command(cmd):
    """检查宿主机上是否有某个命令"""
    rc, _, _ = run_host_cmd(["which", cmd])
    return rc == 0

async def start_vnc_visualization(id, host_ip, scheme="http", auto_start_rviz=False):
    """启动容器内 VNC 远程桌面可视化（含 noVNC）。

    v3.6 重写：
    - 根据容器 ID 哈希动态分配 DISPLAY 号（:99~:199），避免多容器共享
      /tmp/.X11-unix 时 Xvfb socket 冲突导致画面串台。
    - 若容器已有 Xvfb 进程则复用其 display。
    - 在容器内以 root 启动 x11vnc（attach 到该 DISPLAY）和 websockify/noVNC（监听 6080）。
    - 容器通过 docker-compose 映射 6080→宿主机固定端口（如 ros2_fz001→6100），
      宿主机无需安装任何软件，直接访问宿主机端口即可打开 noVNC。
    - rviz2 使用容器默认用户（boonray）在目标 DISPLAY 上启动。
    """
    import time
    container_vnc_port = 5901
    container_web_port = 6080

    # 获取容器默认运行用户（用于启动 rviz2）
    rc, container_user, _ = DockerManager.run_cmd(DockerManager._docker(
        "exec", id, "bash", "-c", "whoami"
    ))
    container_user = container_user.strip() if rc == 0 and container_user.strip() else "boonray"

    # 获取 DISPLAY 号：优先级 1) 容器已有 Xvfb 进程 -> 复用；2) 容器标签 ros2.display -> 使用预设；3) 动态哈希分配
    # 新版脚本（2026-07）不再挂载宿主机 /tmp/.X11-unix，每个容器完全独立，Xvfb 在容器启动时已启动
    rc, xvfb_out, _ = DockerManager.run_cmd(DockerManager._docker(
        "exec", "-u", "root", id, "bash", "-c",
        "ps aux | grep '[X]vfb' | grep -oP 'Xvfb \\K:\\d+' | head -1"
    ))
    if xvfb_out.strip():
        display_num = xvfb_out.strip()
        need_start_xvfb = False
        logger.info(f"[{id}] 容器内已有 Xvfb {display_num} 运行，复用之")
    else:
        # 优先检查容器标签中预设的 display
        rc, label_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "inspect", "-f", "{{index .Config.Labels \"ros2.display\"}}", id
        ))
        if rc == 0 and label_out.strip() and label_out.strip() != "<no value>":
            display_num = label_out.strip()
            if not display_num.startswith(":"):
                display_num = ":" + display_num
            need_start_xvfb = False
            logger.info(f"[{id}] 使用容器标签预设的 DISPLAY={display_num}，Xvfb 应已启动")
        else:
            # 回退：动态哈希分配（兼容旧容器）
            import hashlib
            base_display = 99 + (int(hashlib.md5(id.encode()).hexdigest(), 16) % 100)
            display_num = f":{base_display}"
            for offset in range(0, 100):
                d = base_display + offset
                rc, chk, _ = DockerManager.run_cmd(DockerManager._docker(
                    "exec", "-u", "root", id, "bash", "-c",
                    f"test -e /tmp/.X11-unix/X{d} && echo EXISTS || echo FREE"
                ))
                if 'FREE' in chk:
                    display_num = f":{d}"
                    break
            need_start_xvfb = True
            logger.info(f"[{id}] 未检测到预设 DISPLAY，动态分配 Xvfb {display_num} 虚拟显示")

    # 1) 检查 VNC(5901) / noVNC(6080) 端口是否在监听
    def port_listening(port):
        rc, out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"netstat -tln 2>/dev/null | grep -q ':{port} ' && echo YES || echo NO"
        ))
        return 'YES' in out

    vnc_listening = port_listening(container_vnc_port)
    web_listening = port_listening(container_web_port)
    services_running = vnc_listening and web_listening

    if not services_running:
        # 2) 以 root 在容器内安装必要软件（缺则装）
        rc, which_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "which Xvfb x11vnc websockify >/dev/null 2>&1 && echo ALL_PRESENT || echo NEED_INSTALL"
        ))
        if 'NEED_INSTALL' in which_out:
            logger.info(f"[{id}] 容器内缺少 VNC 组件，开始 root 安装...")
            install_cmd = (
                "export DEBIAN_FRONTEND=noninteractive && "
                "apt-get update -qq && "
                "apt-get install -y -qq xvfb x11vnc novnc websockify x11-utils wmctrl xdotool "
                "> /log/vnc_install.log 2>&1 && "
                "echo INSTALL_OK >> /log/vnc_install.log"
            )
            rc, out, err = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c", install_cmd
            ), timeout=180)
            logger.info(f"[{id}] 容器内安装包 rc={rc}, err={err[:200] if err else ''}")

        # 3) 若需要，启动 Xvfb
        if need_start_xvfb:
            disp_n = display_num.lstrip(":")
            # 从配置中读取 VNC 分辨率，默认 1920x1080
            vnc_geometry = CONFIG.get("visualization", {}).get("methods", {}).get("vnc", {}).get("geometry", "1920x1080")
            xvfb_screen = f"{vnc_geometry}x24" if 'x' in vnc_geometry and vnc_geometry.count('x') == 1 else "1920x1080x24"
            DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c",
                f"rm -f /tmp/.X{disp_n}-lock && "
                f"Xvfb {display_num} -screen 0 {xvfb_screen} -ac +extension GLX +render -noreset "
                f"> /log/xvfb.log 2>&1 &"
            ))
            time.sleep(2)

        # 4) 启动 x11vnc（attach 到目标 DISPLAY，监听 5901）
        # -noshm 解决容器内 X MIT-SHM 权限问题；-noxdamage 避免部分 X server 崩溃
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c",
            f"x11vnc -display {display_num} -rfbport {container_vnc_port} -forever -shared -nopw "
            f"-noxdamage -ncache 0 -rfbwait 30000 -noshm -bg -o /log/x11vnc.log"
        ))
        time.sleep(2)

        # 检查 x11vnc 是否监听
        rc, chk_vnc, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"netstat -tln 2>/dev/null | grep -q ':{container_vnc_port} ' && echo LISTEN || echo NOT_LISTEN"
        ))
        if 'NOT_LISTEN' in chk_vnc:
            logger.warning(f"[{id}] x11vnc 首次启动未监听，查看日志")
            rc, log_out, _ = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c", "tail -20 /log/x11vnc.log"
            ))
            logger.warning(f"[{id}] x11vnc log: {log_out[:500]}")

        # 5) 启动 websockify + novnc（监听 0.0.0.0:6080）
        rc, np_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "for p in /usr/share/novnc /usr/share/www/novnc; do "
            "[ -d $p ] && echo $p && break; done"
        ))
        novnc_path = np_out.strip() if rc == 0 and np_out.strip() else "/usr/share/novnc"
        rc, wsbin_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            "which websockify || (ls /usr/share/novnc/utils/websockify/run 2>/dev/null) || echo websockify"
        ))
        wsbin = wsbin_out.strip().split('\n')[0] if wsbin_out.strip() else "websockify"

        ws_launch_cmd = (
            f"cd {novnc_path} && "
            f"nohup {wsbin} --web={novnc_path} 0.0.0.0:{container_web_port} localhost:{container_vnc_port} "
            f"> /log/novnc.log 2>&1 &"
        )
        DockerManager.run_cmd(DockerManager._docker("exec", "-u", "root", id, "bash", "-c", ws_launch_cmd))
        time.sleep(3)

        # 等待 6080 监听
        for _ in range(8):
            rc, chk, _ = DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c",
                f"netstat -tln 2>/dev/null | grep -q ':{container_web_port} ' && echo LISTEN || echo NOT_LISTEN"
            ))
            if 'LISTEN' in chk:
                logger.info(f"[{id}] 容器内 {container_web_port} 已监听")
                break
            time.sleep(2)

    # 6) 获取容器 6080 映射到宿主机的端口
    host_web_port = get_host_port(id, container_web_port)
    if not host_web_port:
        host_web_port = str(container_web_port)
        logger.warning(f"[{id}] 容器 6080 端口未映射到宿主机，回退到容器端口")

    # 7) 自动启动 rviz2（仅 rviz_x11 模式，用容器默认用户）
    #    关键：必须确保 rviz2 运行在 VNC 可见的 DISPLAY（display_num）上。
    #    如果 rviz2 已经在错误的 display（如 :0 宿主机 X）上运行，需要杀掉后在正确 display 重启。
    if auto_start_rviz:
        # 检查当前 DISPLAY 上是否有 rviz2 窗口
        rc, win_check, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", "root", id, "bash", "-c",
            f"DISPLAY={display_num} xwininfo -root -children 2>/dev/null | grep -i rviz | head -1 || echo NO_RVIZ_WIN"
        ))
        rviz_on_correct_display = 'rviz' in win_check.lower() and 'NO_RVIZ_WIN' not in win_check

        # 检查是否有 rviz2 进程在跑
        rc, rviz_out, _ = DockerManager.run_cmd(DockerManager._docker(
            "exec", "-u", container_user, id, "bash", "-c",
            f"ps -u $(id -u) -o pid=,comm=,args= | grep -v grep | grep rviz2 || echo NOT_RUNNING"
        ))
        rviz_running = 'NOT_RUNNING' not in rviz_out

        # 如果 rviz2 跑错了 display（VNC 屏幕上看不到），先杀掉旧进程
        need_restart_rviz = rviz_running and not rviz_on_correct_display
        if need_restart_rviz:
            logger.info(f"[{id}] rviz2 运行中但不在 DISPLAY={display_num} 上（可能连到了宿主机 :0），将在正确 display 重启")
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", container_user, id, "bash", "-c",
                "pkill -f rviz2; sleep 1"
            ))
            rviz_running = False

        if not rviz_running:
            # 获取 ROS_DOMAIN_ID
            rc, env_out, _ = DockerManager.run_cmd(DockerManager._docker(
                "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", id
            ))
            domain_id = "0"
            if env_out:
                m = re.search(r'ROS_DOMAIN_ID=(\d+)', env_out)
                if m:
                    domain_id = m.group(1)

            # 确保 wmctrl/xdotool 已存在（用于后续最大化 rviz 窗口）
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", "root", id, "bash", "-c",
                "export DEBIAN_FRONTEND=noninteractive && "
                "which wmctrl xdotool >/dev/null 2>&1 || "
                "(apt-get update -qq && apt-get install -y -qq wmctrl xdotool >/log/wmtools_install.log 2>&1)"
            ), timeout=120)

            # 查找/注入 rviz 配置（优先用户 install 内，找不到则回退到宿主机 data/simu.rviz）
            rviz_config = _resolve_rviz_config(id, container_user)

            if rviz_config:
                rviz_cmd = (
                    f"cd /home/boonray && source install/setup.bash && "
                    f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                    f"export LIBGL_ALWAYS_SOFTWARE=1 && export QT_X11_NO_MITSHM=1 && "
                    f"nohup rviz2 -d {rviz_config} > /log/rviz2.log 2>&1 &"
                )
            else:
                rviz_cmd = (
                    f"cd /home/boonray && source install/setup.bash && "
                    f"export ROS_DOMAIN_ID={domain_id} && export DISPLAY={display_num} && "
                    f"export LIBGL_ALWAYS_SOFTWARE=1 && export QT_X11_NO_MITSHM=1 && "
                    f"nohup rviz2 > /log/rviz2.log 2>&1 &"
                )
            DockerManager.run_cmd(DockerManager._docker(
                "exec", "-u", container_user, id, "bash", "-c", rviz_cmd
            ))
            time.sleep(2)
            # 等待 rviz 窗口出现并最大化、移到 (0,0)，避免配置文件里保存的 1692x1094@(437,118)
            # 导致右侧面板被截断在 Xvfb 1920x1080 屏幕外
            _maximize_rviz(id, container_user, display_num, wait_seconds=8)
        elif rviz_running and rviz_on_correct_display:
            # rviz2 已经在正确 DISPLAY 上运行，可能是之前启动时窗口位置/尺寸偏移，补一次最大化
            _maximize_rviz(id, container_user, display_num, wait_seconds=2)

    # 8) 构建访问 URL
    #    novnc 不同版本 websocket 路径可能是 /websockify 或 /，URL 用 vnc.html 默认参数即可自动连接
    web_vnc_url = f"{scheme}://{host_ip}:{host_web_port}/vnc.html?autoconnect=true&resize=scale&path=websockify"
    method_name = "原生 RVIZ (X11)" if auto_start_rviz else "VNC 远程桌面"
    msg = f"{method_name} 已启动！Web 访问地址: {web_vnc_url}（无需密码，DISPLAY={display_num}"
    if auto_start_rviz:
        msg += "，rviz2 已自动启动"
    msg += "）"

    return {
        "success": True,
        "method": "rviz_x11" if auto_start_rviz else "vnc",
        "name": method_name,
        "url": web_vnc_url,
        "host_ip": host_ip,
        "host_web_port": host_web_port,
        "display": display_num,
        "message": msg,
    }

# v3.6: 旧版 start_rviz_x11_visualization 已废弃，功能合并到 start_vnc_visualization(auto_start_rviz=True)
# async def start_rviz_x11_visualization(...): 保留空实现占位避免代码引用出错
async def start_rviz_x11_visualization(*args, **kwargs):
    """Deprecated: 已合并到 start_vnc_visualization(auto_start_rviz=True)。"""
    host_ip = get_host_ip()
    cid = args[0] if args else kwargs.get('id')
    return await start_vnc_visualization(cid, host_ip, kwargs.get('scheme', 'http'), auto_start_rviz=True)
