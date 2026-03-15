#!/usr/bin/env python3
"""
PhotoMemory - Phase 3: API Server
启动: python3 api_server.py --db ./photomemory.db --port 8765 [--token YOUR_TOKEN]
"""

import os
import io
import json
import sqlite3
import argparse
import subprocess
import tempfile
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_file, abort, make_response
from flask_cors import CORS
from PIL import Image

# ── Token 认证 ────────────────────────────────────────────
ACCESS_TOKEN = None          # 启动时从 --token 或环境变量设置
SESSION_COOKIE = "pm_session"
SESSION_TTL_HOURS = 720      # 30天免重登

# 已授权的 session tokens（内存存储，重启失效）
_valid_sessions: dict[str, datetime] = {}

def _check_auth() -> bool:
    """验证请求是否已授权"""
    if not ACCESS_TOKEN:
        return True  # 未设置 token，本地模式不验证

    # 1. Bearer token（API客户端/Chat工具用）
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        if secrets.compare_digest(token, ACCESS_TOKEN):
            return True

    # 2. Session cookie（浏览器登录后）
    session = request.cookies.get(SESSION_COOKIE, "")
    if session and session in _valid_sessions:
        if datetime.now() < _valid_sessions[session]:
            return True
        else:
            _valid_sessions.pop(session, None)

    # 3. URL 参数 token（扫码/分享链接用）
    url_token = request.args.get("token", "")
    if url_token and secrets.compare_digest(url_token, ACCESS_TOKEN):
        return True

    return False

def require_auth(f):
    """装饰器：对 API 路由强制验证"""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _check_auth():
            return jsonify({"error": "Unauthorized", "code": 401}), 401
        return f(*args, **kwargs)
    return wrapper


# 中文地名别名映射（英文存储，支持中文搜索）
CITY_ALIASES = {
    "北京": ["Beijing", "beijing"],
    "上海": ["Shanghai", "shanghai"],
    "广州": ["Guangzhou", "guangzhou"],
    "深圳": ["Shenzhen", "shenzhen"],
    "成都": ["Chengdu", "chengdu"],
    "杭州": ["Hangzhou", "hangzhou"],
    "武汉": ["Wuhan", "wuhan"],
    "西安": ["Xi'an", "Xian", "xian"],
    "南京": ["Nanjing", "nanjing"],
    "重庆": ["Chongqing", "chongqing"],
    "天津": ["Tianjin", "tianjin"],
    "山西": ["Shanxi", "shanxi"],
    "北京海淀": ["Beijing Haidian", "Haidian"],
    "北京金融街": ["Beijing Jinrongjie", "Jinrongjie"],
    "北京景山": ["Beijing Jingshan", "Jingshan"],
    "江苏": ["Jiangsu", "jiangsu"],
    "苏州": ["Songling", "Suzhou", "suzhou"],
    "太原": ["Gutao", "gutao", "Taiyuan"],
}

VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp'}

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")
CORS(app)

@app.route("/")
def index():
    return app.send_static_file("index.html")

# ── 登录接口 ──────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    token = data.get("token", "").strip()
    if not ACCESS_TOKEN:
        return jsonify({"ok": True, "message": "no auth required"})
    if not token or not secrets.compare_digest(token, ACCESS_TOKEN):
        return jsonify({"error": "Invalid token"}), 401
    # 生成 session
    session_id = secrets.token_urlsafe(32)
    _valid_sessions[session_id] = datetime.now() + timedelta(hours=SESSION_TTL_HOURS)
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(SESSION_COOKIE, session_id,
                    max_age=SESSION_TTL_HOURS * 3600,
                    httponly=True, samesite="Lax")
    return resp

@app.route("/api/auth_check")
def auth_check():
    """前端用来检测是否已登录"""
    if not ACCESS_TOKEN:
        return jsonify({"authenticated": True, "mode": "open"})
    if _check_auth():
        return jsonify({"authenticated": True, "mode": "token"})
    return jsonify({"authenticated": False}), 401

