"""测试搜索建议 API /api/search/suggest"""


def test_empty_query_returns_empty(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=')
    assert r.status_code == 200
    assert r.get_json()["suggestions"] == []


def test_person_name_suggestion(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=Alice')
    assert r.status_code == 200
    data = r.get_json()
    texts = [s["text"] for s in data["suggestions"]]
    assert "Alice" in texts


def test_city_suggestion(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=北京')
    assert r.status_code == 200
    data = r.get_json()
    types = [s["type"] for s in data["suggestions"]]
    assert "city" in types or "folder" in types  # city via alias or folder via directory


def test_like_wildcards_safe(seeded_client):
    """LIKE wildcards (%, _) don't break the query"""
    r1 = seeded_client.get('/api/search/suggest?q=%25')
    assert r1.status_code == 200
    r2 = seeded_client.get('/api/search/suggest?q=_')
    assert r2.status_code == 200


def test_suggestions_deduplicated(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=test')
    assert r.status_code == 200
    data = r.get_json()
    texts = [s["text"] for s in data["suggestions"]]
    assert len(texts) == len(set(texts))


def test_max_10_suggestions(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=a')
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["suggestions"]) <= 10


def test_directory_suggestion(seeded_client):
    r = seeded_client.get('/api/search/suggest?q=/test')
    assert r.status_code == 200
    data = r.get_json()
    folder_suggestions = [s for s in data["suggestions"] if s["type"] == "folder"]
    assert len(folder_suggestions) >= 1
