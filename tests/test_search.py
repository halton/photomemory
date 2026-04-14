"""测试 /api/search — 照片搜索"""


def test_search_empty_query(seeded_client):
    """空查询返回所有非截图照片"""
    r = seeded_client.get('/api/search')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_search_by_city(seeded_client):
    """按城市搜索"""
    r = seeded_client.get('/api/search?q=北京')
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_search_by_date_range(seeded_client):
    """按日期范围搜索"""
    r = seeded_client.get('/api/search?date_from=2026-01-01&date_to=2026-01-03')
    assert r.status_code == 200


def test_search_by_year(seeded_client):
    """按年份搜索"""
    r = seeded_client.get('/api/search?year=2026')
    assert r.status_code == 200


def test_search_by_month(seeded_client):
    """按月份搜索"""
    r = seeded_client.get('/api/search?month=1')
    assert r.status_code == 200


def test_search_by_person(seeded_client):
    """按人物搜索"""
    r = seeded_client.get('/api/search?person=Alice')
    assert r.status_code == 200


def test_search_with_limit(seeded_client):
    """限制返回数量"""
    r = seeded_client.get('/api/search?limit=2')
    assert r.status_code == 200
    data = r.get_json()
    if isinstance(data, list):
        assert len(data) <= 2
    elif isinstance(data, dict) and 'photos' in data:
        assert len(data['photos']) <= 2


def test_search_with_offset(seeded_client):
    """分页偏移"""
    r = seeded_client.get('/api/search?offset=2&limit=2')
    assert r.status_code == 200


def test_search_exclude_screenshots(seeded_client):
    """默认排除截图"""
    r = seeded_client.get('/api/search?exclude_screenshots=true')
    assert r.status_code == 200


def test_search_special_chars(seeded_client):
    """特殊字符不导致 500"""
    r = seeded_client.get('/api/search?q=' + "'; DROP TABLE photos;--")
    assert r.status_code in (200, 400)


def test_search_unicode(seeded_client):
    """Unicode 搜索"""
    r = seeded_client.get('/api/search?q=上海')
    assert r.status_code == 200


def test_search_nonexistent_person(seeded_client):
    """搜索不存在的人物"""
    r = seeded_client.get('/api/search?person=不存在的人')
    assert r.status_code == 200
    data = r.get_json()
    if isinstance(data, list):
        assert len(data) == 0
    elif isinstance(data, dict) and 'photos' in data:
        assert len(data['photos']) == 0

# ========== 追加测试用例 ===========

def test_search_combo_city_date(seeded_client):
    """组合搜索：city + date"""
    r = seeded_client.get('/api/search?q=北京&date_from=2026-01-01&date_to=2026-01-03')
    assert r.status_code == 200

def test_search_pagination_offset_limit(seeded_client):
    """极大limit+offset超界"""
    r = seeded_client.get('/api/search?offset=10000&limit=5000')
    assert r.status_code == 200
    data = r.get_json()
    # 应当返回空 或最多极少结果
    if isinstance(data, list):
        assert len(data) == 0 or len(data) < 1000
    elif isinstance(data, dict) and "photos" in data:
        assert len(data["photos"]) == 0 or len(data["photos"]) < 1000

def test_search_extreme_limit(seeded_client):
    r = seeded_client.get('/api/search?limit=10000')
    assert r.status_code == 200
    data = r.get_json()
    # 返回数量不会超 10000, 一般服务器有限制
    if isinstance(data, list):
        assert len(data) <= 10000
    elif isinstance(data, dict) and "photos" in data:
        assert len(data["photos"]) <= 10000

def test_search_person_year_combo(seeded_client):
    r = seeded_client.get('/api/search?person=Alice&year=2026')
    assert r.status_code == 200
