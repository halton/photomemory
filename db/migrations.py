"""
db/migrations.py
统一数据库表结构和迁移相关操作。
"""
import sqlite3

CREATE_TABLES_SQL = """
-- Phase 1
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT UNIQUE NOT NULL,
    filename    TEXT,
    size        INTEGER,
    file_hash   TEXT,
    taken_at    TEXT,
    gps_lat     REAL,
    gps_lon     REAL,
    gps_city    TEXT,
    width       INTEGER,
    height      INTEGER,
    is_screenshot INTEGER DEFAULT 0,
    is_duplicate  INTEGER DEFAULT 0,
    duplicate_of  TEXT,
    indexed_at  TEXT,
    dir_label   TEXT
);
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
-- Phase 2 (faces/persons)
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
-- albums/shares/favorites
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
-- 索引
CREATE INDEX IF NOT EXISTS idx_taken_at     ON photos(taken_at);
CREATE INDEX IF NOT EXISTS idx_gps_city     ON photos(gps_city);
CREATE INDEX IF NOT EXISTS idx_hash         ON photos(file_hash);
CREATE INDEX IF NOT EXISTS idx_is_screenshot ON photos(is_screenshot);
CREATE INDEX IF NOT EXISTS idx_persons_id   ON persons(id);
CREATE INDEX IF NOT EXISTS idx_faces_photo   ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person  ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_faces_pid_photo ON faces(person_id, photo_id);
"""

def ensure_tables(conn: sqlite3.Connection):
    """
    创建或升级所有必要表结构。
    """
    conn.executescript(CREATE_TABLES_SQL)
    conn.commit()
