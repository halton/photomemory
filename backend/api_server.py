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

# ── Device Pairing 认证（类 OpenClaw 方案）─────────────────
#
# 流程:
#   1. 客户端 POST /api/pair/request {device_id, device_name}
#   2. 服务端存入 pending，管理员调 POST /api/pair/approve 审批
#   3. 审批后颁发绑定 device_id 的 token
#   4. 后续请求 Header: Authorization: Bearer <token>
#                        X-Device-ID: <device_id>
#      缺任意一个或 device_id 不匹配 → 401
#
# 管理员用 ADMIN_TOKEN 调审批/列表/吊销接口。
# ADMIN_TOKEN 通过 --admin-token 或 PM_ADMIN_TOKEN 环境变量设置。
# 未设置任何 token 时，本地开放访问。

ADMIN_TOKEN = None           # 管理员 token（审批设备用）
PAIRING_ENABLED = False      # 启动时根据 --admin-token 自动开启
SESSION_COOKIE = "pm_session"
SESSION_TTL_HOURS = 720      # 30天 cookie

# 设备存储（生产可换 JSON 文件持久化；这里内存+文件双写）
_DEVICES_FILE: Path = None   # 初始化时设置

def _load_devices() -> dict:
    if _DEVICES_FILE and _DEVICES_FILE.exists():
        try:
            return json.loads(_DEVICES_FILE.read_text())
        except Exception:
            pass
    return {"paired": {}, "pending": {}}

def _save_devices(data: dict):
    if _DEVICES_FILE:
        _DEVICES_FILE.write_text(json.dumps(data, indent=2, default=str))

# 内存缓存（启动时从文件加载）
_devices: dict = {"paired": {}, "pending": {}}

# Session cookie → device_id 映射（内存，重启失效）
_sessions = {}   # session_id → (device_id, expiry)


def _get_request_device_id():
    return (request.headers.get("X-Device-ID") or
            request.args.get("device_id") or
            request.cookies.get("pm_device_id"))

def _check_auth():
    """验证请求。返回 (ok, device_id|'open')"""
    if not PAIRING_ENABLED:
        return True, "open"

    # 1. Session cookie（浏览器登录后免重输）
    sid = request.cookies.get(SESSION_COOKIE, "")
    if sid and sid in _sessions:
        did, expiry = _sessions[sid]
        if datetime.now() < expiry:
            return True, did
        else:
            _sessions.pop(sid, None)

    # 2. Bearer token + device_id（API / 原生客户端）
    auth = request.headers.get("Authorization", "")
    device_id = _get_request_device_id()
    if auth.startswith("Bearer ") and device_id:
        token = auth[7:]
        paired = _devices["paired"].get(device_id)
        if paired and paired.get("status") == "active":
            if secrets.compare_digest(token, paired["token"]):
                return True, device_id

    # 3. URL query 参数 token + device_id（<img src> 等无法带 header 的场景）
    url_token = request.args.get("_t", "")
    url_did   = request.args.get("_d", "")
    if url_token and url_did:
        paired = _devices["paired"].get(url_did)
        if paired and paired.get("status") == "active":
            if secrets.compare_digest(url_token, paired["token"]):
                return True, url_did

    return False, ""

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        ok, _ = _check_auth()
        if not ok:
            return jsonify({"error": "Unauthorized", "code": 401}), 401
        return f(*args, **kwargs)
    return wrapper

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not ADMIN_TOKEN:
            return jsonify({"error": "Admin not configured"}), 403
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
            return jsonify({"error": "Forbidden"}), 403
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

# ── Pairing 接口 ──────────────────────────────────────────

@app.route("/api/pair/request", methods=["POST"])
def pair_request():
    """设备申请配对（任何人可调，不需认证）"""
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    device_name = data.get("device_name", "Unknown Device").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if not PAIRING_ENABLED:
        return jsonify({"error": "Pairing not enabled"}), 503

    # 已配对直接返回（重复申请幂等）
    if device_id in _devices["paired"]:
        d = _devices["paired"][device_id]
        if d.get("status") == "active":
            return jsonify({"status": "already_paired", "device_id": device_id})
        elif d.get("status") == "revoked":
            return jsonify({"status": "revoked", "message": "此设备已被吊销"}), 403

    # 已在 pending 中
    if device_id in _devices["pending"]:
        return jsonify({"status": "pending", "message": "等待管理员审批"})

    # 新申请
    _devices["pending"][device_id] = {
        "device_id": device_id,
        "device_name": device_name,
        "requested_at": datetime.now().isoformat(),
        "ip": request.remote_addr,
    }
    _save_devices(_devices)
    print(f"[Pairing] 新设备申请: {device_name} ({device_id}) from {request.remote_addr}")
    print(f"[Pairing] 审批命令: curl -X POST http://localhost:8765/api/pair/approve "
          f"-H 'Authorization: Bearer <admin_token>' -d '{{\"device_id\":\"{device_id}\"}}'")
    return jsonify({"status": "pending", "message": "申请已提交，等待管理员审批"})


