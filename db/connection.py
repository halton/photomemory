"""
db/connection.py
SQLite数据库连接和性能优化相关封装。
"""
import sqlite3
from typing import Optional

def set_sqlite_pragmas(conn: sqlite3.Connection):
    """
    标准化设置SQLite PRAGMA参数，用于性能优化。
    可多次调用，无副作用。
    """
    c = conn.cursor()
    try:
        c.execute('PRAGMA journal_mode=WAL;')
        c.execute('PRAGMA synchronous=NORMAL;')
        c.execute('PRAGMA temp_store=MEMORY;')
        c.execute('PRAGMA cache_size=-20000;')
        c.execute('PRAGMA mmap_size=268435456;')
    except Exception:
        pass

def get_connection(db_path: str, row_factory: Optional[object]=None) -> sqlite3.Connection:
    """
    创建SQLite连接并应用优化参数。
    row_factory: 可选，若设置则自动设置conn.row_factory。
    """
    conn = sqlite3.connect(db_path)
    set_sqlite_pragmas(conn)
    if row_factory:
        conn.row_factory = row_factory
    return conn

# 保留兼容性接口
def get_optimized_connection(db_path: str) -> sqlite3.Connection:
    """
    向后兼容旧接口，等价于get_connection。
    """
    return get_connection(db_path)
