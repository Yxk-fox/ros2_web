#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
版权所有：上海伯镭科技有限公司
@File    :  deploy.py
@Time    :  2026/07/21
@Author  :  Fox
@Version :  5.2
@Desc    :  Mock Truck 管理工具 - 一键部署脚本（解耦优化版）
            包含：环境检测、依赖安装、服务部署、自启动配置
            优化：已安装环境自动跳过，支持 --skip-system 快速部署
            v5.2：部署前单测回归（--skip-tests 可跳过并留痕）+
                  部署后健康探测（/ 与 /api/system/ping）+ 失败回滚指引
"""

import os
import sys
import time
import json
import subprocess
import shutil
import platform
import re
import argparse
import urllib.request
import urllib.error

DEPLOY_REPORT = {
    "environment": {},
    "python_deps": {
        "already_installed": [],
        "newly_installed": [],
        "failed": []
    },
    "tests": {
        "executed": False,
        "skipped": False,
        "passed": False,
        "summary": ""
    },
    "health_check": {
        "executed": False,
        "passed": False,
        "endpoints": []
    },
    "steps": [],
    "status": "success"
}


def run_cmd(cmd, capture=True, sudo=False):
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    try:
        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        else:
            subprocess.run(cmd)
            return 0, "", ""
    except Exception as e:
        return -1, "", str(e)


def get_current_user():
    """获取实际执行用户名（适配所有服务器环境，无需修改脚本）

    获取优先级：
      1. SUDO_USER   —— sudo 执行时记录的真实调用用户
      2. LOGNAME / USER / USERNAME —— 各发行版通用的环境变量
      3. getpass.getuser() —— 兜底方案
    不使用 os.getlogin()，因其依赖控制终端，在 systemd / cron / ssh 无 tty
    环境下会抛 OSError。
    """
    user = os.environ.get("SUDO_USER", "").strip()
    if user:
        return user
    for var in ("LOGNAME", "USER", "USERNAME"):
        user = os.environ.get(var, "").strip()
        if user and user != "root":
            return user
    try:
        import getpass
        user = getpass.getuser()
        if user and user != "root":
            return user
    except Exception:
        pass
    return "root"


def ensure_root(args):
    """确保以 root 权限运行；非 root 时提示使用 sudo 执行（会提示输入当前用户密码）

    --only-deps 模式仅安装 Python 依赖（pip --user），无需 root。
    """
    if os.geteuid() == 0:
        return
    if args.only_deps:
        print_warning("当前以普通用户运行，仅安装依赖模式（--only-deps）无需 root")
        return

    user = get_current_user()
    script = os.path.abspath(__file__)
    print_error("部署需要 root 权限（安装系统软件 / 写入 systemd 服务 / 配置 Docker 组）")
    print_info(f"请使用以下命令重新执行（sudo 将提示输入用户 {user} 的密码）：")
    print_info(f"    sudo python3 {script}")
    try:
        answer = input("\n是否现在自动以 sudo 重新执行？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in ("y", "yes"):
        cmd = ["sudo", sys.executable, script] + sys.argv[1:]
        sys.exit(subprocess.run(cmd).returncode)
    print_warning(f"已取消，请手动执行：sudo python3 {script}")
    sys.exit(1)


def print_info(msg):
    print(f"\033[94m[INFO] {msg}\033[0m")


def print_success(msg):
    print(f"\033[92m[SUCCESS] {msg}\033[0m")


def print_error(msg):
    print(f"\033[91m[ERROR] {msg}\033[0m")


def print_warning(msg):
    print(f"\033[93m[WARNING] {msg}\033[0m")


def check_python():
    print_info("检查 Python 环境...")
    rc, out, err = run_cmd(["python3", "--version"])
    if rc == 0:
        DEPLOY_REPORT["environment"]["python"] = out
        print_success(f"Python 版本: {out}")
        return True
    print_error("Python 3 未安装")
    return False


def check_pip():
    print_info("检查 pip 环境...")
    rc, out, err = run_cmd(["pip3", "--version"])
    if rc == 0:
        DEPLOY_REPORT["environment"]["pip"] = out
        print_success(f"pip 版本: {out}")
        return True
    print_error("pip3 未安装")
    return False


def check_docker():
    print_info("检查 Docker 环境...")
    rc, out, err = run_cmd(["docker", "--version"])
    if rc == 0:
        DEPLOY_REPORT["environment"]["docker"] = out
        print_success(f"Docker 版本: {out}")
        return True
    print_warning("Docker 未安装，将自动安装")
    return False


def check_git():
    print_info("检查 Git 环境...")
    rc, out, err = run_cmd(["git", "--version"])
    if rc == 0:
        DEPLOY_REPORT["environment"]["git"] = out
        print_success(f"Git 版本: {out}")
        return True
    print_warning("Git 未安装，将自动安装")
    return False


def install_python():
    print_info("安装 Python 和 pip...")
    rc, out, err = run_cmd(["apt", "update"], sudo=True)
    if rc != 0:
        print_error(f"更新包列表失败: {err}")
        return False
    rc, out, err = run_cmd(["apt", "install", "-y", "python3", "python3-pip", "python3-venv"], sudo=True)
    if rc == 0:
        print_success("Python 和 pip 安装成功")
        return True
    print_error(f"安装失败: {err}")
    return False


def install_docker():
    print_info("安装 Docker...")
    rc, out, err = run_cmd(["apt", "update"], sudo=True)
    if rc != 0:
        print_error(f"更新包列表失败: {err}")
        return False
    rc, out, err = run_cmd(["apt", "install", "-y", "docker.io"], sudo=True)
    if rc != 0:
        print_error(f"安装失败: {err}")
        return False
    rc, out, err = run_cmd(["systemctl", "enable", "docker"], sudo=True)
    rc, out, err = run_cmd(["systemctl", "start", "docker"], sudo=True)
    print_success("Docker 安装成功")
    return True


def install_git():
    print_info("安装 Git...")
    rc, out, err = run_cmd(["apt", "install", "-y", "git"], sudo=True)
    if rc == 0:
        print_success("Git 安装成功")
        return True
    print_error(f"安装失败: {err}")
    return False


def parse_requirements(req_path):
    packages = []
    with open(req_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                clean_line = re.sub(r'\[.*?\]', '', line)
                match = re.match(r'^([a-zA-Z0-9_-]+)(?:(==|>=|<=|~=|>|<)(.+))?$', clean_line)
                if match:
                    name = match.group(1)
                    op = match.group(2)
                    version = match.group(3)
                    if op and version:
                        packages.append({"name": name, "spec": f"{op}{version}", "version": version})
                    else:
                        packages.append({"name": name, "spec": None, "version": None})
    return packages


def check_package_installed(name, version=None):
    rc, out, err = run_cmd(["pip3", "show", name])
    if rc != 0:
        return False, None
    installed_version = None
    for line in out.split('\n'):
        if line.startswith('Version:'):
            installed_version = line.split(':')[1].strip()
            break
    if installed_version:
        if version:
            if installed_version == version:
                return True, installed_version
            return False, installed_version
        return True, installed_version
    return False, None


def install_python_dependencies():
    """优化版 Python 依赖安装：批量检查，一次性安装缺失包"""
    print_info("检查并安装 Python 依赖...")
    req_path = os.path.join(os.path.dirname(__file__), "redame", "requirements.txt")
    if not os.path.exists(req_path):
        print_error(f"依赖文件不存在: {req_path}")
        return False

    packages = parse_requirements(req_path)
    print_info(f"检测到 {len(packages)} 个依赖包")

    to_install = []
    for pkg in packages:
        installed, ver = check_package_installed(pkg["name"], pkg["version"])
        if installed:
            DEPLOY_REPORT["python_deps"]["already_installed"].append(f"{pkg['name']}=={ver}")
            print_info(f"  ✓ {pkg['name']}=={ver} 已安装，跳过")
        else:
            pkg_str = f"{pkg['name']}{pkg['spec'] if pkg['spec'] else ''}"
            to_install.append(pkg_str)
            if ver:
                print_info(f"  ↻ {pkg['name']} 当前版本 {ver}，将更新至要求版本 {pkg['spec']}")
            else:
                print_info(f"  ✗ {pkg['name']} 未安装，待安装")

    if not to_install:
        print_success("所有 Python 依赖均已安装，无需操作")
        return True

    # 批量安装缺失包（一次性命令，速度更快）
    print_info(f"批量安装 {len(to_install)} 个缺失包...")
    rc, out, err = run_cmd(
        ["pip3", "install", "--no-input", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"] + to_install
    )
    if rc != 0:
        print_warning(f"批量安装输出: {err or out}")

    # 再次验证
    failed = []
    for pkg_str in to_install:
        pkg_name = re.match(r'^([a-zA-Z0-9_-]+)', pkg_str).group(1)
        installed, ver = check_package_installed(pkg_name)
        if installed:
            DEPLOY_REPORT["python_deps"]["newly_installed"].append(f"{pkg_name}=={ver}")
            print_success(f"    ✓ {pkg_name}=={ver} 安装成功")
        else:
            failed.append(pkg_str)
            DEPLOY_REPORT["python_deps"]["failed"].append(pkg_str)
            print_error(f"    ✗ {pkg_str} 安装失败")

    if failed:
        print_warning(f"部分依赖安装失败，共 {len(failed)} 个")
        return True  # 非致命错误，继续部署

    print_success("所有缺失依赖安装成功")
    return True


def user_in_docker_group(user):
    """检查用户是否已在 docker 组"""
    rc, out, err = run_cmd(["id", "-nG", user])
    if rc == 0 and out:
        return "docker" in out.split()
    # 兜底：直接读取 /etc/group
    try:
        with open("/etc/group") as f:
            for line in f:
                if line.startswith("docker:"):
                    members = line.strip().split(":")[-1]
                    return user in members.split(",") if members else False
    except Exception:
        pass
    return False


def add_user_to_docker_group():
    """将实际执行用户自动加入 docker 组（已入组则跳过）"""
    user = get_current_user()
    if user == "root":
        print_warning("检测到 root 直接执行且无 SUDO_USER，跳过 docker 组配置")
        print_warning("如需普通用户使用 docker，请手动执行: sudo usermod -aG docker <用户名>")
        return False
    print_info(f"检查用户 {user} 的 docker 组权限...")
    if user_in_docker_group(user):
        print_success(f"用户 {user} 已在 docker 组中，跳过添加")
        return True
    rc, out, err = run_cmd(["usermod", "-aG", "docker", user], sudo=True)
    if rc == 0:
        print_success(f"用户 {user} 已自动加入 docker 组")
        print_warning("注意：docker 组权限需注销并重新登录后生效（或先执行 newgrp docker）")
        return True
    print_error(f"添加失败: {err}")
    return False


def deploy_systemd_service():
    print_info("部署 systemd 服务...")
    target_path = "/etc/systemd/system/ros2_web.service"

    project_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(project_dir, "backend")
    current_user = get_current_user()
    user_home = os.path.expanduser(f"~{current_user}")
    python3_path = shutil.which("python3") or "/usr/bin/python3"

    service_content = f"""[Unit]
