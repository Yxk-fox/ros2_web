#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
版权所有：上海伯镭科技有限公司
@File    :  deploy.py
@Time    :  2026/07/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  ROS2 Web 管理工具 - 一键部署脚本（解耦优化版）
            包含：环境检测、依赖安装、服务部署、自启动配置
            优化：已安装环境自动跳过，支持 --skip-system 快速部署
"""

import os
import sys
import subprocess
import shutil
import platform
import re
import argparse

DEPLOY_REPORT = {
    "environment": {},
    "python_deps": {
        "already_installed": [],
        "newly_installed": [],
        "failed": []
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


def add_user_to_docker_group():
    print_info("将当前用户添加到 docker 组...")
    user = os.environ.get("SUDO_USER", os.getlogin())
    rc, out, err = run_cmd(["usermod", "-aG", "docker", user], sudo=True)
    if rc == 0:
        print_success(f"用户 {user} 已添加到 docker 组")
        return True
    print_error(f"添加失败: {err}")
    return False


def deploy_systemd_service():
    print_info("部署 systemd 服务...")
    target_path = "/etc/systemd/system/ros2_web.service"

    project_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(project_dir, "backend")
    current_user = os.environ.get("SUDO_USER", os.getlogin())
    user_home = os.path.expanduser(f"~{current_user}")
    python3_path = shutil.which("python3") or "/usr/bin/python3"

    service_content = f"""[Unit]
Description=ROS2 Web Manager Service (Decoupled)
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

    rc, out, err = run_cmd(["systemctl", "start", "ros2_web"], sudo=True)
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
    print("默认账号: admin / 123456")
    print("\n注意：Docker 组权限需要重新登录后生效")


def main():
    parser = argparse.ArgumentParser(description="ROS2 Web 管理工具 - 一键部署脚本")
    parser.add_argument("--skip-system", action="store_true",
                        help="跳过系统环境检查与安装（Python/Docker/Git），仅部署应用")
    parser.add_argument("--skip-deps", action="store_true",
                        help="跳过 Python 依赖安装")
    parser.add_argument("--only-deps", action="store_true",
                        help="仅安装 Python 依赖，跳过系统服务部署")
    args = parser.parse_args()

    print("=" * 60)
    print("  ROS2 Web 管理工具 - 一键部署脚本 v4.0-decoupled")
    print("=" * 60)

    if os.geteuid() != 0 and not args.only_deps:
        print_error("需要以 root 权限运行，请使用 sudo")
        sys.exit(1)

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

    # ---------- 系统服务部署 ----------
    print("\n" + "=" * 60)
    print("  第五步：部署系统服务")
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
    print("  第六步：验证服务状态")
    print("=" * 60)

    check_service_status()
    check_port_status()
    DEPLOY_REPORT["steps"].append({"name": "验证服务状态", "status": True})

    print_deploy_report()


if __name__ == "__main__":
    main()
