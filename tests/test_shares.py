"""测试分享 API"""


def test_create_share(seeded_client):
    """创建分享链接"""
    r = seeded_client.post('/api/shares',
                           json={'photo_ids': [1, 2]},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_create_share_album(seeded_client):
    """分享整个相册"""
    r = seeded_client.post('/api/shares',
                           json={'album_id': 1},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_create_share_empty(seeded_client):
    """空分享请求"""
    r = seeded_client.post('/api/shares',
                           json={},
                           content_type='application/json')
    assert r.status_code in (200, 201, 400)


def test_access_share(seeded_client):
    """访问分享"""
    # 先创建
    r1 = seeded_client.post('/api/shares',
                            json={'photo_ids': [1]},
                            content_type='application/json')
    if r1.status_code in (200, 201):
        data = r1.get_json()
        share_id = data.get('id') or data.get('share_id')
        if share_id:
            r2 = seeded_client.get(f'/api/shares/{share_id}')
            assert r2.status_code == 200


def test_access_nonexistent_share(seeded_client):
    """访问不存在的分享"""
    r = seeded_client.get('/api/shares/nonexistent-id-xxx')
    assert r.status_code in (404, 410)


def test_share_with_expiry(seeded_client):
    """带过期时间的分享"""
    r = seeded_client.post('/api/shares',
                           json={'photo_ids': [1], 'expires_hours': 24},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_share_single_photo(seeded_client):
    """分享单张照片"""
    r = seeded_client.post('/api/shares',
                           json={'photo_ids': [1]},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_share_invalid_photo(seeded_client):
    """分享不存在的照片"""
    r = seeded_client.post('/api/shares',
                           json={'photo_ids': [99999]},
                           content_type='application/json')
    # 可能成功也可能 404
    assert r.status_code in (200, 201, 400, 404)


def test_share_many_photos(seeded_client):
    """分享多张照片"""
    r = seeded_client.post('/api/shares',
                           json={'photo_ids': [1, 2, 3, 4, 5]},
                           content_type='application/json')
    assert r.status_code in (200, 201)
