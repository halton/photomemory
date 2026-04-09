#!/usr/bin/env python3
"""
PhotoMemory - 逆地理编码批处理脚本（修复 gps_city 为空项，支持 --dry-run）
用法：python3 backfill_geocode.py --db /tmp/photomemory.db [--dry-run]

依赖：reverse_geocode
安装：pip3 install reverse-geocode
"""
import argparse
import sqlite3
import reverse_geocode
import os
import sys


def update_gps_city(db_path, dry_run=False):
    if not os.path.isfile(db_path):
        print(f"未找到数据库文件: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 只处理gps_lat/lon非空且gps_city为空的记录
    c.execute("SELECT id, gps_lat, gps_lon FROM photos WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL AND (gps_city IS NULL OR gps_city='')")
    rows = c.fetchall()
    print(f"待处理照片数: {len(rows)}")
    updated = 0
    failed = 0
    samples = []

    for rid, lat, lon in rows:
        try:
            loc = reverse_geocode.search([(lat, lon)])[0]
            city = loc.get("city", "")
            admin1 = loc.get("admin1", "")
            country = loc.get("country", "")
            # 组合城市名（优先city，有则city+admin1，无city用admin1+country）
            if city and city != admin1:
                city_name = f"{city}, {admin1}"
            elif admin1:
                city_name = f"{admin1}, {country}"
            else:
                city_name = country or "(未知)"
            city_name = city_name.strip()
            if not dry_run:
                c.execute("UPDATE photos SET gps_city = ? WHERE id = ?", (city_name, rid))
            updated += 1
            if len(samples) < 5:
                samples.append({"id": rid, "lat": lat, "lon": lon, "city": city_name})
        except Exception as e:
            failed += 1
            if len(samples) < 5:
                samples.append({"id": rid, "lat": lat, "lon": lon, "city": "失败", "err": str(e)})
    if not dry_run:
        conn.commit()

    print(f"已补全: {updated}，失败: {failed}")
    print("样例:")
    for item in samples:
        print(item)
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="批量填充gps_city，使用reverse_geocode。仅处理gps_city为空的照片。")
    parser.add_argument('--db', type=str, default='/tmp/photomemory.db', help='数据库路径，默认/tmp/photomemory.db')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，将不会写入数据库')
    args = parser.parse_args()
    update_gps_city(args.db, args.dry_run)

if __name__ == "__main__":
    main()