Description=Mock Truck Service (Decoupled)
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User={current_user}
WorkingDirectory={backend_dir}
ExecStart={python3_path} -m uvicorn app:app --host 0.0.0.0 --port 8875
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PATH=/usr/bin:/usr/local/bin:{user_home}/.local/bin"
Environment="ROS_DOMAIN_ID=0"
Environment="RMW_IMPLEMENTATION=rmw_fastrtps_cpp"
Environment="PYTHONPATH={backend_dir}"

[Install]
WantedBy=multi-user.target
"""

    # 检查现有服务是否相同，避免重复写入
    if os.path.exists(target_path):
        with open(target_path, 'r') as f:
            existing = f.read()
        if existing.strip() == service_content.strip():
            print_success("systemd 服务配置已是最新，跳过写入")
            rc, out, err = run_cmd(["systemctl", "daemon-reload"], sudo=True)
            rc, out, err = run_cmd(["systemctl", "enable", "ros2_web"], sudo=True)
            # v5.2：配置未变也重启服务，确保本次部署的代码真正生效（供健康探测验证）
            rc, out, err = run_cmd(["systemctl", "restart", "ros2_web"], sudo=True)
            if rc != 0:
                print_error(f"重启服务失败: {err}")
                return False
            print_success("服务已重启以加载最新代码")
            return True

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.service', delete=False, prefix='ros2_web_') as tmp:
        tmp.write(service_content)
        tmp_path = tmp.name

    try:
        rc, out, err = run_cmd(["cp", tmp_path, target_path], sudo=True)
        if rc != 0:
            print_error(f"写入服务文件失败: {err}")
            return False
    finally:
        os.unlink(tmp_path)

    rc, out, err = run_cmd(["systemctl", "daemon-reload"], sudo=True)
    if rc != 0:
        print_error(f"重载 systemd 失败: {err}")
        return False

    rc, out, err = run_cmd(["systemctl", "enable", "ros2_web"], sudo=True)
    if rc != 0:
        print_error(f"启用服务失败: {err}")
        return False

    rc, out, err = run_cmd(["systemctl", "restart", "ros2_web"], sudo=True)
    if rc != 0:
        print_error(f"启动服务失败: {err}")
        return False

    print_success("systemd 服务部署成功")
    return True


def create_log_directory():
    print_info("创建日志目录...")
    log_dir = os.path.join(os.path.dirname(__file__), "log")
    os.makedirs(log_dir, exist_ok=True)
    print_success(f"日志目录就绪: {log_dir}")


def create_data_directory():
    print_info("创建数据目录...")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    print_success(f"数据目录就绪: {data_dir}")


def move_log_files():
    print_info("移动日志文件到 log 目录...")
    root_dir = os.path.dirname(__file__)
    log_dir = os.path.join(root_dir, "log")
    for log_file in ["audit.log", "audit_debug.log"]:
        src = os.path.join(root_dir, log_file)
        dst = os.path.join(log_dir, log_file)
        if os.path.exists(src):
            shutil.move(src, dst)
            print_success(f"已移动 {log_file} 到 log 目录")


def check_service_status():
    print_info("检查服务状态...")
    rc, out, err = run_cmd(["systemctl", "status", "ros2_web"], sudo=True)
    if rc == 0:
        DEPLOY_REPORT["environment"]["service_status"] = "running"
        print_success("服务运行正常")
    else:
        DEPLOY_REPORT["environment"]["service_status"] = "failed"
        print_warning(f"服务状态异常: {err}")


def check_port_status():
    print_info("检查端口状态...")
    rc, out, err = run_cmd(["ss", "-tlnp"])
    if "8875" in out:
        DEPLOY_REPORT["environment"]["port_status"] = "open"
        print_success("端口 8875 已监听")
    else:
        DEPLOY_REPORT["environment"]["port_status"] = "closed"
        print_warning("端口 8875 未监听")


# ---------- v5.2：部署前回归 + 部署后健康探测 + 回滚指引 ----------

def get_server_config():
    """读取后端 config.json 的 server 节（端口 / SSL 配置），供健康探测使用"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "backend", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            server = json.load(f).get("server", {})
        return {
            "port": int(server.get("port", 8875)),
            "ssl_cert": server.get("ssl_cert", ""),
            "ssl_key": server.get("ssl_key", ""),
        }
    except Exception as e:
        print_warning(f"读取 config.json 失败（{e}），健康探测使用默认端口 8875")
        return {"port": 8875, "ssl_cert": "", "ssl_key": ""}


