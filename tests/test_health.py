"""测试 /api/health 和基本连通性"""


def test_health_endpoint(client):
    """健康检查端点返回 200"""
    r = client.get('/api/health')
    assert r.status_code == 200


def test_health_json(client):
    """健康检查返回 JSON 格式"""
    r = client.get('/api/health')
    data = r.get_json()
    assert data is not None
    assert 'status' in data or isinstance(data, dict)


def test_root_page(client):
    """根路径返回 HTML 页面"""
    r = client.get('/')
    assert r.status_code == 200


def test_auth_check(client):
    """auth_check 端点始终返回 200"""
    r = client.get('/api/auth_check')
    assert r.status_code == 200


def test_404_nonexistent(client):
    """不存在的路径返回 404"""
    r = client.get('/api/this_does_not_exist')
    assert r.status_code == 404
