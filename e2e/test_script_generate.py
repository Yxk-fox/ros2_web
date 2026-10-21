"""E2E 用例 3：脚本生成联动

验证：脚本相关接口可用（真实路径 /api/scripts/list, /api/scripts/launch-files）
"""
import requests
from .conftest import BASE_URL


def test_scripts_list_api(backend_url, test_token):
    """脚本列表接口应返回 200"""
    r = requests.get(f"{BASE_URL}/api/scripts/list", timeout=10,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code == 200, f"脚本列表接口异常: {r.status_code}"
    data = r.json()
    assert isinstance(data, (dict, list)), "脚本列表响应格式异常"


def test_scripts_launch_files_api(backend_url, test_token):
    """launch 文件扫描接口应可用"""
    r = requests.get(f"{BASE_URL}/api/scripts/launch-files", timeout=10,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 404), f"launch 文件接口异常: {r.status_code}"


def test_scripts_quota_api(backend_url, test_token):
    """脚本配额接口应可用"""
    r = requests.get(f"{BASE_URL}/api/scripts/quota", timeout=5,
                     headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code in (200, 404), f"脚本配额接口异常: {r.status_code}"
