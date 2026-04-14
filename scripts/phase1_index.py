#!/usr/bin/env python3
"""
PhotoMemory - Phase 1: EXIF索引 + 重复检测 + 截图过滤
用法: python3 phase1_index.py --dir /Volumes/nas-photos --db ./photomemory.db
"""

import os
import sys
import hashlib
import argparse
import sqlite3

def set_sqlite_pragmas(conn):
    """
    性能优化：统一设置 WAL 模式及核心参数。无副作用。
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

import json
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image
    import piexif
except ImportError:
    print("缺少依赖，请运行: pip3 install Pillow piexif")
    sys.exit(1)

try:
    import reverse_geocode
    HAS_GEO = True
except ImportError:
    HAS_GEO = False
    print("⚠️  reverse_geocode 未安装，GPS城市将为空。运行: pip3 install reverse-geocode")

# 支持的图片格式
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp', '.gif', '.webp', '.mov', '.mp4'}
# 递归扫描时匹配的扩展名（小写）
RECURSIVE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.mov', '.mp4'}


# 截图特征（分辨率特征 + 目录名）
SCREENSHOT_DIRS = {'screenshots', 'screen shot', 'screencapture', '截图', 'screenshot'}
SCREENSHOT_RESOLUTIONS = {
    (750, 1334), (1125, 2436), (1170, 2532), (1290, 2796),  # iPhone
    (1242, 2208), (1080, 1920),
    (2560, 1600), (2560, 1440), (1920, 1080), (2880, 1800),  # Mac
    (1366, 768), (1280, 800),
}


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    set_sqlite_pragmas(conn)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS photos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            path        TEXT UNIQUE NOT NULL,
            filename    TEXT,
            size        INTEGER,
            file_hash   TEXT,
            taken_at    TEXT,
            gps_lat     REAL,
            gps_lon     REAL,
            gps_city    TEXT,
            width       INTEGER,
            height      INTEGER,
            is_screenshot INTEGER DEFAULT 0,
            is_duplicate  INTEGER DEFAULT 0,
            duplicate_of  TEXT,
            indexed_at  TEXT,
            dir_label   TEXT
        );

        CREATE TABLE IF NOT EXISTS directories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            path      TEXT UNIQUE NOT NULL,
            label     TEXT,
            added_at  TEXT,
            last_scan TEXT,
            file_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS duplicate_groups (
            hash        TEXT PRIMARY KEY,
            paths       TEXT,   -- JSON array
            count       INTEGER,
            notified    INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_taken_at  ON photos(taken_at);
        CREATE INDEX IF NOT EXISTS idx_hash      ON photos(file_hash);
        CREATE INDEX IF NOT EXISTS idx_is_screenshot ON photos(is_screenshot);
    """)
    conn.commit()
    return conn


def compute_hash(path: str, chunk_size=65536) -> str:
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def parse_gps(exif_dict: dict):
    try:
        gps = exif_dict.get("GPS", {})
        if not gps:
            return None, None

        def to_decimal(dms, ref):
            d, m, s = dms
            val = d[0]/d[1] + m[0]/m[1]/60 + s[0]/s[1]/3600
            if ref in [b'S', b'W']:
                val = -val
            return round(val, 6)

        lat = to_decimal(gps[piexif.GPSIFD.GPSLatitude], gps[piexif.GPSIFD.GPSLatitudeRef])
        lon = to_decimal(gps[piexif.GPSIFD.GPSLongitude], gps[piexif.GPSIFD.GPSLongitudeRef])
        return lat, lon
    except Exception:
        return None, None


def parse_exif(path: str):
    result = {"taken_at": None, "gps_lat": None, "gps_lon": None, "width": None, "height": None}
    try:
        img = Image.open(path)
        result["width"], result["height"] = img.size

        exif_bytes = img.info.get("exif")
        if exif_bytes:
            exif = piexif.load(exif_bytes)
            # 拍摄时间
            dt_raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
            if dt_raw:
                result["taken_at"] = dt_raw.decode("utf-8", errors="ignore")
            # GPS
            lat, lon = parse_gps(exif)
            result["gps_lat"] = lat
            result["gps_lon"] = lon
    except Exception:
        pass
    return result


def is_screenshot(path: str, width: int, height: int) -> bool:
    # 目录名匹配
    parts = Path(path).parts
    for p in parts:
        if p.lower() in SCREENSHOT_DIRS:
            return True
    # 分辨率匹配
    if width and height:
        if (width, height) in SCREENSHOT_RESOLUTIONS or (height, width) in SCREENSHOT_RESOLUTIONS:
            return True
    return False


