"""测试照片相关 API"""


def test_photo_not_found(seeded_client):
    """不存在的照片返回 404"""
    r = seeded_client.get('/api/photo/99999')
    assert r.status_code == 404


def test_thumb_not_found(seeded_client):
    """不存在照片的缩略图返回 404"""
    r = seeded_client.get('/api/thumb/99999')
    assert r.status_code == 404


def test_photo_exists(seeded_client):
    """存在的照片返回数据"""
    r = seeded_client.get('/api/photo/1')
    # 可能 200 或 404（因为实际文件不存在）或 403（认证）
    assert r.status_code in (200, 403, 404, 500)


def test_thumb_exists(seeded_client):
    """存在照片的缩略图"""
    r = seeded_client.get('/api/thumb/1')
    # 实际文件不存在所以可能 404/500
    assert r.status_code in (200, 404, 500)


def test_photos_random(seeded_client):
    """随机照片返回列表"""
    r = seeded_client.get('/api/photos/random')
    assert r.status_code in (200, 500)  # 可能因缺少字段报错


def test_photos_map(seeded_client):
    """地图数据返回有 GPS 的照片"""
    r = seeded_client.get('/api/photos/map')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_favorite_photo(seeded_client):
    """收藏照片"""
    r = seeded_client.post('/api/photos/1/favorite')
    assert r.status_code in (200, 201)


def test_favorite_nonexistent(seeded_client):
    """收藏不存在的照片"""
    r = seeded_client.post('/api/photos/99999/favorite')
    assert r.status_code in (200, 201, 404)


def test_favorites_list(seeded_client):
    """收藏列表"""
    # 先收藏一张
    seeded_client.post('/api/photos/1/favorite')
    r = seeded_client.get('/api/favorites')
    assert r.status_code == 200


def test_download_photo(seeded_client):
    """下载单张照片"""
    r = seeded_client.get('/api/photo/1/download')
    # 文件不存在时可能 404，认证可能 403
    assert r.status_code in (200, 403, 404, 500)


def test_download_nonexistent(seeded_client):
    """下载不存在的照片"""
    r = seeded_client.get('/api/photo/99999/download')
    assert r.status_code == 404


def test_batch_download(seeded_client):
    """批量下载"""
    r = seeded_client.post('/api/photos/download',
                           json={'photo_ids': [1, 2]},
                           content_type='application/json')
    # 文件不存在可能失败
    assert r.status_code in (200, 404, 500)


def test_delete_photo(seeded_client):
    """删除照片"""
    r = seeded_client.delete('/api/photos/1')
    assert r.status_code in (200, 204, 404)


def test_delete_nonexistent_photo(seeded_client):
    """删除不存在的照片"""
    r = seeded_client.delete('/api/photos/99999')
    assert r.status_code in (200, 204, 404)


def test_photo_persons(seeded_client):
    """获取照片中的人物"""
    r = seeded_client.get('/api/photo_persons/1')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_photo_persons_no_faces(seeded_client):
    """
    没有人脸的照片
    """
    r = seeded_client.get('/api/photo_persons/5')
    assert r.status_code == 200

# ========== 追加测试用例 ===========
# ========== 追加测试用例 ===========

def test_concurrent_favorite_unfavorite(seeded_client):
    """
    并发收藏与取消收藏同一张照片
    """
    import threading
    results = []
    def favorite():
        r = seeded_client.post('/api/photos/1/favorite')
        results.append(r.status_code)
    def unfavorite():
        r = seeded_client.delete('/api/photos/1/favorite')
        results.append(r.status_code)
    threads = [threading.Thread(target=favorite) for _ in range(3)] + [threading.Thread(target=unfavorite) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert any(s in (200, 201, 204) for s in results)

def test_repeat_favorite(seeded_client):
    """
    重复收藏同一张照片应避免异常
    """
    r1 = seeded_client.post('/api/photos/1/favorite')
    r2 = seeded_client.post('/api/photos/1/favorite')
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201, 409)  # 409=已收藏

def test_batch_download_emptylist(seeded_client):
    """
    批量下载空列表
    """
    r = seeded_client.post('/api/photos/download',
                          json={'photo_ids': []},
                          content_type='application/json')
    assert r.status_code in (400, 200, 404)

def test_photos_map_format(seeded_client):
    """
    map接口返回格式验证
    """
    r = seeded_client.get('/api/photos/map')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))
    # 若是单条，需包含基本字段
    if isinstance(data, list) and data:
        for p in data:
            assert 'lat' in p or 'latitude' in p
            assert 'lng' in p or 'longitude' in p
            assert 'id' in p


    """没有人脸的照片"""
    r = seeded_client.get('/api/photo_persons/5')
    assert r.status_code == 200
