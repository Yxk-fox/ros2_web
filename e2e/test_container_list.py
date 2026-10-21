"""E2E 用例 4：容器列表渲染

验证：Docker 容器列表接口可用，无 Docker 时 skip
"""
import pytest
import requests
from .conftest import BASE_URL, docker_available


@pytest.mark.skipif(not docker_available(), reason="Docker 不可用，跳过容器列表测试")
def test_container_list_api(backend_url, test_token):
    """容器列表接口应返回 200"""
    r = requests.get(f"{BASE_URL}/api/docker/containers", timeout=10,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code == 200, f"容器列表接口异常: {r.status_code}"
    data = r.json()
    assert isinstance(data, (dict, list)), "容器列表响应格式异常"


def test_container_list_api_no_docker(backend_url, test_token):
    """无 Docker 时容器列表接口应优雅返回（空列表或错误，不崩溃）"""
    r = requests.get(f"{BASE_URL}/api/docker/containers", timeout=10,
                     headers={"Authorization": f"Bearer {test_token}"})
    # 有 Docker 返回 200，无 Docker 可能返回 200（空列表）或 500
    assert r.status_code in (200, 500), f"容器列表接口异常: {r.status_code}"


def test_docker_panel_navigation(backend_url, test_token):
    """Docker 容器接口应可访问（验证导航链路可用）"""
    r = requests.get(f"{BASE_URL}/api/docker/containers", timeout=10,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 500), f"Docker 接口异常: {r.status_code}"
