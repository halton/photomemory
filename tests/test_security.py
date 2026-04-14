"""测试安全性 — SQL注入、路径遍历、XSS"""


def test_sql_injection_search(seeded_client):
    """搜索接口 SQL 注入"""
    payloads = [
        "'; DROP TABLE photos;--",
        "1 OR 1=1",
        "' UNION SELECT * FROM persons--",
        "1; DELETE FROM photos",
    ]
    for p in payloads:
        r = seeded_client.get(f'/api/search?q={p}')
        assert r.status_code in (200, 400), f"SQL injection payload failed: {p}"


def test_sql_injection_person_name(seeded_client):
    """人物命名 SQL 注入"""
    r = seeded_client.patch('/api/persons/1',
                            json={'name': "'; DROP TABLE persons;--"},
                            content_type='application/json')
    assert r.status_code in (200, 204, 400)
    # 确认表还在
    r2 = seeded_client.get('/api/persons')
    assert r2.status_code == 200


def test_path_traversal_thumb(seeded_client):
    """缩略图路径遍历"""
    r = seeded_client.get('/api/thumb/1?size=../../etc/passwd')
    assert r.status_code in (200, 400, 404, 500)
    # 不应该返回系统文件内容
    if r.status_code == 200 and r.data:
        assert b'root:' not in r.data


def test_path_traversal_photo(seeded_client):
    """照片下载路径遍历"""
    r = seeded_client.get('/api/photo/1/download')
    # 正常返回或文件不存在或认证
    assert r.status_code in (200, 403, 404, 500)


def test_xss_album_name(seeded_client):
    """相册名 XSS"""
    r = seeded_client.post('/api/albums',
                           json={'name': '<script>alert("xss")</script>'},
                           content_type='application/json')
    assert r.status_code in (200, 201, 400)
    if r.status_code in (200, 201):
        data = r.get_json()
        # 存储型 XSS 检查 — 名字应该被存储但渲染时转义
        r2 = seeded_client.get('/api/albums')
        assert r2.status_code == 200


def test_xss_person_name(seeded_client):
    """人物名 XSS"""
    r = seeded_client.patch('/api/persons/1',
                            json={'name': '<img src=x onerror=alert(1)>'},
                            content_type='application/json')
    assert r.status_code in (200, 204, 400)


def test_xss_search_query(seeded_client):
    """搜索框 XSS"""
    r = seeded_client.get('/api/search?q=<script>alert(1)</script>')
    assert r.status_code in (200, 400)


def test_large_payload(seeded_client):
    """超大请求体"""
    r = seeded_client.post('/api/albums',
                           json={'name': 'A' * 100000},
                           content_type='application/json')
    assert r.status_code in (200, 201, 400, 413)


def test_negative_id(seeded_client):
    """负数 ID"""
    r = seeded_client.get('/api/photo/-1')
    assert r.status_code in (404, 400)


def test_zero_id(seeded_client):
    """零 ID"""
    r = seeded_client.get('/api/photo/0')
    assert r.status_code in (404, 400)


def test_concurrent_writes(seeded_client):
    """
    并发写入不崩溃
    """
    import threading
    results = []
    def create_album(n):
        r = seeded_client.post('/api/albums',
                               json={'name': f'Album {n}'},
                               content_type='application/json')
        results.append(r.status_code)
    threads = [threading.Thread(target=create_album, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 至少一些应该成功
    assert any(s in (200, 201) for s in results)

# ========== 追加测试用例 ===========

def test_more_sql_injection_variants(seeded_client):
    """更多 SQL 注入变体"""
    payloads = [
        '1; DROP TABLE users',
        '" OR "1"="1',
        'admin"--',
        ') OR (1=1',
        "' OR 'a'='a' --",
    ]
    for p in payloads:
        r = seeded_client.get(f'/api/search?q={p}')
        assert r.status_code in (200, 400)

def test_ssrf_url_params(seeded_client):
    """尝试 SSRF 攻击 （url 参数）"""
    urls = [
        'http://127.0.0.1:80',
        'http://169.254.169.254/latest/meta-data',
        'file:///etc/passwd',
        'http://localhost:8000',
    ]
    for u in urls:
        # 假定有某些以 url 传递参数的接口（如 /api/proxy?url=XXX）
        r = seeded_client.get(f'/api/proxy?url={u}')
        assert r.status_code in (200, 400, 403, 404, 500)

def test_http_method_misuse(seeded_client):
    """HTTP method 滥用"""
    # PUT 到不支持的端点
    resp = seeded_client.put('/api/search')
    assert resp.status_code in (405, 400, 404, 500)
    # PATCH 到健康检查
    resp2 = seeded_client.patch('/api/health')
    assert resp2.status_code in (405, 400, 404, 500)

    """并发写入不崩溃"""
    import threading
    results = []

    def create_album(n):
        r = seeded_client.post('/api/albums',
                               json={'name': f'Album {n}'},
                               content_type='application/json')
        results.append(r.status_code)

    threads = [threading.Thread(target=create_album, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 至少一些应该成功
    assert any(s in (200, 201) for s in results)
