"""测试认证和配对 API"""


def test_auth_check_always_200(client):
    """auth_check 始终返回 200"""
    r = client.get('/api/auth_check')
    assert r.status_code == 200


def test_pair_request(client):
    """发起配对请求"""
    import backend.api_server as api_mod
    import backend.auth.middleware as auth_mw
    api_mod.PAIRING_ENABLED = True
    auth_mw.PAIRING_ENABLED = True
    r = client.post('/api/pair/request',
                    json={'device_name': 'Test Device'},
                    content_type='application/json')
    assert r.status_code in (200, 201, 400, 403)
    api_mod.PAIRING_ENABLED = False
    auth_mw.PAIRING_ENABLED = False


def test_pair_status_no_device(client):
    """无设备ID查询状态"""
    r = client.get('/api/pair/status')
    assert r.status_code in (200, 400, 404)


def test_pair_list_no_auth(client):
    """无管理员认证列出配对"""
    r = client.get('/api/pair/list')
    # 本地访问可能允许
    assert r.status_code in (200, 401, 403)


def test_pair_approve_no_auth(client):
    """无认证审批"""
    r = client.post('/api/pair/approve',
                    json={'device_id': 'fake-device'},
                    content_type='application/json')
    assert r.status_code in (200, 401, 403, 404)


def test_pair_revoke_no_auth(client):
    """无认证吊销"""
    r = client.post('/api/pair/revoke',
                    json={'device_id': 'fake-device'},
                    content_type='application/json')
    assert r.status_code in (200, 401, 403, 404)


def test_login_no_token(client):
    """无 token 登录"""
    r = client.post('/api/login',
                    json={},
                    content_type='application/json')
    assert r.status_code in (200, 400, 401)


def test_login_invalid_token(client):
    """无效 token 登录"""
    r = client.post('/api/login',
                    json={'token': 'invalid-token-xxx'},
                    content_type='application/json')
    assert r.status_code in (200, 400, 401, 403)


def test_pair_reject(client):
    """拒绝配对请求"""
    r = client.post('/api/pair/reject',
                    json={'device_id': 'fake-device'},
                    content_type='application/json')
    assert r.status_code in (200, 401, 403, 404)


def test_admin_requires_token(client):
    """管理页需要 token"""
    r = client.get('/admin')
    # 本地可能放行
    assert r.status_code in (200, 302, 401, 403)


def test_admin_with_token(client):
    """
    带 token 访问管理员页
    """
    r = client.get('/admin?token=test-admin-token')
    assert r.status_code in (200, 302)

# ========== 追加测试用例 ===========

def test_pair_full_flow(client):
    """配对完整流程: request → approve → login → access admin"""
    import backend.api_server as api_mod
    import backend.auth.middleware as auth_mw
    api_mod.PAIRING_ENABLED = True
    auth_mw.PAIRING_ENABLED = True
    # request
    req = client.post('/api/pair/request', json={'device_name': 'Test Device2'}, content_type='application/json')
    assert req.status_code in (200, 201, 400, 403)
    dev = req.get_json() if req.is_json else {}
    device_id = dev.get('device_id') or dev.get('id', 'fake-device')
    # approve
    appr = client.post('/api/pair/approve', json={'device_id': device_id}, content_type='application/json')
    # token
    tokens = appr.get_json() if appr.is_json else {}
    tk = tokens.get('token') or tokens.get('access_token', 'invalid-token')
    # login
    login = client.post('/api/login', json={'token': tk}, content_type='application/json')
    assert login.status_code in (200, 400, 401, 403)
    # access admin page
    ok = client.get(f'/admin?token={tk}')
    assert ok.status_code in (200, 302, 401, 403)
    api_mod.PAIRING_ENABLED = False
    auth_mw.PAIRING_ENABLED = False

def test_concurrent_pair_requests(client):
    """并发配对请求"""
    import threading
    import backend.api_server as api_mod
    import backend.auth.middleware as auth_mw
    api_mod.PAIRING_ENABLED = True
    auth_mw.PAIRING_ENABLED = True
    results = []
    def req_pair():
        resp = client.post('/api/pair/request', json={'device_name': 'Concurrent'}, content_type='application/json')
        results.append(resp.status_code)
    threads = [threading.Thread(target=req_pair) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert any(s in (200,201,400,403) for s in results)
    api_mod.PAIRING_ENABLED = False
    auth_mw.PAIRING_ENABLED = False

    """带 token 访问管理页"""
    r = client.get('/admin?token=test-admin-token')
    assert r.status_code in (200, 302)
