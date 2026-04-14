#!/usr/bin/env python3
"""
PhotoMemory - 简洁统计工具
"""
import os
import sys
import argparse
import sqlite3
import json

def get_db_path():
    return os.environ.get("PM_DB", "/tmp/photomemory_test.db")

def get_counts(conn):
    # 照片总数
    cur = conn.execute("SELECT COUNT(*) FROM photos;")
    total = cur.fetchone()[0]

    # 有 GPS 的照片数
    gps = conn.execute("SELECT COUNT(*) FROM photos WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL;").fetchone()[0]

    # 有人脸识别的照片数
    try:
        face = conn.execute("SELECT COUNT(DISTINCT photo_id) FROM faces;").fetchone()[0]
    except sqlite3.OperationalError:
        face = 0

    # 人物总数
    try:
        persons = conn.execute("SELECT COUNT(*) FROM persons;").fetchone()[0]
    except sqlite3.OperationalError:
        persons = 0

    # 重复照片数
    try:
        dupe = conn.execute("SELECT COUNT(*) FROM photos WHERE file_hash IN (SELECT file_hash FROM photos GROUP BY file_hash HAVING COUNT(*) > 1);").fetchone()[0]
    except Exception:
        dupe = 0

    # 截图数
    try:
        screenshot = conn.execute("SELECT COUNT(*) FROM photos WHERE is_screenshot=1;").fetchone()[0]
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

def main():
    parser = argparse.ArgumentParser(description="PhotoMemory Stats")
    parser.add_argument('--db', type=str, help='数据库路径 (默认 $PM_DB 或 /tmp/photomemory_test.db)')
    parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    args = parser.parse_args()
    db_path = args.db or get_db_path()

    if not os.path.isfile(db_path):
        print(f"未找到数据库文件: {db_path}")
        sys.exit(1)
    from backend.db_util import get_optimized_connection
    conn = get_optimized_connection(db_path)
    counts = get_counts(conn)
    if args.json:
        print(json.dumps(counts, ensure_ascii=False, indent=2))
    else:
        print(f"照片总数    : {counts['total']}")
        print(f"有GPS照片数 : {counts['gps']}")
        print(f"人脸识别照片 : {counts['face']}")
        print(f"人物数      : {counts['persons']}")
        print(f"重复照片数  : {counts['duplicate']}")
        print(f"截图数      : {counts['screenshot']}")

if __name__ == "__main__":
    main()
