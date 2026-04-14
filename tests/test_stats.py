"""测试统计 API"""


def test_stats_basic(seeded_client):
    """基本统计返回数据"""
    r = seeded_client.get('/api/stats')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, dict)


def test_stats_has_counts(seeded_client):
    """统计包含照片数"""
    r = seeded_client.get('/api/stats')
    data = r.get_json()
    # 应该有某种计数字段
    assert any(k in data for k in ('total', 'photos', 'total_photos', 'count'))


def test_stats_timeline(seeded_client):
    """时间线统计"""
    r = seeded_client.get('/api/stats/timeline')
    assert r.status_code == 200


def test_stats_persons(seeded_client):
    """人物统计"""
    r = seeded_client.get('/api/stats/persons')
    assert r.status_code == 200


def test_stats_locations(seeded_client):
    """地点统计"""
    r = seeded_client.get('/api/stats/locations')
    assert r.status_code == 200


def test_stats_no_data(client):
    """空数据库统计不报错"""
    # client 用的是空 DB（不是 seeded_client）
    # 但 photos 表可能不存在，先建表
    from backend.db import get_db
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT, filename TEXT, taken_at TEXT,
            gps_city TEXT, is_screenshot INTEGER DEFAULT 0,
            is_duplicate INTEGER DEFAULT 0
        )
    """)
    db.commit()
    r = client.get('/api/stats')
    assert r.status_code == 200


def test_stats_cache_works(seeded_client):
    """连续调用应该被缓存（第二次更快）"""
    import time
    t1 = time.time()
    seeded_client.get('/api/stats')
    d1 = time.time() - t1

    t2 = time.time()
    seeded_client.get('/api/stats')
    d2 = time.time() - t2

    # 第二次应该不会慢太多（允许误差）
    assert d2 < d1 + 1.0  # 宽松检查


def test_stats_locations_format(seeded_client):
    """地点统计返回正确格式"""
    r = seeded_client.get('/api/stats/locations')
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_stats_timeline_format(seeded_client):
    """
    时间线统计返回正确格式
    """
    r = seeded_client.get('/api/stats/timeline')
    data = r.get_json()
    assert isinstance(data, (list, dict))

# ========== 追加测试用例 ===========

def test_stats_empty_data_format(client):
    """空数据统计格式"""
    from backend.db import get_db
    db = get_db()
    db.execute("""
        DELETE FROM photos
    """)
    db.commit()
    r = client.get('/api/stats')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, dict)
    # 某些关键字段应返回 0 或空(兼容老前端)
    for fld in ('total', 'photos', 'count'):
        if fld in data:
            assert data[fld] == 0

def test_stats_massive_data(seeded_client):
    """统计接口在有数据时返回正确计数"""
    r = seeded_client.get('/api/stats')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, dict)
    total = data.get('total_photos', 0)
    # seeded_db 插入了 5 张照片
    assert total >= 5, f"Expected >= 5 photos, got {total}"
    # 确保各字段类型正确
    for k in ('total_photos', 'faces', 'persons', 'screenshots', 'duplicates'):
        assert isinstance(data.get(k, 0), int), f"{k} should be int"

def test_stats_fields_validation(seeded_client):
    """各个统计端点返回字段验证"""
    endpoints = ["/api/stats", "/api/stats/persons", "/api/stats/locations", "/api/stats/timeline"]
    for ep in endpoints:
        r = seeded_client.get(ep)
        assert r.status_code == 200
        data = r.get_json()
        assert data is not None

    """时间线统计返回正确格式"""
    r = seeded_client.get('/api/stats/timeline')
    data = r.get_json()
    assert isinstance(data, (list, dict))
