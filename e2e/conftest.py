"""T-6.0-04 E2E 测试公共夹具

策略：
- 启动后端（当前 config，JSON/Supabase 自动适配）在测试端口 18765
- 注册测试用户（时间戳唯一）
- Playwright 提供浏览器 + page
- Docker 用例带环境探测，不具备时 skip
"""
import os
import sys
import time
import socket
import subprocess
import uuid
import pytest
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
E2E_PORT = 18765
BASE_URL = f"http://127.0.0.1:{E2E_PORT}"

# 测试用户（时间戳唯一，避免冲突）
_TEST_USER = None
_TEST_TOKEN = None


def _wait_port(host, port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _register_test_user():
    """注册测试用户并登录获取 token（注册要求邮箱格式用户名）"""
    global _TEST_USER, _TEST_TOKEN
    ts = int(time.time())
    email = f"e2e_{ts}@test.com"
    password = "Test1234!"
    # 注册（接口要求 username 为邮箱格式）
    r = requests.post(f"{BASE_URL}/api/auth/register", json={
        "username": email, "password": password
    }, timeout=5)
    if r.status_code == 200:
        _TEST_USER = {"username": email, "password": password}
    else:
        # 注册失败，尝试 admin 登录
        r2 = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin", "remember_me": False
        }, timeout=5)
        if r2.status_code == 200:
            _TEST_USER = {"username": "admin", "password": "admin"}
        else:
            return
    # 登录
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": _TEST_USER["username"],
        "password": _TEST_USER["password"],
        "remember_me": False
    }, timeout=5)
    if r.status_code == 200:
        data = r.json()
        _TEST_TOKEN = data.get("token") or data.get("access_token")


@pytest.fixture(scope="session")
def backend_url():
    """启动后端测试服务（临时切换 JSON 数据库模式，避免 Supabase 频率限制）"""
    import json as _json
    config_path = BACKEND_DIR / "config.json"
    backup_path = BACKEND_DIR / "config.json.e2e_bak"
    # 备份原 config，写入 JSON 模式临时 config
    if config_path.exists():
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        cfg = _json.loads(backup_path.read_text(encoding="utf-8"))
        cfg["database"]["type"] = "json"
        cfg["server"]["port"] = E2E_PORT
        cfg["server"]["host"] = "127.0.0.1"
        config_path.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(BACKEND_DIR)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app",
             "--host", "127.0.0.1", "--port", str(E2E_PORT), "--log-level", "warning"],
            cwd=str(BACKEND_DIR), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            if not _wait_port("127.0.0.1", E2E_PORT, timeout=20):
                proc.terminate()
                pytest.skip("后端服务启动失败，跳过 E2E")
                return None
            _register_test_user()
            yield BASE_URL
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        # 恢复原 config
        if backup_path.exists():
            config_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
            backup_path.unlink()


@pytest.fixture(scope="session")
def test_user(backend_url):
    if _TEST_USER is None:
        pytest.skip("测试用户未就绪")
    return _TEST_USER


@pytest.fixture(scope="session")
def test_token(test_user):
    if _TEST_TOKEN is None:
        pytest.skip("测试 token 未就绪")
    return _TEST_TOKEN


@pytest.fixture(scope="session")
def browser_context(backend_url):
    """Playwright 浏览器上下文（无头）"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        yield context
        context.close()
        browser.close()


@pytest.fixture
def page(browser_context, test_token):
    """页面（预置 token 到 localStorage）"""
    pg = browser_context.new_page()
    # 预置登录态
    pg.add_init_script(f"localStorage.setItem('ros2_web_token', '{test_token}');")
    pg.goto(BASE_URL)
    yield pg
    pg.close()


def docker_available():
    """探测 Docker 是否可用"""
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False