def scan_directory(dir_path: str, label: str, conn: sqlite3.Connection, verbose=True):
    c = conn.cursor()
    now = datetime.now().isoformat()

    # 注册目录
    c.execute("""
        INSERT OR REPLACE INTO directories(path, label, added_at, last_scan)
        VALUES (?, ?, ?, ?)
    """, (dir_path, label, now, now))
    conn.commit()

    hash_map = {}  # hash -> first_path (用于重复检测)
    # 加载已有哈希
    for row in c.execute("SELECT file_hash, path FROM photos WHERE file_hash != ''"):
        if row[0] not in hash_map:
            hash_map[row[0]] = row[1]

    total = 0
    new_count = 0
    dup_count = 0
    screenshot_count = 0
    errors = 0

    print(f"\n🔍 扫描目录: {dir_path} (标签: {label})")

    for root, dirs, files in os.walk(dir_path):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in IMAGE_EXTS:
                continue

            full_path = os.path.join(root, fname)
            total += 1

            if verbose and total % 100 == 0:
                print(f"  已处理 {total} 张...")

            # 跳过已索引
            exists = c.execute("SELECT id FROM photos WHERE path=?", (full_path,)).fetchone()
            if exists:
                continue

            try:
                stat = os.stat(full_path)
                fsize = stat.st_size
            except Exception:
                errors += 1
                continue

            # 计算哈希
            fhash = compute_hash(full_path)

            # EXIF
            meta = parse_exif(full_path)
            width, height = meta["width"], meta["height"]

            # 截图检测
            screenshot = 1 if is_screenshot(full_path, width, height) else 0
            if screenshot:
                screenshot_count += 1

            # 重复检测
            is_dup = 0
            dup_of = None
            if fhash and fhash in hash_map:
                is_dup = 1
                dup_of = hash_map[fhash]
                dup_count += 1
                # 更新重复组
                row = c.execute("SELECT paths, count FROM duplicate_groups WHERE hash=?", (fhash,)).fetchone()
                if row:
                    paths = json.loads(row[0])
                    paths.append(full_path)
                    c.execute("UPDATE duplicate_groups SET paths=?, count=? WHERE hash=?",
                              (json.dumps(paths, ensure_ascii=False), row[1]+1, fhash))
                else:
                    c.execute("INSERT INTO duplicate_groups(hash, paths, count) VALUES (?,?,?)",
                              (fhash, json.dumps([hash_map[fhash], full_path], ensure_ascii=False), 2))
            elif fhash:
                hash_map[fhash] = full_path

            # 逆地理编码（批量，先暂存）
            gps_city = None

            c.execute("""
                INSERT OR IGNORE INTO photos
                (path, filename, size, file_hash, taken_at, gps_lat, gps_lon, gps_city,
                 width, height, is_screenshot, is_duplicate, duplicate_of, indexed_at, dir_label)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                full_path, fname, fsize, fhash,
                meta["taken_at"], meta["gps_lat"], meta["gps_lon"], gps_city,
                width, height,
                screenshot, is_dup, dup_of,
                now, label
            ))
            new_count += 1

            if new_count % 200 == 0:
                conn.commit()

    # 批量逆地理编码
    if HAS_GEO:
        print("🌍 正在逆地理编码...")
        geo_rows = c.execute(
            "SELECT id, gps_lat, gps_lon FROM photos WHERE gps_lat IS NOT NULL AND gps_city IS NULL"
        ).fetchall()
        if geo_rows:
            coords = [(r[1], r[2]) for r in geo_rows]
            geo_results = reverse_geocode.search(coords)
            updates = []
            for (photo_id, _, __), geo in zip(geo_rows, geo_results):
                if geo.get('country_code') == 'CN':
                    label_geo = f"{geo.get('state','')} {geo.get('city','')}".strip()
                else:
                    label_geo = f"{geo.get('city','')}, {geo.get('country','')}".strip()
                updates.append((label_geo, photo_id))
            c.executemany("UPDATE photos SET gps_city=? WHERE id=?", updates)
            conn.commit()
            print(f"  已解析 {len(updates)} 条位置")

    conn.commit()

    # 更新目录文件数
    c.execute("UPDATE directories SET file_count=?, last_scan=? WHERE path=?",
              (total, now, dir_path))
    conn.commit()

    print(f"\n✅ 扫描完成:")
    print(f"   总文件数  : {total}")
    print(f"   新增索引  : {new_count}")
    print(f"   重复图片  : {dup_count} (已标记，未删除)")
    print(f"   疑似截图  : {screenshot_count} (已标记，未删除)")
    print(f"   错误      : {errors}")

    if dup_count > 0:
        print(f"\n⚠️  发现 {dup_count} 张重复图片，运行 --report-dups 查看详情")

    return {"total": total, "new": new_count, "duplicates": dup_count, "screenshots": screenshot_count}


def report_duplicates(conn: sqlite3.Connection, limit=50):
    c = conn.cursor()
    rows = c.execute("""
        SELECT hash, paths, count FROM duplicate_groups
        WHERE count > 1 ORDER BY count DESC LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        print("没有发现重复图片。")
        return

    print(f"\n📋 重复图片报告 (前{limit}组):")
    for i, (h, paths_json, cnt) in enumerate(rows, 1):
        paths = json.loads(paths_json)
        print(f"\n  [{i}] {cnt}张重复 (MD5: {h[:8]}...)")
        for p in paths:
            print(f"       {p}")


def main():
    parser = argparse.ArgumentParser(description="PhotoMemory Phase 1 - 图片索引")
    parser.add_argument("--photos-dir", "--dir", dest="photos_dir", required=True, help="要扫描的根目录路径 (如 /Volumes/backup/photos/)")
    parser.add_argument("--label", default="", help="目录标签（如：家庭相册）")
    parser.add_argument("--db", default="./photomemory.db", help="数据库路径")
    parser.add_argument("--no-recursive", dest="recursive", action="store_false", help="仅扫描指定单一目录，不递归 (默认递归)")
    parser.set_defaults(recursive=True)
    parser.add_argument("--report-dups", action="store_true", help="显示重复图片报告")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    args = parser.parse_args()

    conn = init_db(args.db)

    if args.report_dups:
        report_duplicates(conn)
        return

    if args.stats:
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        dups = c.execute("SELECT COUNT(*) FROM photos WHERE is_duplicate=1").fetchone()[0]
        shots = c.execute("SELECT COUNT(*) FROM photos WHERE is_screenshot=1").fetchone()[0]
        dirs = c.execute("SELECT COUNT(*) FROM directories").fetchone()[0]
        print(f"\n📊 数据库统计:")
        print(f"   总索引图片: {total:,}")
        print(f"   重复图片  : {dups:,}")
        print(f"   截图      : {shots:,}")
        print(f"   已索引目录: {dirs}")
        return

    root = args.photos_dir
    if not os.path.isdir(root):
        print(f"❌ 目录不存在: {root}")
        sys.exit(1)

    def recursive_scan(root_dir, conn, verbose=True):
        """
        递归扫描 root_dir 下所有 RECURSIVE_EXTS 文件，支持大目录，进度显示。
        """
        all_files = []
        for p in Path(root_dir).rglob('*'):
            if p.is_file() and p.suffix.lower() in RECURSIVE_EXTS:
                all_files.append(str(p))
        total = len(all_files)
        print(f"\n🔍 递归扫描 {root_dir}，共找到 {total} 文件")
        processed = 0
        batch = 100
        label = args.label or Path(root_dir).name
        now = datetime.now().isoformat()
        c = conn.cursor()
        hash_map = {}
        for row in c.execute("SELECT file_hash, path FROM photos WHERE file_hash != ''"):
            if row[0] not in hash_map:
                hash_map[row[0]] = row[1]
        new_count = 0
        dup_count = 0
        screenshot_count = 0
        errors = 0
        for idx, full_path in enumerate(all_files, 1):
            processed += 1
            if verbose and processed % batch == 0:
                print(f"[进度] {processed}/{total} 已处理")
            fname = os.path.basename(full_path)
            ext = Path(fname).suffix.lower()
            exists = c.execute("SELECT id FROM photos WHERE path=?", (full_path,)).fetchone()
            if exists:
                continue
            try:
                stat = os.stat(full_path)
                fsize = stat.st_size
            except Exception:
                errors += 1
                continue
            fhash = compute_hash(full_path)
            meta = parse_exif(full_path)
            width, height = meta["width"], meta["height"]
            screenshot = 1 if is_screenshot(full_path, width, height) else 0
            if screenshot:
                screenshot_count += 1
            is_dup = 0
            dup_of = None
            if fhash and fhash in hash_map:
                is_dup = 1
                dup_of = hash_map[fhash]
                dup_count += 1
                row = c.execute("SELECT paths, count FROM duplicate_groups WHERE hash=?", (fhash,)).fetchone()
                if row:
                    paths = json.loads(row[0])
                    paths.append(full_path)
                    c.execute("UPDATE duplicate_groups SET paths=?, count=? WHERE hash=?",
                              (json.dumps(paths, ensure_ascii=False), row[1]+1, fhash))
                else:
                    c.execute("INSERT INTO duplicate_groups(hash, paths, count) VALUES (?,?,?)",
                              (fhash, json.dumps([hash_map[fhash], full_path], ensure_ascii=False), 2))
            elif fhash:
                hash_map[fhash] = full_path
            gps_city = None
            c.execute("""
                INSERT OR IGNORE INTO photos
                (path, filename, size, file_hash, taken_at, gps_lat, gps_lon, gps_city,
                 width, height, is_screenshot, is_duplicate, duplicate_of, indexed_at, dir_label)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                full_path, fname, fsize, fhash,
                meta["taken_at"], meta["gps_lat"], meta["gps_lon"], gps_city,
                width, height,
                screenshot, is_dup, dup_of,
                now, label
            ))
            new_count += 1
            if new_count % 200 == 0:
                conn.commit()
        conn.commit()
        print(f"\n✅ 扫描完成: 共计 {total}，新增索引 {new_count}，重复 {dup_count}，截图 {screenshot_count}，错误 {errors}")

    if args.recursive:
        recursive_scan(root, conn)
    else:
        label = args.label or Path(root).name
        scan_directory(root, label, conn)


if __name__ == "__main__":
    main()
