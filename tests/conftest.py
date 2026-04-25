"""
PhotoMemory 测试基础设施
使用真实 Flask test_client + 临时 SQLite DB，不 mock 服务层
"""
import os
import sys
import tempfile
import pytest

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# photos 表的 DDL（phase1 创建的，ensure_tables 不包含）
PHOTOS_DDL = """
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE,
    filename TEXT,
    directory TEXT,
    size INTEGER,
    width INTEGER,
    height INTEGER,
    format TEXT,
    taken_at TEXT,
    gps_lat REAL,
    gps_lon REAL,
    gps_city TEXT,
    camera_make TEXT,
    camera_model TEXT,
    md5 TEXT,
    is_screenshot INTEGER DEFAULT 0,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_group TEXT,
    indexed_at TEXT,
    file_type TEXT DEFAULT 'image',
    owner TEXT DEFAULT NULL
)
"""


@pytest.fixture(scope='function')
def app_with_db():
    """创建带临时数据库的 Flask app，每个测试函数独立"""
    from backend.db import set_db_path, ensure_tables, get_db
    import backend.auth.middleware as auth_mw

    # 创建临时数据库
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)

    set_db_path(db_path)
    ensure_tables()

    # 创建 photos 表
    db = get_db()
    db.execute(PHOTOS_DDL)
    db.commit()

    # 禁用认证
    auth_mw.PAIRING_ENABLED = False
    auth_mw.ADMIN_TOKEN = 'test-admin-token'

    from backend.api_server import app
    import backend.api_server as api_mod
    api_mod.DB_PATH = db_path
    app.config['TESTING'] = True

    yield app

    try:
        db = get_db()
        db.close()
    except Exception:
        pass
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client(app_with_db):
    """Flask test client"""
    return app_with_db.test_client()


@pytest.fixture
def db(app_with_db):
    """直接访问数据库连接"""
    from backend.db import get_db
    return get_db()


@pytest.fixture
def seeded_db(db):
    """插入测试数据的数据库"""
    # 插入测试目录
    db.execute("""
        INSERT INTO directories (path, label, file_count, last_scan)
        VALUES ('/test/photos', 'Test Photos', 5, '2026-01-01 00:00:00')
    """)

    # 插入测试照片
    for i in range(1, 6):
        db.execute("""
            INSERT INTO photos (path, filename, directory, size, width, height,
                format, taken_at, gps_lat, gps_lon, gps_city, is_screenshot, is_duplicate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f'/test/photos/img_{i}.jpg', f'img_{i}.jpg', '/test/photos',
            1024 * i, 1920, 1080, 'JPEG',
            f'2026-01-{i:02d} 12:00:00',
            39.9 + i * 0.01, 116.3 + i * 0.01,
            '北京' if i <= 3 else '上海',
            0, 0
        ))

    # 插入测试人物
    db.execute("""
        INSERT INTO persons (id, name, face_count, created_at, updated_at)
        VALUES (1, 'Alice', 3, '2026-01-01', '2026-01-01')
    """)
    db.execute("""
        INSERT INTO persons (id, name, face_count, created_at, updated_at)
        VALUES (2, NULL, 2, '2026-01-01', '2026-01-01')
    """)

    # 插入测试人脸
    for i in range(1, 4):
        db.execute("""
            INSERT INTO faces (photo_id, photo_path, det_score, person_id, detected_at)
            VALUES (?, ?, ?, ?, ?)
        """, (i, f'/test/photos/img_{i}.jpg', 0.95, 1, '2026-01-01'))

    # 插入测试相册
    db.execute("""
        INSERT INTO albums (id, name, description, created_at, updated_at)
        VALUES (1, 'Test Album', 'A test album', '2026-01-01', '2026-01-01')
    """)
    db.execute("""
        INSERT INTO album_photos (album_id, photo_id, sort_order)
        VALUES (1, 1, 0), (1, 2, 1)
    """)

    db.commit()
    return db


@pytest.fixture
def seeded_client(app_with_db, seeded_db):
    """带测试数据的 Flask test client"""
    return app_with_db.test_client()


@pytest.fixture
def admin_client(app_with_db, seeded_db):
    """带 admin token 的 test client"""
    import backend.auth.middleware as auth_mw
    import backend.api_server as api_mod
    auth_mw.ADMIN_TOKEN = 'test-admin-token'
    api_mod.ADMIN_TOKEN = 'test-admin-token'

    class AdminClient:
        def __init__(self, c):
            self._c = c
            self._headers = {'Authorization': 'Bearer test-admin-token'}

        def get(self, *a, **kw):
            kw.setdefault('headers', {}).update(self._headers)
            return self._c.get(*a, **kw)

        def post(self, *a, **kw):
            kw.setdefault('headers', {}).update(self._headers)
            return self._c.post(*a, **kw)

        def delete(self, *a, **kw):
            kw.setdefault('headers', {}).update(self._headers)
            return self._c.delete(*a, **kw)

        def patch(self, *a, **kw):
            kw.setdefault('headers', {}).update(self._headers)
            return self._c.patch(*a, **kw)

    return AdminClient(app_with_db.test_client())
