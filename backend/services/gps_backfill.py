"""
gps_backfill.py - 负责自动补齐 photos 表中缺失 gps_city 的记录。
可通过 import 调用：backfill_gps_city(db_path, dry_run=False, limit=1000)

依赖 reverse_geocode，需提前 pip3 install reverse-geocode。
"""
import os
import sys
import reverse_geocode
from backend.db_util import get_optimized_connection


def backfill_gps_city(db_path, dry_run=False, limit=1000):
    """
    批量为缺少 gps_city 但有 gps_lat/lon 的照片记录补全城市。
    Args:
        db_path (str): SQLite 数据库文件路径
        dry_run (bool): 仅预览，不写入数据库
        limit (int): 单次处理最大条数（防止超大批量阻塞）
    Returns:
        dict: 统计信息
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"未找到数据库文件: {db_path}")

    conn = get_optimized_connection(db_path)
    c = conn.cursor()

    # 查询需补齐的记录，限制最大处理条数
    c.execute("SELECT id, gps_lat, gps_lon FROM photos WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL AND (gps_city IS NULL OR gps_city='') LIMIT ?", (limit,))
    rows = c.fetchall()
    updated = 0
    failed = 0
    samples = []

    for rid, lat, lon in rows:
        try:
            loc = reverse_geocode.search([(lat, lon)])[0]
            city = loc.get("city", "")
            admin1 = loc.get("admin1", "")
            country = loc.get("country", "")
            # 组合城市名：优先 city+admin1，否则 admin1+country
            if city and city != admin1:
                city_name = f"{city}, {admin1}" if admin1 else city
            elif admin1:
                city_name = f"{admin1}, {country}" if country else admin1
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
    conn.close()
    return {
        "total": len(rows),
        "updated": updated,
        "failed": failed,
        "samples": samples
    }