DB_PATH = None

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.bmp', '.tiff', '.gif', '.webp'}

# ── DB Helper ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 搜索 API ──────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
@require_auth
def search():
    """
    通用搜索接口
    参数:
      q        - 文本（人物名/地点）
      date_from - 开始日期 YYYY-MM-DD
      date_to   - 结束日期 YYYY-MM-DD
      year      - 年份
      month     - 月份
      person    - 人物名
      exclude_screenshots - 1/0（默认1）
      exclude_duplicates  - 1/0（默认0）
      limit     - 最多返回数量（默认50）
      offset    - 分页偏移
    """
    conn = get_db()
    c = conn.cursor()

    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    year = request.args.get("year", "")
    month = request.args.get("month", "")
    person_name = request.args.get("person", "")
    exclude_screenshots = request.args.get("exclude_screenshots", "1") == "1"
    exclude_duplicates = request.args.get("exclude_duplicates", "0") == "1"
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    # 人物检索：先查 person_id
    person_photo_paths = None
    if person_name or (q and _is_person_query(q, c)):
        name = person_name or q
        person_rows = c.execute("""
            SELECT DISTINCT f.photo_path FROM faces f
            JOIN persons p ON p.id = f.person_id
            WHERE p.name LIKE ?
        """, (f"%{name}%",)).fetchall()
        person_photo_paths = {r["photo_path"] for r in person_rows}
        if not person_photo_paths:
            return jsonify({"results": [], "total": 0, "query": {"person": name}})

    # 构建 SQL
    conditions = []
    params = []

    if exclude_screenshots:
        conditions.append("p.is_screenshot = 0")
    if exclude_duplicates:
        conditions.append("p.is_duplicate = 0")

    if date_from:
        conditions.append("p.taken_at >= ?")
        params.append(date_from.replace("-", ":").replace("-", ":") if ":" not in date_from else date_from)
        conditions[-1] = "p.taken_at >= ?"
        params[-1] = date_from

    if date_to:
        conditions.append("p.taken_at <= ?")
        params.append(date_to + " 23:59:59")

    if year:
        conditions.append("p.taken_at LIKE ?")
        params.append(f"{year}%")

    if month and year:
        conditions[-1] = "p.taken_at LIKE ?"
        params[-1] = f"{year}:{month}%"

    if person_photo_paths:
        placeholders = ",".join("?" * len(person_photo_paths))
        conditions.append(f"p.path IN ({placeholders})")
        params.extend(list(person_photo_paths))

    # 地点文本搜索（GPS城市字段，支持中文别名）
    if q and not person_name and not _is_person_query(q, c):
        # 展开中文别名为英文关键词
        search_terms = [q]
        for cn, aliases in CITY_ALIASES.items():
            if q in cn or cn in q:
                search_terms.extend(aliases)
            for alias in aliases:
                if q.lower() in alias.lower():
                    search_terms.append(cn)
                    break
        # 去重
        search_terms = list(dict.fromkeys(search_terms))
        # 构建多词 OR 条件
        term_conditions = []
        for term in search_terms:
            term_conditions.append("(p.gps_city LIKE ? OR p.filename LIKE ? OR p.dir_label LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
        conditions.append("(" + " OR ".join(term_conditions) + ")")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT p.id, p.path, p.filename, p.taken_at,
               p.gps_lat, p.gps_lon, p.gps_city,
               p.width, p.height, p.is_screenshot, p.is_duplicate,
               p.dir_label, p.size
        FROM photos p
        {where}
        ORDER BY p.taken_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = c.execute(sql, params).fetchall()

    # 计总数
    count_sql = f"SELECT COUNT(*) FROM photos p {where}"
    total = c.execute(count_sql, params[:-2]).fetchone()[0]

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "path": r["path"],
            "filename": r["filename"],
            "taken_at": r["taken_at"],
            "gps_lat": r["gps_lat"],
            "gps_lon": r["gps_lon"],
            "gps_city": r["gps_city"],
            "width": r["width"],
            "height": r["height"],
            "is_screenshot": bool(r["is_screenshot"]),
            "is_duplicate": bool(r["is_duplicate"]),
            "dir_label": r["dir_label"],
            "thumb_url": f"/api/thumb/{r['id']}",
            "original_url": f"/api/photo/{r['id']}",
        })

    conn.close()
    return jsonify({"results": results, "total": total, "limit": limit, "offset": offset})


