# 数据库建表和迁移逻辑
from backend.db.connection import get_db

INIT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS faces (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        photo_id    INTEGER,
        photo_path  TEXT,
        bbox        TEXT,
        landmark    TEXT,
        det_score   REAL,
        embedding   BLOB,
        person_id   INTEGER,
        detected_at TEXT
    );
    CREATE TABLE IF NOT EXISTS persons (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT,
        alias       TEXT,
        embedding_centroid BLOB,
        face_count  INTEGER DEFAULT 0,
        created_at  TEXT,
        updated_at  TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_persons_id ON persons(id);
    CREATE TABLE IF NOT EXISTS directories (
        path TEXT PRIMARY KEY,
        label TEXT,
        file_count INTEGER DEFAULT 0,
        last_scan TEXT
    );
    CREATE TABLE IF NOT EXISTS duplicate_groups (
        hash TEXT PRIMARY KEY,
        paths TEXT,
        count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS albums (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        cover_photo_id INTEGER,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS album_photos (
        album_id INTEGER NOT NULL,
        photo_id INTEGER NOT NULL,
        sort_order INTEGER DEFAULT 0,
        PRIMARY KEY (album_id, photo_id)
    );
    CREATE TABLE IF NOT EXISTS shares (
        id TEXT PRIMARY KEY,
        album_id INTEGER,
        photo_ids TEXT,
        expires_at TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS favorites (
        photo_id INTEGER PRIMARY KEY,
        created_at TEXT
    );
"""

# FTS5 全文搜索虚拟表（用于 filename、gps_city、directory 联合搜索）
FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
        filename,
        gps_city,
        directory,
        content='photos',
        content_rowid='id'
    );
"""

# 索引优化
INDEXES_SCHEMA = """
    CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photos(taken_at);
    CREATE INDEX IF NOT EXISTS idx_photos_gps_city ON photos(gps_city);
    CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces(person_id);
    CREATE INDEX IF NOT EXISTS idx_faces_photo_id ON faces(photo_id);
    CREATE INDEX IF NOT EXISTS idx_faces_photo_path ON faces(photo_path);
    CREATE INDEX IF NOT EXISTS idx_album_photos_photo ON album_photos(photo_id);
"""


def ensure_tables():
    conn = get_db()
    conn.executescript(INIT_SCHEMA)
    # FTS5 — silently skip if photos table doesn't exist yet
    try:
        conn.executescript(FTS_SCHEMA)
    except Exception:
        pass
    try:
        conn.executescript(INDEXES_SCHEMA)
    except Exception:
        pass
    conn.close()


def rebuild_fts():
    """重建 FTS5 索引（全量同步 photos 表内容）"""
    conn = get_db()
    try:
        conn.executescript(FTS_SCHEMA)
        conn.execute("DELETE FROM photos_fts")
        conn.execute("""
            INSERT INTO photos_fts(rowid, filename, gps_city, directory)
            SELECT id, filename, gps_city, directory FROM photos
        """)
        conn.commit()
    finally:
        conn.close()
