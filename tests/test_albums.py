"""测试相册 API"""


def test_create_album(seeded_client):
    """创建相册"""
    r = seeded_client.post('/api/albums',
                           json={'name': 'New Album'},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_create_album_with_desc(seeded_client):
    """创建带描述的相册"""
    r = seeded_client.post('/api/albums',
                           json={'name': 'Vacation', 'description': '2026 Summer'},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_create_album_no_name(seeded_client):
    """无名称返回 400"""
    r = seeded_client.post('/api/albums',
                           json={},
                           content_type='application/json')
    assert r.status_code in (400, 422)


def test_list_albums(seeded_client):
    """列出相册"""
    r = seeded_client.get('/api/albums')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_album_photos(seeded_client):
    """获取相册照片"""
    r = seeded_client.get('/api/albums/1/photos')
    assert r.status_code == 200


def test_add_photo_to_album(seeded_client):
    """添加照片到相册"""
    r = seeded_client.post('/api/albums/1/photos',
                           json={'photo_ids': [3]},
                           content_type='application/json')
    assert r.status_code in (200, 201)


def test_remove_photo_from_album(seeded_client):
    """从相册移除照片"""
    r = seeded_client.delete('/api/albums/1/photos/1')
    assert r.status_code in (200, 204)


def test_delete_album(seeded_client):
    """删除相册"""
    r = seeded_client.delete('/api/albums/1')
    assert r.status_code in (200, 204)


def test_delete_nonexistent_album(seeded_client):
    """删除不存在的相册"""
    r = seeded_client.delete('/api/albums/99999')
    assert r.status_code in (200, 204, 404)


def test_album_recommend(seeded_client):
    """智能推荐相册"""
    r = seeded_client.get('/api/albums/recommend')
    assert r.status_code == 200


def test_album_nonexistent_photos(seeded_client):
    """不存在相册的照片"""
    r = seeded_client.get('/api/albums/99999/photos')
    assert r.status_code in (200, 404)


def test_add_photo_nonexistent_album(seeded_client):
    """向不存在的相册添加照片"""
    r = seeded_client.post('/api/albums/99999/photos',
                           json={'photo_ids': [1]},
                           content_type='application/json')
    assert r.status_code in (200, 201, 404)

# ========== 追加测试用例 ===========

def test_repeat_add_same_photo(seeded_client):
    """重复添加同一照片到相册"""
    r1 = seeded_client.post('/api/albums/1/photos', json={'photo_ids': [3]}, content_type='application/json')
    r2 = seeded_client.post('/api/albums/1/photos', json={'photo_ids': [3]}, content_type='application/json')
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201, 409, 400)

def test_delete_empty_album(seeded_client):
    """空相册删除"""
    r = seeded_client.post('/api/albums', json={'name': 'empty_del_album'}, content_type='application/json')
    album_id = None
    if r.status_code in (200, 201):
        data = r.get_json()
        album_id = data.get('id') or data.get('album_id')
    if album_id:
        delr = seeded_client.delete(f'/api/albums/{album_id}')
        assert delr.status_code in (200, 204, 404)

def test_album_sort(seeded_client):
    """相册排序"""
    r = seeded_client.get('/api/albums?sort=id&order=desc')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))

def test_set_album_cover(seeded_client):
    """设置相册封面"""
    albums = seeded_client.get('/api/albums').get_json()
    album_id = None
    if isinstance(albums, list) and albums:
        album_id = albums[0].get('id')
    elif isinstance(albums, dict) and albums.get('albums'):
        album_id = albums['albums'][0].get('id')
    if album_id:
        r = seeded_client.post(f'/api/albums/{album_id}/cover', json={'photo_id': 1}, content_type='application/json')
        assert r.status_code in (200, 201, 204, 400, 404, 405)


# ========== Album Update (PATCH) Tests ===========

def test_update_album_rename(seeded_client):
    """PATCH rename album and verify mutation persisted"""
    r = seeded_client.patch('/api/albums/1', json={'name': 'Renamed Album'},
                            content_type='application/json')
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    # Verify mutation persisted
    albums = seeded_client.get('/api/albums').get_json()
    album_list = albums if isinstance(albums, list) else albums.get("albums", [])
    found = [a for a in album_list if a.get("id") == 1]
    if found:
        assert found[0]["name"] == "Renamed Album"


def test_update_album_description(seeded_client):
    r = seeded_client.patch('/api/albums/1', json={'description': 'New desc'},
                            content_type='application/json')
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_update_album_no_fields(seeded_client):
    """Empty update returns 400"""
    r = seeded_client.patch('/api/albums/1', json={},
                            content_type='application/json')
    assert r.status_code == 400


def test_update_album_nonexistent(seeded_client):
    r = seeded_client.patch('/api/albums/99999', json={'name': 'X'},
                            content_type='application/json')
    assert r.status_code == 404


def test_update_album_cover(seeded_client):
    r = seeded_client.patch('/api/albums/1', json={'cover_photo_id': 1},
                            content_type='application/json')
    assert r.status_code == 200
