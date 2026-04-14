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


from backend.services.gps_backfill import backfill_gps_city

def update_gps_city(db_path, dry_run=False, limit=1000):
    """
    兼容历史脚本参数，用新版后端逻辑自动补全 gps_city。
    """
    result = backfill_gps_city(db_path, dry_run=dry_run, limit=limit)
    print(f"待处理照片数: {result['total']}")
    print(f"已补全: {result['updated']}，失败: {result['failed']}")
    print("样例:")
    for item in result['samples']:
        print(item)


def main():
    parser = argparse.ArgumentParser(description="批量填充gps_city，使用reverse_geocode。仅处理gps_city为空的照片。")
    parser.add_argument('--db', type=str, default='/tmp/photomemory.db', help='数据库路径，默认/tmp/photomemory.db')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，将不会写入数据库')
    args = parser.parse_args()
    update_gps_city(args.db, args.dry_run)

if __name__ == "__main__":
    main()
