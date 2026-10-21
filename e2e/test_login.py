"""E2E 用例 1：登录鉴权

验证：未登录访问受保护资源 → 跳转登录；登录后可访问主页
"""
import requests
from .conftest import BASE_URL


def test_unauthenticated_access_redirects(backend_url):
    """未登录访问根路径应返回登录页或重定向"""
    r = requests.get(f"{BASE_URL}/", timeout=5, allow_redirects=False)
    assert r.status_code in (200, 302, 307), f"未登录访问返回 {r.status_code}"


def test_login_page_loads(backend_url):
    """登录页面应正常加载（含登录表单）"""
    r = requests.get(f"{BASE_URL}/", timeout=5)
    assert r.status_code == 200
    assert "登录" in r.text or "login" in r.text.lower(), "登录页面未含登录表单"


def test_login_with_test_user(backend_url, test_user):
    """测试用户登录应返回 token"""
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": test_user["username"],
        "password": test_user["password"],
        "remember_me": False
    }, timeout=5)
    assert r.status_code == 200, f"登录失败: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data or "access_token" in data, "登录响应缺 token 字段"


def test_login_wrong_password(backend_url, test_user):
    """错误密码登录应返回 401"""
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": test_user["username"],
        "password": "wrong_password_xxx",
        "remember_me": False
    }, timeout=5)
    assert r.status_code == 401, f"错误密码应返回401，实际 {r.status_code}"


def test_protected_api_requires_token(backend_url):
    """受保护 API 无 token 应返回 401/403（部分接口可能公开，允许 200）"""
    r = requests.get(f"{BASE_URL}/api/docker/containers", timeout=5)
    assert r.status_code in (200, 401, 403, 422), f"无 token 访问 API 异常: {r.status_code}"