def _is_person_query(q: str, c) -> bool:
    """判断查询词是否命中已知人名"""
    row = c.execute("SELECT id FROM persons WHERE name LIKE ?", (f"%{q}%",)).fetchone()
    return row is not None


# ── 缩略图 API ────────────────────────────────────────────

@app.route("/api/thumb/<int:photo_id>")
@require_auth
def thumbnail(photo_id):
    conn = get_db()
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    path = row["path"]
    if not os.path.exists(path):
        abort(404)

    size = int(request.args.get("size", 300))
    ext = Path(path).suffix.lower()

    # 视频：用 ffmpeg 截取第1秒帧
    if ext in VIDEO_EXTS:
        return _video_thumbnail(path, size)

    # 图片
    try:
        img = Image.open(path)
        img.thumbnail((size, size), Image.LANCZOS)
        # 处理 EXIF 旋转
        try:
            exif = img._getexif()
            if exif:
                from PIL.ExifTags import TAGS
                for tag, val in exif.items():
                    if TAGS.get(tag) == "Orientation":
                        rotations = {3: 180, 6: 270, 8: 90}
                        if val in rotations:
                            img = img.rotate(rotations[val], expand=True)
        except Exception:
            pass
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")
    except Exception:
        abort(500)


def _video_thumbnail(path: str, size: int):
    """用 ffmpeg 截取视频第1秒画面作为缩略图"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        # ffmpeg 不可用时返回占位图
        return _placeholder_thumb(size, "🎬")

    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

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
            os.unlink(tmp_path)
            return send_file(io.BytesIO(data), mimetype="image/jpeg")
        else:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return _placeholder_thumb(size, "🎬")
    except Exception:
        return _placeholder_thumb(size, "🎬")


def _find_ffmpeg():
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _placeholder_thumb(size: int, emoji: str = "?"):
    """生成纯色占位缩略图"""
    img = Image.new("RGB", (size, size), color=(40, 40, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


# ── 原图 API ──────────────────────────────────────────────

@app.route("/api/photo/<int:photo_id>")
@require_auth
def original_photo(photo_id):
    conn = get_db()
    row = conn.execute("SELECT path, filename FROM photos WHERE id=?", (photo_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    path = row["path"]
    if not os.path.exists(path):
        abort(404)
    ext = Path(path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".heic": "image/heic",
        ".gif": "image/gif", ".webp": "image/webp",
        ".mp4": "video/mp4", ".mov": "video/quicktime",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mime, as_attachment=False)


# ── 人物 API ──────────────────────────────────────────────

@app.route("/api/persons", methods=["GET"])
@require_auth
def list_persons():
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.name, p.alias, p.face_count,
               MIN(f.photo_path) as sample_photo,
               MIN(f.id) as sample_face_id
        FROM persons p
        LEFT JOIN faces f ON f.person_id = p.id
        GROUP BY p.id
        ORDER BY p.face_count DESC
    """).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "name": r["name"],
            "alias": r["alias"],
            "face_count": r["face_count"],
            "thumb_url": f"/api/face_thumb/{r['sample_face_id']}" if r["sample_face_id"] else None,
        })
    return jsonify({"persons": results})


