#!/usr/bin/env python3
"""
PhotoMemory - 批量生成照片 AI Summary
使用 SiliconFlow VL 模型理解图片内容，写入数据库 summary 字段。

用法:
  python3 generate_summaries.py --db <db_path> [--model Qwen/Qwen3-VL-8B-Instruct] [--limit 100] [--batch 5] [--dry-run]

环境变量:
  SILICONFLOW_API_KEY - SiliconFlow API Key
"""

import argparse
import base64
import io
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Optional

import requests

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from PIL import Image

# ---- 配置 ----
DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MAX_IMAGE_SIZE = 1024  # 长边最大像素
JPEG_QUALITY = 75
VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp'}

SYSTEM_PROMPT = """你是一个照片描述助手。请用简洁的中文描述照片的内容，包括：
- 主要场景/地点
- 人物（如有，描述人数、大致年龄、动作）
- 关键物品
- 氛围/时间（白天/夜晚等）
控制在 50-100 字以内。不要开头说"照片中"或"这张照片"，直接描述内容。"""


def load_api_key():
    """从环境变量或 openclaw 配置加载 API key"""
    key = os.environ.get("SILICONFLOW_API_KEY")
    if key:
        return key
    # 从 openclaw.json 读取
    cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = json.load(f)
        providers = cfg.get("models", {}).get("providers", {})
        sf = providers.get("siliconflow", {})
        key = sf.get("apiKey", "")
        if key:
            return key
    print("❌ 未找到 SILICONFLOW_API_KEY，请设置环境变量或配置 openclaw.json")
    sys.exit(1)


def prepare_image_base64(photo_path: str) -> Optional[str]:
    """读取图片，缩放，转 base64 JPEG"""
    try:
        ext = Path(photo_path).suffix.lower()
        if ext in VIDEO_EXTS:
            return None  # 跳过视频

        img = Image.open(photo_path)
        img = img.convert("RGB")

        # 缩放
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


def call_vision_api(api_key: str, model: str, image_b64: str, retries: int = 3) -> Optional[str]:
    """调用 VL 模型获取描述"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                    {"type": "text", "text": "描述这张照片。"},
                ],
            },
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }

    for attempt in range(retries):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 5))
                print(f"  ⏳ 限流，等待 {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            # 去掉 thinking 标签（如果模型返回的话）
            if "<think>" in content:
                idx = content.find("</think>")
                if idx >= 0:
                    content = content[idx + 8:].strip()
            return content
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  ❌ API 调用失败: {e}")
                return None
    return None


def main():
    parser = argparse.ArgumentParser(description="批量生成照片 AI Summary")
    parser.add_argument("--db", required=True, help="SQLite 数据库路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="VL 模型 ID")
    parser.add_argument("--limit", type=int, default=0, help="最多处理数量 (0=全部)")
    parser.add_argument("--batch", type=int, default=1, help="并发数")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不写入")
    parser.add_argument("--sleep", type=float, default=0.5, help="每张之间间隔秒数")
    args = parser.parse_args()

    api_key = load_api_key()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # 查找缺 summary 的照片
    query = """
        SELECT id, path, filename FROM photos
        WHERE summary IS NULL
          AND is_screenshot = 0
          AND is_duplicate = 0
          AND lower(filename) NOT LIKE '%.mov'
          AND lower(filename) NOT LIKE '%.mp4'
          AND lower(filename) NOT LIKE '%.avi'
          AND lower(filename) NOT LIKE '%.mkv'
          AND lower(filename) NOT LIKE '%.m4v'
          AND lower(filename) NOT LIKE '%.3gp'
        ORDER BY taken_at DESC
    """
    if args.limit > 0:
        query += f" LIMIT {args.limit}"

    rows = db.execute(query).fetchall()
    total = len(rows)
    print(f"📷 找到 {total} 张照片需要生成 summary（模型: {args.model}）")

    if total == 0:
        print("✅ 全部照片已有 summary！")
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
            print("⚠️ 文件不存在，跳过")
            skipped += 1
            continue

        b64 = prepare_image_base64(photo_path)
        if b64 is None:
            print("⚠️ 无法处理，跳过")
            skipped += 1
            continue

        if args.dry_run:
            print("(dry-run) 跳过 API 调用")
            continue

        summary = call_vision_api(api_key, args.model, b64)
        if summary:
            db.execute("UPDATE photos SET summary = ? WHERE id = ?", (summary, photo_id))
            if (i + 1) % 10 == 0:
                db.commit()
            print(f"✅ {summary[:40]}...")
            success += 1
        else:
            print("❌ 生成失败")
            failed += 1

        if args.sleep > 0:
            time.sleep(args.sleep)

    db.commit()
    db.close()

    print(f"\n📊 完成！成功: {success}, 跳过: {skipped}, 失败: {failed}")


if __name__ == "__main__":
    main()
