# 数据库建表和迁移逻辑
import sqlite3
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

def ensure_tables():
    conn = get_db()
    conn.executescript(INIT_SCHEMA)
    conn.close()

# 可后续扩展 migration 体系，现只负责初始建表