@app.route("/api/persons/<int:person_id>", methods=["PATCH"])
@require_auth
def update_person(person_id):
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    conn = get_db()
    conn.execute("UPDATE persons SET name=?, updated_at=? WHERE id=?",
                 (name, datetime.now().isoformat(), person_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/face_thumb/<int:face_id>")
def face_thumbnail(face_id):
    conn = get_db()
    row = conn.execute("SELECT photo_path, bbox FROM faces WHERE id=?", (face_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    try:
        img = Image.open(row["photo_path"])
        bbox = json.loads(row["bbox"])
        x1, y1, x2, y2 = [int(v) for v in bbox]
        pad = 20
        w, h = img.size
        x1 = max(0, x1-pad); y1 = max(0, y1-pad)
        x2 = min(w, x2+pad); y2 = min(h, y2+pad)
        face = img.crop((x1, y1, x2, y2))
        face.thumbnail((150, 150))
        buf = io.BytesIO()
        face.convert("RGB").save(buf, "JPEG", quality=90)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")
    except Exception:
        abort(500)


@app.route("/api/photo_persons/<int:photo_id>")
def photo_persons(photo_id):
    """返回某张照片中出现的所有命名人物"""
    conn = get_db()
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"persons": []})

    rows = conn.execute("""
        SELECT DISTINCT p.id, p.name, MIN(f.id) as face_id
        FROM faces f
        JOIN persons p ON p.id = f.person_id
        WHERE f.photo_path = ? AND p.name IS NOT NULL
        GROUP BY p.id
    """, (row["path"],)).fetchall()
    conn.close()

    persons = [{"id": r["id"], "name": r["name"],
                "thumb_url": f"/api/face_thumb/{r['face_id']}"} for r in rows]
    return jsonify({"persons": persons})


# ── 统计 API ──────────────────────────────────────────────

@app.route("/api/stats")
@require_auth
def stats():
    conn = get_db()
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    screenshots = c.execute("SELECT COUNT(*) FROM photos WHERE is_screenshot=1").fetchone()[0]
    duplicates = c.execute("SELECT COUNT(*) FROM photos WHERE is_duplicate=1").fetchone()[0]
    persons = c.execute("SELECT COUNT(*) FROM persons WHERE name IS NOT NULL").fetchone()[0]
    faces = c.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    dirs = c.execute("SELECT path, label, file_count, last_scan FROM directories").fetchall()
    conn.close()

    return jsonify({
        "total_photos": total,
        "screenshots": screenshots,
        "duplicates": duplicates,
        "named_persons": persons,
        "total_faces": faces,
        "directories": [{"path": r["path"], "label": r["label"],
                         "file_count": r["file_count"], "last_scan": r["last_scan"]}
                        for r in dirs],
    })


# ── 重复图报告 API ────────────────────────────────────────

@app.route("/api/duplicates")
@require_auth
def duplicates():
    conn = get_db()
    rows = conn.execute("""
        SELECT hash, paths, count FROM duplicate_groups
        WHERE count > 1 ORDER BY count DESC LIMIT 100
    """).fetchall()
    conn.close()
    result = [{"hash": r["hash"][:8], "count": r["count"],
               "paths": json.loads(r["paths"])} for r in rows]
    return jsonify({"groups": result, "total": len(result)})


# ── 目录管理 API ──────────────────────────────────────────

@app.route("/api/directories", methods=["GET"])
@require_auth
def list_directories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM directories ORDER BY added_at DESC").fetchall()
    conn.close()
    return jsonify({"directories": [dict(r) for r in rows]})


# ── 健康检查 ──────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "db": DB_PATH})


# ── 主入口 ────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./photomemory.db")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--token", default=os.environ.get("PM_TOKEN", ""),
                        help="访问 token（留空则不验证，适合纯局域网）")
    args = parser.parse_args()

    DB_PATH = os.path.abspath(args.db)
    ACCESS_TOKEN = args.token or None

    print(f"🚀 PhotoMemory API 启动")
    print(f"   DB    : {DB_PATH}")
    print(f"   URL   : http://localhost:{args.port}")
    if ACCESS_TOKEN:
        print(f"   Token : {ACCESS_TOKEN}")
        print(f"   Auth  : ✅ Bearer Token 已启用")
    else:
        print(f"   Auth  : ⚠️  未设置 token，局域网开放访问")
    app.run(host=args.host, port=args.port, debug=False)
