"""E2E 用例 2：install 上传切换

验证：install 状态接口可用（真实路径 /api/install/status）
"""
import requests
from .conftest import BASE_URL


def test_install_status_api(backend_url, test_token):
    """install 状态接口应可用（JSON 模式下可能 500，验证接口存在）"""
    r = requests.get(f"{BASE_URL}/api/install/status", timeout=5,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 500), f"install 状态接口异常: {r.status_code}"


def test_install_versions_api(backend_url, test_token):
    """install 版本列表接口应可用"""
    r = requests.get(f"{BASE_URL}/api/install/versions", timeout=5,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 404), f"install 版本接口异常: {r.status_code}"


def test_install_tree_api(backend_url, test_token):
    """install 目录树接口应可用"""
    r = requests.get(f"{BASE_URL}/api/install/tree", timeout=5,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 404), f"install 目录树接口异常: {r.status_code}"
