import sqlite3

def set_sqlite_pragmas(conn):
    """
    性能优化：统一设置 WAL 模式及核心参数。
    可重复调用，无副作用。
    """
    c = conn.cursor()
    try:
        c.execute('PRAGMA journal_mode=WAL;')
        c.execute('PRAGMA synchronous=NORMAL;')
        c.execute('PRAGMA temp_store=MEMORY;')
        c.execute('PRAGMA cache_size=-20000;')  # ~20MB
        c.execute('PRAGMA mmap_size=268435456;')  # 256MB
    except Exception:
        pass

def get_optimized_connection(db_path):
    conn = sqlite3.connect(db_path)
    set_sqlite_pragmas(conn)
    return conn
