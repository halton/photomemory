"""
thumbnail.py  - 缩略图与视频缩略图服务。用于图片/视频小图生成、缓存、占位图。
"""
import os
import io
import tempfile
import subprocess
from pathlib import Path
from PIL import Image, ImageOps

def generate_image_thumbnail(path, size):
    """
    生成图片文件的缩略图，EXIF 归正，保存为 JPEG。用于照片、本地图片缩略图展示。
    Args:
        path (str): 图片文件路径。
        size (int): 缩略图边长（最大值）。
    Returns:
        (bytes): JPEG 数据，RGB。
    Raises:
        Exception: 打开或处理失败。
    """
    img = Image.open(path)
    # EXIF旋转
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    buf.seek(0)
    return buf.getvalue()

def find_ffmpeg():
    """
    自动查找 ffmpeg 可执行文件路径。
    """
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def generate_video_thumbnail(path, size):
    """
    视频文件生成缩略图（取第1秒的一帧）。
    Args:
        path (str): 视频文件路径。
        size (int): 缩略图边长。
    Returns:
        (bytes): JPEG 数据
    注意：若 ffmpeg 不可用，抛出 FileNotFoundError
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg 未找到")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run([
            ffmpeg, "-y", "-ss", "00:00:01",
            "-i", path,
            "-vframes", "1",
            "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
            "-q:v", "3",
            tmp_path
        ], capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                data = f.read()
            return data
        else:
            raise Exception(f"ffmpeg 执行失败 code={result.returncode}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def placeholder_thumbnail(size, emoji="?"):
    """
    生成纯色 JPEG 占位缩略图。返回 bytes。
    """
    img = Image.new("RGB", (size, size), color=(40, 40, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf.getvalue()
