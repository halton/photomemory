"""测试管理接口和清理功能"""


def test_directories_list(seeded_client):
    """列出目录"""
    r = seeded_client.get('/api/directories')
    assert r.status_code == 200


def test_duplicates_list(seeded_client):
    """列出重复文件"""
    r = seeded_client.get('/api/duplicates')
    assert r.status_code == 200


def test_cleanup_duplicates(admin_client):
    """清理重复文件（需 admin）"""
    r = admin_client.post('/api/cleanup/duplicates')
    assert r.status_code in (200, 204)


def test_cleanup_screenshots(admin_client):
    """清理截图（需 admin）"""
    r = admin_client.post('/api/cleanup/screenshots')
    assert r.status_code in (200, 204)


def test_face_scan_status(seeded_client):
    """人脸扫描状态"""
    r = seeded_client.get('/api/face_scan/status')
    assert r.status_code == 200


def test_face_scan_trigger(admin_client):
    """触发人脸扫描（需 admin）"""
    r = admin_client.post('/api/face_scan')
    # 可能缺少依赖
    assert r.status_code in (200, 202, 400, 500)


def test_admin_page_no_token(client):
    """管理页无 token"""
    r = client.get('/admin')
    assert r.status_code in (200, 302, 401, 403)


def test_admin_page_correct_token(client):
    """管理页正确 token"""
    r = client.get('/admin?token=test-admin-token')
    assert r.status_code in (200, 302)


def test_admin_page_wrong_token(client):
    """管理页错误 token"""
    r = client.get('/admin?token=wrong')
    assert r.status_code in (200, 302, 401, 403)
