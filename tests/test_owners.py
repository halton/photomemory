"""测试 owner API 及搜索 owner 过滤"""


def test_owners_endpoint(seeded_client, seeded_db):
    """/api/owners 应返回 owner 列表"""
    # 插入带 owner 的照片
    seeded_db.execute(
        "UPDATE photos SET owner = 'halton' WHERE id IN (1, 2, 3)"
    )
    seeded_db.execute(
        "UPDATE photos SET owner = 'lxn' WHERE id IN (4, 5)"
    )
    seeded_db.commit()
    r = seeded_client.get('/api/owners')
    assert r.status_code == 200
    data = r.get_json()
    assert 'owners' in data
    owners = {o['owner']: o['photo_count'] for o in data['owners']}
    assert owners['halton'] == 3
    assert owners['lxn'] == 2


def test_search_by_owner(seeded_client, seeded_db):
    """搜索应支持 owner 过滤"""
    seeded_db.execute("UPDATE photos SET owner = 'halton' WHERE id IN (1, 2, 3)")
    seeded_db.execute("UPDATE photos SET owner = 'lxn' WHERE id IN (4, 5)")
    seeded_db.commit()
    r = seeded_client.get('/api/search?owner=halton&exclude_screenshots=0')
    assert r.status_code == 200
    data = r.get_json()
    assert data['total'] == 3


def test_search_without_owner(seeded_client, seeded_db):
    """不传 owner 参数应返回所有照片"""
    seeded_db.execute("UPDATE photos SET owner = 'halton' WHERE id IN (1, 2, 3)")
    seeded_db.commit()
    r = seeded_client.get('/api/search?exclude_screenshots=0')
    assert r.status_code == 200
    data = r.get_json()
    assert data['total'] == 5