def run_unit_tests():
    """部署前执行后端单元测试回归（T-5.2-02）

    - 使用当前 Python 解释器执行 `python -m pytest backend/tests -q`
    - 失败即返回 False，调用方须中止部署（阻止带病上线）
    - pytest 未安装时视为失败并提示（依赖安装步骤已覆盖 requirements.txt）
    """
    project_dir = os.path.dirname(os.path.abspath(__file__))
    tests_dir = os.path.join(project_dir, "backend", "tests")

    DEPLOY_REPORT["tests"]["executed"] = True
    print_info("部署前回归：执行后端单元测试（pytest）...")

    if not os.path.isdir(tests_dir):
        DEPLOY_REPORT["tests"]["passed"] = False
        DEPLOY_REPORT["tests"]["summary"] = f"测试目录不存在: {tests_dir}"
        print_error(DEPLOY_REPORT["tests"]["summary"])
        return False

    try:
        # 注意：不传 -q —— pytest.ini 已有 addopts=-q，叠加会升级为 -qq 并抑制统计行
        result = subprocess.run(
            [sys.executable, "-m", "pytest", tests_dir, "--no-header"],
            cwd=project_dir, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        DEPLOY_REPORT["tests"]["passed"] = False
        DEPLOY_REPORT["tests"]["summary"] = "单元测试执行超时（>10 分钟）"
        print_error(DEPLOY_REPORT["tests"]["summary"])
        return False
    except FileNotFoundError:
        DEPLOY_REPORT["tests"]["passed"] = False
        DEPLOY_REPORT["tests"]["summary"] = (
            f"pytest 不可用（{sys.executable} -m pytest 失败），"
            f"请先安装: pip3 install pytest pytest-cov"
        )
        print_error(DEPLOY_REPORT["tests"]["summary"])
        return False

    # pytest -q 输出统计行形如 "45 passed in 2.34s" / "2 failed, 43 passed in ..."
    # 从后往前找第一行含 "passed"/"failed"/"error" 的统计行，避免取到进度点行 [100%]
    summary = ""
    for line in reversed((result.stdout or "").strip().splitlines()):
        line = line.strip()
        if line and re.search(r"\b(passed|failed|error)\b", line):
            summary = line
            break
    if not summary:
        summary = (result.stderr or "").strip()[:200] or f"pytest 退出码 {result.returncode}"
    DEPLOY_REPORT["tests"]["summary"] = summary

    if result.returncode != 0:
        print_error(f"单元测试未通过（退出码 {result.returncode}）：{summary}")
        print_error("为阻止带病上线，部署已中止。可修复后重试，或使用 --skip-tests 显式跳过")
        # 输出失败详情，便于现场定位
        detail = (result.stdout or "")[-3000:]
        for line in detail.splitlines():
            if line.strip():
                print(f"    {line}")
        return False

    DEPLOY_REPORT["tests"]["passed"] = True
    print_success(f"单元测试全部通过：{summary}")
    return True


def _http_get(url, timeout=5):
    """轻量 HTTP GET 探测，返回 (状态码, 错误信息)"""
    try:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "deploy-healthcheck/5.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        # 能拿到 HTTP 状态码说明服务本身在响应（如 307 HTTPS 重定向），视为存活
        return e.code, None
    except Exception as e:
        return None, str(e)


def health_check():
    """部署后健康探测（T-5.2-02）

    依次探测（最多重试 6 次、间隔 5s，覆盖 systemd RestartSec=10 的启动窗口）：
      1. GET /                      —— 前端入口（HTTP 任意响应码即存活）
      2. GET /api/system/ping       —— 无鉴权健康端点（要求 200）
    """
    DEPLOY_REPORT["health_check"]["executed"] = True
    print_info("部署后健康探测：/ 与 /api/system/ping ...")

    server = get_server_config()
    scheme = "https" if (server["ssl_cert"] and server["ssl_key"]) else "http"
    base_url = f"{scheme}://127.0.0.1:{server['port']}"

    probes = [
        {"name": f"GET {scheme}://127.0.0.1:{server['port']}/", "url": f"{base_url}/",
         "expect": "any", "passed": False, "detail": ""},
        {"name": f"GET {scheme}://127.0.0.1:{server['port']}/api/system/ping",
         "url": f"{base_url}/api/system/ping", "expect": 200, "passed": False, "detail": ""},
    ]

    max_attempts, interval = 6, 5
    for attempt in range(1, max_attempts + 1):
        pending = [p for p in probes if not p["passed"]]
        if not pending:
            break
        for probe in pending:
            code, err = _http_get(probe["url"])
            if code is not None and (probe["expect"] == "any" or code == probe["expect"]):
                probe["passed"] = True
                probe["detail"] = f"HTTP {code}"
            else:
                probe["detail"] = f"无响应（{err}）" if code is None else f"HTTP {code}（预期 {probe['expect']})"
        if [p for p in probes if not p["passed"]]:
            if attempt < max_attempts:
                print_info(f"  第 {attempt}/{max_attempts} 次探测未全通过，{interval}s 后重试（等待服务启动）...")
                time.sleep(interval)

    all_passed = all(p["passed"] for p in probes)
    for probe in probes:
        status_icon = "✓" if probe["passed"] else "✗"
        print(f"  {status_icon} {probe['name']} → {probe['detail']}")
        DEPLOY_REPORT["health_check"]["endpoints"].append(
            {"name": probe["name"], "passed": probe["passed"], "detail": probe["detail"]}
        )

    DEPLOY_REPORT["health_check"]["passed"] = all_passed
    if all_passed:
        print_success("健康探测全部通过")
    else:
        print_error("健康探测失败")
    return all_passed


def print_rollback_guide(reason):
    """部署失败时的回滚指引（T-5.2-02）

    项目代码由 git 管理，服务由 systemd 管理：
      - 代码回滚：git reset/checkout 回到上一个可用提交
      - 服务恢复：systemctl restart ros2_web
    """
    print("\n" + "=" * 60)
    print_error(f"部署失败：{reason}")
    print("=" * 60)
    print("回滚步骤：")
    print("  1. 查看部署前最后一个可用提交：")
    print("       git log --oneline -5")
    print("  2. 回滚代码到该提交（保留现场可用 git stash）：")
    print("       git stash && git reset --hard <上一个可用提交>")
    print("  3. 重启服务使旧代码生效：")
    print("       sudo systemctl restart ros2_web")
    print("  4. 验证服务恢复：")
    print(f"       curl -fsS http://127.0.0.1:{get_server_config()['port']}/api/system/ping")
    print("  5. 排查本次失败原因后，修复再重新部署")
    print("=" * 60)


def print_deploy_report():
    print("\n" + "=" * 60)
    print("  部署报告")
    print("=" * 60)

    print("\n【环境检测结果】")
    for key, value in DEPLOY_REPORT["environment"].items():
        key_cn = {
            "python": "Python",
            "pip": "pip",
            "docker": "Docker",
            "git": "Git",
            "service_status": "服务状态",
            "port_status": "端口状态"
        }.get(key, key)
        status_icon = "✓" if value else "✗"
        print(f"  {status_icon} {key_cn}: {value}")

    print("\n【Python 依赖安装报告】")
    print(f"  已安装: {len(DEPLOY_REPORT['python_deps']['already_installed'])} 个")
    print(f"  新安装: {len(DEPLOY_REPORT['python_deps']['newly_installed'])} 个")
    print(f"  安装失败: {len(DEPLOY_REPORT['python_deps']['failed'])} 个")

    if DEPLOY_REPORT["python_deps"]["already_installed"]:
        print("\n  已安装列表:")
        for pkg in DEPLOY_REPORT["python_deps"]["already_installed"]:
            print(f"    ✓ {pkg}")

    if DEPLOY_REPORT["python_deps"]["newly_installed"]:
        print("\n  新安装列表:")
        for pkg in DEPLOY_REPORT["python_deps"]["newly_installed"]:
            print(f"    ✓ {pkg}")

    if DEPLOY_REPORT["python_deps"]["failed"]:
        print("\n  安装失败列表:")
        for pkg in DEPLOY_REPORT["python_deps"]["failed"]:
            print(f"    ✗ {pkg}")

    print("\n【部署前单元测试回归】")
    if DEPLOY_REPORT["tests"]["skipped"]:
        print("  ⚠ 已通过 --skip-tests 显式跳过（留痕）")
    elif DEPLOY_REPORT["tests"]["executed"]:
        status_icon = "✓" if DEPLOY_REPORT["tests"]["passed"] else "✗"
        print(f"  {status_icon} {DEPLOY_REPORT['tests']['summary'] or '（无摘要）'}")
    else:
        print("  - 未执行")

    if DEPLOY_REPORT["health_check"]["executed"]:
        print("\n【部署后健康探测】")
        for ep in DEPLOY_REPORT["health_check"]["endpoints"]:
            status_icon = "✓" if ep["passed"] else "✗"
            print(f"  {status_icon} {ep['name']} → {ep['detail']}")

    print("\n【部署步骤状态】")
    for step in DEPLOY_REPORT["steps"]:
        status = "✓" if step["status"] else "✗"
        print(f"  {status} {step['name']}")

    print("\n" + "=" * 60)
    if DEPLOY_REPORT["status"] == "success":
        print_success("  部署完成！")
    else:
        print_warning("  部署部分完成，请检查上述失败项")
    print("=" * 60)
    print("\n访问地址: http://<服务器IP>:8875")
    print("默认账号: admin / Boonray2020!")
    print("\n注意：Docker 组权限需要重新登录后生效（首次登录后请立即修改默认密码）")


def main():
    parser = argparse.ArgumentParser(description="Mock Truck 管理工具 - 一键部署脚本")
    parser.add_argument("--skip-system", action="store_true",
                        help="跳过系统环境检查与安装（Python/Docker/Git），仅部署应用")
    parser.add_argument("--skip-deps", action="store_true",
                        help="跳过 Python 依赖安装")
    parser.add_argument("--only-deps", action="store_true",
                        help="仅安装 Python 依赖，跳过系统服务部署")
    parser.add_argument("--skip-tests", action="store_true",
                        help="跳过部署前单元测试回归（默认执行，跳过时在日志与部署报告中留痕）")
    args = parser.parse_args()

    print("=" * 60)
    print("  Mock Truck 管理工具 - 一键部署脚本 v5.2")
    print("=" * 60)

    # 非 root 运行时提示 sudo 执行（--only-deps 免 sudo），可选择自动拉起
    ensure_root(args)

    # ---------- 系统环境检测与安装 ----------
    if not args.skip_system:
        print("\n" + "=" * 60)
        print("  第一步：环境检测")
        print("=" * 60)

        checks = [
            ("Python", check_python, install_python),
            ("pip", check_pip, install_python),
            ("Docker", check_docker, install_docker),
            ("Git", check_git, install_git),
        ]

        for name, check_func, install_func in checks:
            if not check_func():
                print_info(f"正在安装 {name}...")
                if not install_func():
                    print_error(f"{name} 安装失败，退出部署")
                    DEPLOY_REPORT["status"] = "failed"
                    DEPLOY_REPORT["steps"].append({"name": f"安装 {name}", "status": False})
                    print_deploy_report()
                    sys.exit(1)
                DEPLOY_REPORT["steps"].append({"name": f"安装 {name}", "status": True})
            else:
                DEPLOY_REPORT["steps"].append({"name": f"检测 {name}", "status": True})
    else:
        print_info("--skip-system 已指定，跳过系统环境检测")
        DEPLOY_REPORT["steps"].append({"name": "跳过系统环境检测", "status": True})

    # ---------- 目录准备 ----------
    print("\n" + "=" * 60)
    print("  第二步：目录准备")
    print("=" * 60)

    create_log_directory()
    create_data_directory()
    move_log_files()
    DEPLOY_REPORT["steps"].append({"name": "目录准备", "status": True})

    # ---------- Python 依赖安装 ----------
    if not args.skip_deps:
        print("\n" + "=" * 60)
        print("  第三步：安装 Python 依赖")
        print("=" * 60)

        if not install_python_dependencies():
            print_error("Python 依赖安装失败")
            DEPLOY_REPORT["status"] = "failed"
            DEPLOY_REPORT["steps"].append({"name": "安装 Python 依赖", "status": False})
            print_deploy_report()
            sys.exit(1)
        DEPLOY_REPORT["steps"].append({"name": "安装 Python 依赖", "status": True})
    else:
        print_info("--skip-deps 已指定，跳过 Python 依赖安装")
        DEPLOY_REPORT["steps"].append({"name": "跳过 Python 依赖安装", "status": True})

    if args.only_deps:
        print_success("仅安装依赖模式完成")
        print_deploy_report()
        return

    # ---------- Docker 权限 ----------
    print("\n" + "=" * 60)
    print("  第四步：配置 Docker 权限")
    print("=" * 60)

    add_user_to_docker_group()
    DEPLOY_REPORT["steps"].append({"name": "配置 Docker 权限", "status": True})

    # ---------- 部署前单元测试回归（v5.2，默认开启） ----------
    print("\n" + "=" * 60)
    print("  第五步：部署前单元测试回归")
    print("=" * 60)

    if args.skip_tests:
        DEPLOY_REPORT["tests"]["skipped"] = True
        print_warning("--skip-tests 已指定，跳过部署前单元测试回归（此跳过行为已在部署报告留痕）")
        DEPLOY_REPORT["steps"].append({"name": "跳过单元测试回归（--skip-tests）", "status": True})
    else:
        if not run_unit_tests():
            print_error("单元测试回归未通过，中止部署（服务仍运行旧代码，无需回滚）")
            DEPLOY_REPORT["status"] = "failed"
            DEPLOY_REPORT["steps"].append({"name": "单元测试回归", "status": False})
            print_deploy_report()
            sys.exit(1)
        DEPLOY_REPORT["steps"].append({"name": "单元测试回归", "status": True})

    # ---------- 系统服务部署 ----------
    print("\n" + "=" * 60)
    print("  第六步：部署系统服务")
    print("=" * 60)

    if not deploy_systemd_service():
        print_error("系统服务部署失败")
        DEPLOY_REPORT["status"] = "failed"
        DEPLOY_REPORT["steps"].append({"name": "部署系统服务", "status": False})
        print_deploy_report()
        sys.exit(1)
    DEPLOY_REPORT["steps"].append({"name": "部署系统服务", "status": True})

    # ---------- 验证 ----------
    print("\n" + "=" * 60)
    print("  第七步：验证服务状态")
    print("=" * 60)

    check_service_status()
    check_port_status()
    DEPLOY_REPORT["steps"].append({"name": "验证服务状态", "status": True})

    # ---------- 部署后健康探测（v5.2） ----------
    print("\n" + "=" * 60)
    print("  第八步：部署后健康探测")
    print("=" * 60)

    if not health_check():
        DEPLOY_REPORT["status"] = "failed"
        DEPLOY_REPORT["steps"].append({"name": "部署后健康探测", "status": False})
        print_rollback_guide("部署后健康探测未通过（/ 或 /api/system/ping 无响应）")
        print_deploy_report()
        sys.exit(1)
    DEPLOY_REPORT["steps"].append({"name": "部署后健康探测", "status": True})

    print_deploy_report()


if __name__ == "__main__":
    main()