@app.route("/api/pair/status", methods=["GET"])
def pair_status():
    """客户端轮询自己的配对状态"""
    device_id = _get_request_device_id()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if not PAIRING_ENABLED:
        return jsonify({"status": "open"})
    if device_id in _devices["pending"]:
        return jsonify({"status": "pending"})
    if device_id in _devices["paired"]:
        d = _devices["paired"][device_id]
        if d["status"] == "active":
            # 颁发 token（只在 status 轮询时返回一次，之后 token 已在 paired 记录）
            return jsonify({"status": "approved", "token": d["token"]})
        elif d["status"] == "revoked":
            return jsonify({"status": "revoked"}), 403
    return jsonify({"status": "not_found"}), 404


@app.route("/api/pair/approve", methods=["POST"])
@require_admin
def pair_approve():
    """管理员审批设备（需 admin token）"""
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if device_id not in _devices["pending"]:
        return jsonify({"error": "device not found in pending"}), 404

    pending = _devices["pending"].pop(device_id)
    token = secrets.token_urlsafe(32)
    _devices["paired"][device_id] = {
        **pending,
        "token": token,
        "status": "active",
        "approved_at": datetime.now().isoformat(),
    }
    _save_devices(_devices)
    print(f"[Pairing] ✅ 已批准: {pending['device_name']} ({device_id})")
    return jsonify({"ok": True, "device_id": device_id, "device_name": pending["device_name"]})


@app.route("/api/pair/revoke", methods=["POST"])
@require_admin
def pair_revoke():
    """管理员吊销设备"""
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    if device_id in _devices["paired"]:
        _devices["paired"][device_id]["status"] = "revoked"
        _save_devices(_devices)
        return jsonify({"ok": True})
    return jsonify({"error": "device not found"}), 404


@app.route("/api/pair/list", methods=["GET"])
@require_admin
def pair_list():
    """管理员查看所有设备"""
    def safe(d):
        return {k: v for k, v in d.items() if k != "token"}
    return jsonify({
        "pending": [safe(v) for v in _devices["pending"].values()],
        "paired":  [safe(v) for v in _devices["paired"].values()],
    })


@app.route("/api/auth_check")
def auth_check():
    ok, device_id = _check_auth()
    if not PAIRING_ENABLED:
        return jsonify({"authenticated": True, "mode": "open"})
    if ok:
        return jsonify({"authenticated": True, "mode": "paired", "device_id": device_id})
    return jsonify({"authenticated": False, "mode": "pairing"}), 401


@app.route("/api/login", methods=["POST"])
def login():
    """浏览器配对：提交 token+device_id 换取 session cookie"""
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    token = data.get("token", "").strip()
    if not PAIRING_ENABLED:
        return jsonify({"ok": True})
    if not device_id or not token:
        return jsonify({"error": "device_id and token required"}), 400
    paired = _devices["paired"].get(device_id)
    if not paired or paired.get("status") != "active":
        return jsonify({"error": "Device not approved"}), 401
    if not secrets.compare_digest(token, paired["token"]):
        return jsonify({"error": "Invalid token"}), 401
    # 颁发 session cookie
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = (device_id, datetime.now() + timedelta(hours=SESSION_TTL_HOURS))
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL_HOURS * 3600,
                    httponly=True, samesite="Lax")
    resp.set_cookie("pm_device_id", device_id, max_age=SESSION_TTL_HOURS * 3600,
                    samesite="Lax")
    return resp

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
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./photomemory.db")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--admin-token", default=os.environ.get("PM_ADMIN_TOKEN", ""),
                        help="管理员 token（审批/吊销设备用）；设置后自动启用 Pairing 认证")
    args = parser.parse_args()

    DB_PATH = os.path.abspath(args.db)
    _admin = args.admin_token or None
    _pairing = bool(_admin)

    # 更新模块级变量（供装饰器/函数使用）
    import __main__ as _m
    _m.ADMIN_TOKEN = _admin
    _m.PAIRING_ENABLED = _pairing
    _m.DB_PATH = DB_PATH
    globals()['ADMIN_TOKEN'] = _admin
    globals()['PAIRING_ENABLED'] = _pairing
    globals()['DB_PATH'] = DB_PATH

    # 设备持久化文件（与 DB 同目录）
    _DEVICES_FILE = Path(DB_PATH).parent / "photomemory_devices.json"
    globals()['_DEVICES_FILE'] = _DEVICES_FILE
    _devices.update(_load_devices())

    print(f"🚀 PhotoMemory API 启动")
    print(f"   DB    : {DB_PATH}")
    print(f"   URL   : http://localhost:{args.port}")
    if PAIRING_ENABLED:
        print(f"   Auth  : ✅ Device Pairing 已启用")
        print(f"   Admin : {ADMIN_TOKEN}")
        print(f"   设备数: {len(_devices['paired'])} 已配对, {len(_devices['pending'])} 待审批")
    else:
        print(f"   Auth  : ⚠️  未设置 --admin-token，开放访问")
    app.run(host=args.host, port=args.port, debug=False)
