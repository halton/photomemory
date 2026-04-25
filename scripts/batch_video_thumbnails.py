#!/usr/bin/env python3
"""
batch_video_thumbnails.py — 批量为视频文件预生成缩略图（取中间帧）。

用法：
    python scripts/batch_video_thumbnails.py [--db DATA/photomemory.db] [--size 300] [--workers 4]

功能：
    1. 扫描数据库中所有视频记录
    2. 跳过已有缩略图缓存的视频
    3. 用 ffmpeg 抽取视频中间帧生成缩略图
    4. 生成后在数据库 photos 表新增 has_thumbnail 列标记
    5. 输出进度日志和统计摘要
"""
import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v", ".3gp", ".wmv", ".flv", ".webm", ".ts", ".mts"}
DEFAULT_SIZE = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def find_ffmpeg():
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    r = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def find_ffprobe():
    for p in ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "/usr/bin/ffprobe"]:
        if os.path.exists(p):
            return p
    r = subprocess.run(["which", "ffprobe"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()


def get_video_duration(path: str) -> float | None:
    """用 ffprobe 获取视频时长（秒），失败返回 None。"""
    if not FFPROBE:
        return None
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return None


def generate_thumbnail(path: str, size: int, cache_file: str) -> tuple[bool, str]:
    """
    为单个视频生成缩略图，取中间帧。
    返回 (success, message)。
    """
    if not FFMPEG:
        return False, "ffmpeg not found"
    if not os.path.exists(path):
        return False, "file not found"

    # 获取时长，取中间位置
    duration = get_video_duration(path)
    if duration and duration > 2:
        seek_time = duration / 2
    else:
        seek_time = 1.0  # 短视频 fallback 到 1 秒

    # 格式化 seek 时间
    seek_str = f"{seek_time:.2f}"

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [FFMPEG, "-y", "-ss", seek_str,
             "-i", path,
             "-vframes", "1",
             "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
             "-q:v", "3",
             tmp_path],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            # Atomic-ish write: rename from tmp
            os.replace(tmp_path, cache_file)
            return True, "ok"
        else:
            stderr = result.stderr.decode(errors="replace")[:200] if result.stderr else ""
            return False, f"ffmpeg exit {result.returncode}: {stderr}"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timeout"
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def process_one(args: tuple) -> tuple[int, bool, str]:
    """Worker function: (photo_id, path, size, cache_file) -> (photo_id, success, msg)"""
    photo_id, path, size, cache_file = args
    ok, msg = generate_thumbnail(path, size, cache_file)
    return photo_id, ok, msg


def main():
    parser = argparse.ArgumentParser(description="批量生成视频缩略图")
    parser.add_argument("--db", default=None, help="数据库路径（默认自动检测）")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE, help="缩略图尺寸")
    parser.add_argument("--workers", type=int, default=4, help="并行进程数")
    args = parser.parse_args()

    # 自动检测数据库路径
    if args.db:
        db_path = Path(args.db)
    else:
        candidates = [
            Path(__file__).resolve().parent.parent / "data" / "photomemory.db",
            Path("data/photomemory.db"),
        ]
        db_path = next((c for c in candidates if c.exists()), None)
        if not db_path:
            log.error("找不到数据库文件，请用 --db 指定")
            sys.exit(1)

    db_path = db_path.resolve()
    cache_dir = db_path.parent / "thumbs"
    cache_dir.mkdir(exist_ok=True)

    if not FFMPEG:
        log.error("ffmpeg 未找到，请先安装")
        sys.exit(1)

    log.info(f"数据库: {db_path}")
    log.info(f"缓存目录: {cache_dir}")
    log.info(f"缩略图尺寸: {args.size}, 并行数: {args.workers}")

    # 查询所有视频
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ext_conditions = " OR ".join(f"LOWER(path) LIKE '%{ext}'" for ext in VIDEO_EXTS)
    rows = conn.execute(f"SELECT id, path FROM photos WHERE {ext_conditions}").fetchall()
    log.info(f"数据库中共 {len(rows)} 个视频文件")

    # 筛选需要生成缩略图的
    tasks = []
    skipped = 0
    missing_file = 0
    for row in rows:
        photo_id = row["id"]
        path = row["path"]
        if not os.path.exists(path):
            missing_file += 1
            continue
        try:
            mtime = int(os.path.getmtime(path))
        except Exception:
            mtime = 0
        cache_file = str(cache_dir / f"v_{photo_id}_{args.size}_{mtime}.jpg")
        if os.path.exists(cache_file):
            skipped += 1
            continue
        tasks.append((photo_id, path, args.size, cache_file))

    log.info(f"已有缩略图跳过: {skipped}, 文件缺失: {missing_file}, 待生成: {len(tasks)}")

    if not tasks:
        log.info("无需生成，全部已完成 ✓")
        conn.close()
        return

    # 批量生成
    success_ids = []
    fail_count = 0
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, t): t for t in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            photo_id, ok, msg = fut.result()
            if ok:
                success_ids.append(photo_id)
            else:
                fail_count += 1
                log.warning(f"  FAIL id={photo_id}: {msg}")
            if i % 100 == 0 or i == len(tasks):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                log.info(f"  进度: {i}/{len(tasks)} ({rate:.1f}/s) 成功={len(success_ids)} 失败={fail_count}")

    elapsed = time.time() - t0
    log.info(f"生成完毕: 成功={len(success_ids)}, 失败={fail_count}, 耗时={elapsed:.1f}s")

    # 更新数据库: 添加 has_thumbnail 列（如不存在）并标记
    if success_ids:
        cursor = conn.cursor()
        # 安全添加列
        try:
            cursor.execute("ALTER TABLE photos ADD COLUMN has_thumbnail INTEGER DEFAULT 0")
            log.info("已添加 has_thumbnail 列")
        except sqlite3.OperationalError:
            pass  # 列已存在

        # 批量更新
        batch_size = 500
        for i in range(0, len(success_ids), batch_size):
            batch = success_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(batch))
            cursor.execute(
                f"UPDATE photos SET has_thumbnail = 1 WHERE id IN ({placeholders})",
                batch,
            )
        # 同时标记之前已有缩略图的（skipped 的那些）
        # 重新扫描已有缩略图的 video IDs
        for row in rows:
            photo_id = row["id"]
            path = row["path"]
            if not os.path.exists(path):
                continue
            try:
                mtime = int(os.path.getmtime(path))
            except Exception:
                mtime = 0
            cache_file = cache_dir / f"v_{photo_id}_{args.size}_{mtime}.jpg"
            if cache_file.exists() and photo_id not in success_ids:
                cursor.execute("UPDATE photos SET has_thumbnail = 1 WHERE id = ?", (photo_id,))

        conn.commit()
        log.info("数据库 has_thumbnail 已更新")

    conn.close()
    log.info("全部完成 ✓")


if __name__ == "__main__":
    main()
