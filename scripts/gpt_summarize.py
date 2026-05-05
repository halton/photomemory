#!/usr/bin/env python3
"""
PhotoMemory - GPT Vision 中英文照片摘要生成
用法: python3 gpt_summarize.py --db <db_path> [--limit 100] [--sleep 0.5]

使用 OpenAI GPT-4o-mini 生成中英文双语摘要，写入 summary (中文) 和 description_en (英文)。
"""

import argparse
import base64
import io
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from PIL import Image
from openai import OpenAI

# ---- 配置 ----
MODEL = "gpt-4o-mini"
MAX_IMAGE_SIZE = 1024
JPEG_QUALITY = 75
VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp'}

PROMPT = """Please describe this photo in two parts:

1. **Chinese** (中文): A concise 50-100 character description covering scene, people (count, age, actions), key objects, and time of day. Do NOT start with "照片中" or "这张照片".

2. **English**: A concise 50-100 word description of the same content.

Format your response exactly as:
CN: <中文描述>
EN: <English description>"""


def get_openai_client() -> OpenAI:
    """Get OpenAI client, try env var first, then openclaw proxy."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return OpenAI(api_key=api_key)
    # Use openclaw gateway proxy
    return OpenAI(
        base_url="http://localhost:4141/v1",
        api_key="openclaw",
    )


def prepare_image_base64(photo_path: str) -> Optional[str]:
    try:
        ext = Path(photo_path).suffix.lower()
        if ext in VIDEO_EXTS:
            return None
        img = Image.open(photo_path)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_SIZE:
            ratio = MAX_IMAGE_SIZE / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"  ⚠️ 无法读取图片 {photo_path}: {e}")
        return None


def call_gpt_vision(client: OpenAI, image_b64: str, retries: int = 3) -> Optional[tuple]:
    """Returns (cn_summary, en_description) or None."""
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "low",
                                },
                            },
                            {"type": "text", "text": PROMPT},
                        ],
                    }
                ],
                max_tokens=400,
                temperature=0.3,
            )
            content = resp.choices[0].message.content.strip()
            # Parse CN: and EN: lines
            cn = en = None
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("CN:"):
                    cn = line[3:].strip()
                elif line.startswith("EN:"):
                    en = line[3:].strip()
            if cn and en:
                return (cn, en)
            # Fallback: use whole content as CN
            return (content[:200], content[:200])
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 2 ** (attempt + 1)
                print(f"  ⏳ 限流，等待 {wait}s...")
                time.sleep(wait)
                continue
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  ❌ API error: {e}")
                return None
    return None


def main():
    parser = argparse.ArgumentParser(description="GPT Vision 中英文照片摘要")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--limit", type=int, default=0, help="最多处理数量 (0=全部)")
    parser.add_argument("--sleep", type=float, default=0.3, help="每张间隔秒数")
    parser.add_argument("--dry-run", action="store_true", help="仅打印不写入")
    parser.add_argument("--force", action="store_true", help="重新生成已有摘要的照片")
    args = parser.parse_args()

    client = get_openai_client()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # 查找需要摘要的照片
    if args.force:
        where = "WHERE is_screenshot = 0 AND is_duplicate = 0"
    else:
        where = """WHERE (summary IS NULL OR description_en IS NULL)
          AND is_screenshot = 0
          AND is_duplicate = 0"""

    # 排除视频
    for ext in VIDEO_EXTS:
        where += f" AND lower(filename) NOT LIKE '%{ext}'"

    query = f"SELECT id, path, filename FROM photos {where} ORDER BY taken_at DESC"
    if args.limit > 0:
        query += f" LIMIT {args.limit}"

    rows = db.execute(query).fetchall()
    total = len(rows)
    print(f"📷 找到 {total} 张照片需要 GPT 摘要（模型: {MODEL}）")

    if total == 0:
        print("✅ 全部照片已有中英文摘要！")
        return

    success = 0
    skipped = 0
    failed = 0

    for i, row in enumerate(rows):
        photo_id = row["id"]
        photo_path = row["path"]
        filename = row["filename"]

        print(f"[{i+1}/{total}] {filename}...", end=" ", flush=True)

        if not os.path.exists(photo_path):
            print("⚠️ 文件不存在")
            skipped += 1
            continue

        b64 = prepare_image_base64(photo_path)
        if b64 is None:
            print("⚠️ 跳过")
            skipped += 1
            continue

        if args.dry_run:
            print("(dry-run)")
            continue

        result = call_gpt_vision(client, b64)
        if result:
            cn, en = result
            db.execute(
                "UPDATE photos SET summary = ?, description_en = ? WHERE id = ?",
                (cn, en, photo_id),
            )
            if (i + 1) % 10 == 0:
                db.commit()
            print(f"✅ {cn[:30]}... | {en[:30]}...")
            success += 1
        else:
            print("❌ 失败")
            failed += 1

        if args.sleep > 0:
            time.sleep(args.sleep)

    db.commit()
    db.close()
    print(f"\n📊 完成！成功: {success}, 跳过: {skipped}, 失败: {failed}")


if __name__ == "__main__":
    main()
