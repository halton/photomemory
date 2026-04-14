"""
db/queries.py
常用SQL查询操作，统计等。
"""
import sqlite3
from typing import Dict

def get_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    返回数据库各类主要对象数量统计。
    返回字段：total/gps/face/persons/duplicate/screenshot
    """
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM photos;").fetchone()[0]
    gps = c.execute("SELECT COUNT(*) FROM photos WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL;").fetchone()[0]
    try:
        face = c.execute("SELECT COUNT(DISTINCT photo_id) FROM faces;").fetchone()[0]
    except sqlite3.OperationalError:
        face = 0
    try:
        persons = c.execute("SELECT COUNT(*) FROM persons;").fetchone()[0]
    except sqlite3.OperationalError:
        persons = 0
    try:
        dupe = c.execute("SELECT COUNT(*) FROM photos WHERE file_hash IN (SELECT file_hash FROM photos GROUP BY file_hash HAVING COUNT(*) > 1);").fetchone()[0]
    except Exception:
        dupe = 0
    try:
        screenshot = c.execute("SELECT COUNT(*) FROM photos WHERE is_screenshot=1;").fetchone()[0]
    except Exception:
        screenshot = 0
    return {
        "total": total,
        "gps": gps,
        "face": face,
        "persons": persons,
        "duplicate": dupe,
        "screenshot": screenshot
    }
