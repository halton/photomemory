import sqlite3
from backend.db_util import get_optimized_connection

DB_PATH = None

def set_db_path(db_path):
    global DB_PATH
    DB_PATH = db_path

def get_db():
    if DB_PATH is None:
        raise RuntimeError("DB_PATH not set. Call set_db_path first.")
    conn = get_optimized_connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

from backend.db_util import set_sqlite_pragmas

def close_db(conn):
    conn.close()
