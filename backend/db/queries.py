# 通用数据库查询辅助函数
import sqlite3

def fetch_one(conn, sql, params=()):
    cur = conn.cursor()
    return cur.execute(sql, params).fetchone()

def fetch_all(conn, sql, params=()):
    cur = conn.cursor()
    return cur.execute(sql, params).fetchall()

def execute(conn, sql, params=()):
    cur = conn.cursor()
    result = cur.execute(sql, params)
    conn.commit()
    return result

def executescript(conn, script):
    cur = conn.cursor()
    result = cur.executescript(script)
    conn.commit()
    return result
