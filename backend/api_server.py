#!/usr/bin/env python3
"""
PhotoMemory - Phase 3: API Server
启动: python3 api_server.py --db ./photomemory.db --port 8765 [--token YOUR_TOKEN]
"""

import os
import sys
import io
import json
import sqlite3

# Ensure project root is on sys.path for 'backend.*' imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def set_sqlite_pragmas(conn):
    """
    性能优化：统一设置 WAL 模式及核心参数。
    可重复调用，无副作用。
    """
    c = conn.cursor()
    try:
        # WAL模式，允许高并发读写
        c.execute('PRAGMA journal_mode=WAL;')
        # NORMAL同步模式，大幅降低写入延迟，WAL模式安全性适中
        c.execute('PRAGMA synchronous=NORMAL;')
        # 中间结果存在内存临时表
        c.execute('PRAGMA temp_store=MEMORY;')
        # 提高页面缓存，单位为page，负值代表 KB
        c.execute('PRAGMA cache_size=-20000;')  # ~20MB
        # 启用256MB mmap（物理内存足够时提升查询/遍历性能）
        c.execute('PRAGMA mmap_size=268435456;')
    except Exception as e:
        # PRAGMA 调用失败时忽略，不影响主流程
        pass

import argparse
import subprocess
import tempfile
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import threading

from flask import Flask, jsonify, request, send_file, abort, make_response, redirect
from flask_cors import CORS

import pillow_heif
from backend.cache_util import cached
pillow_heif.register_heif_opener()
from PIL import Image

# ==== 认证与设备管理提取到 backend/auth ==== #
from backend.auth.pairing import load_devices, save_devices, get_request_device_id
from backend.auth.middleware import require_auth, require_admin

ADMIN_TOKEN = None           # 管理员 token（审批设备用）
PAIRING_ENABLED = False      # 启动时根据 --admin-token 自动开启

# 人脸扫描进度（线程共享）
_face_scan_state: dict = {"running": False, "total": 0, "processed": 0, "error": None}
SESSION_COOKIE = "pm_session"
SESSION_TTL_HOURS = 720      # 30天 cookie

_face_scan_state = {"running": False, "total": 0, "processed": 0, "error": None}

# 设备存储（生产可换 JSON 文件持久化；这里内存+文件双写）
_DEVICES_FILE: Path = None   # 初始化时设置

# 内存缓存（启动时从文件加载）
_devices: dict = {"paired": {}, "pending": {}}

# Session cookie → device_id 映射（内存，重启失效）
_sessions = {}   # session_id → (device_id, expiry)


# 地名别名辅助由 services.geocode 提供
from backend.services.geocode import CITY_ALIASES

VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp'}

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")
# 限制 CORS 来源（生产环境应配置具体域名）
CORS(app, origins=["http://localhost:*", "https://localhost:*"], supports_credentials=True)

@app.before_request
def force_https():
    """HTTP 访问强制跳转到 HTTPS（反向代理模式下看 X-Forwarded-Proto）"""
    proto = request.headers.get("X-Forwarded-Proto", "")
    if proto == "http":
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)

@app.route("/")
def index():
    resp = app.send_static_file("index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

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
            # 允许吊销后重新申请：从 paired 移除，进入 pending
            del _devices["paired"][device_id]
            # 继续走下面的新申请逻辑

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
    from backend.auth.pairing import save_devices
    save_devices(_DEVICES_FILE, _devices)
    print(f"[Pairing] 新设备申请: {device_name} ({device_id}) from {request.remote_addr}")
    print(f"[Pairing] 审批命令: curl -X POST http://localhost:8765/api/pair/approve "
          f"-H 'Authorization: Bearer <admin_token>' -d '{{\"device_id\":\"{device_id}\"}}'")
    return jsonify({"status": "pending", "message": "申请已提交，等待管理员审批"})


@app.route("/api/pair/status", methods=["GET"])
def pair_status():
    """客户端轮询自己的配对状态"""
    from backend.auth.pairing import get_request_device_id
    device_id = get_request_device_id()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if not PAIRING_ENABLED:
        return jsonify({"status": "open"})
    if device_id in _devices["pending"]:
        return jsonify({"status": "pending"})
    if device_id in _devices["paired"]:
        d = _devices["paired"][device_id]
        if d["status"] == "active":
            # 安全修复：token 只在首次轮询返回一次，之后不再返回
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
        "token_delivered": False,
    }
    from backend.auth.pairing import save_devices
    save_devices(_DEVICES_FILE, _devices)
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
        save_devices(_DEVICES_FILE, _devices)
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


@app.route("/auto-login/<device_id>/<token>")
def auto_login(device_id, token):
    """自动登录：把 device_id 和 token 注入 localStorage 然后跳首页"""
    # 验证 device_id 确实是已配对的设备
    paired = _devices.get("paired", {})
    dev = paired.get(device_id)
    if not dev or dev.get("status") != "active" or dev.get("token") != token:
        return "Invalid or expired login link", 403
    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>PhotoMemory</title></head>
<body style="background:#111;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:16px">
<div style="font-size:48px">📸</div><h2>正在登录...</h2>
<script>
localStorage.setItem('pm_device_id','{device_id}');
localStorage.setItem('pm_token','{token}');
setTimeout(()=>{{window.location.href='/';}},500);
</script></body></html>"""
    return html


@app.route("/reset-auth")
def reset_auth_page():
    """清除浏览器 localStorage/cookie 中的配对凭证，强制重新配对"""
    html = """
<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Reset Auth - PhotoMemory</title>
<style>body{background:#111;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}</style>
</head><body>
<div style="text-align:center">
  <div style="font-size:48px">🔄</div>
  <h2>正在清除凭证...</h2>
  <p style="color:#888">清除后自动跳转到配对页面</p>
</div>
<script>
  ['pm_device_id','pm_token'].forEach(k => {
    localStorage.removeItem(k);
    document.cookie = k + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
  });
  setTimeout(() => { window.location.href = '/'; }, 1000);
</script>
</body></html>
"""
    return html


@app.route("/admin")
def admin_page():
    """管理界面：必须提供 admin token 才能访问页面"""
    # 支持 URL 参数 ?token=xxx 或 Authorization: Bearer xxx
    token = request.args.get("token", "") or \
            request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not PAIRING_ENABLED or not ADMIN_TOKEN:
        pass  # 未启用认证时放行
    elif not token or not secrets.compare_digest(token, ADMIN_TOKEN):
        return '''<!DOCTYPE html><html><body style="background:#0f0f0f;color:#666;
            display:flex;align-items:center;justify-content:center;height:100vh;
            font-family:monospace;flex-direction:column">
            <div style="font-size:48px">🔒</div>
            <div style="margin:16px 0;color:#fff">需要管理员权限</div>
            <div style="font-size:13px">访问 /admin?token=YOUR_ADMIN_TOKEN</div>
            </body></html>''', 403
    admin_path = os.path.join(FRONTEND_DIR, "admin.html")
    return send_file(admin_path)


@app.route("/api/auth_check")
def auth_check():
    from backend.auth.middleware import check_auth
    ok, device_id = check_auth()
    if not PAIRING_ENABLED:
        return jsonify({"authenticated": True, "mode": "open"})
    if ok:
        return jsonify({"authenticated": True, "mode": "paired", "device_id": device_id})
    return jsonify({"authenticated": False, "mode": "pairing"})  # 始终 200，前端判断字段


@app.route("/api/login", methods=["POST"])
def login():
    """保留兼容接口（无状态模式下直接返回 ok）"""
    if not PAIRING_ENABLED:
        return jsonify({"ok": True})
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    token = data.get("token", "").strip()
    if not device_id or not token:
        return jsonify({"error": "device_id and token required"}), 400
    paired = _devices["paired"].get(device_id)
    if not paired or paired.get("status") != "active":
        return jsonify({"error": "Device not approved"}), 401
    if not secrets.compare_digest(token, paired["token"]):
        return jsonify({"error": "Invalid token"}), 401
    return jsonify({"ok": True})


@app.route("/api/pair/reject", methods=["POST"])
@require_admin
def pair_reject():
    """管理员拒绝待审批设备"""
    data = request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    if device_id in _devices["pending"]:
        _devices["pending"].pop(device_id)
        save_devices(_DEVICES_FILE, _devices)
        return jsonify({"ok": True})
    return jsonify({"error": "device not found in pending"}), 404

DB_PATH = None

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.bmp', '.tiff', '.gif', '.webp'}

# ── DB Helper ─────────────────────────────────────────────

def _ensure_tables():
    """在启动时确保必要的表存在（Phase 2 可能还没跑）"""
    conn = sqlite3.connect(DB_PATH)
    set_sqlite_pragmas(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS faces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id    INTEGER,
            photo_path  TEXT,
            bbox        TEXT,
            landmark    TEXT,
            det_score   REAL,
            embedding   BLOB,
            person_id   INTEGER,
            detected_at TEXT
        );
        CREATE TABLE IF NOT EXISTS persons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT,
            alias       TEXT,
            embedding_centroid BLOB,
            face_count  INTEGER DEFAULT 0,
            created_at  TEXT,
            updated_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_persons_id ON persons(id);  # 快速 id 检索
        CREATE TABLE IF NOT EXISTS directories (
            path TEXT PRIMARY KEY,
            label TEXT,
            file_count INTEGER DEFAULT 0,
            last_scan TEXT
        );
        CREATE TABLE IF NOT EXISTS duplicate_groups (
            hash TEXT PRIMARY KEY,
            paths TEXT,
            count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            cover_photo_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS album_photos (
            album_id INTEGER NOT NULL,
            photo_id INTEGER NOT NULL,
            sort_order INTEGER DEFAULT 0,
            PRIMARY KEY (album_id, photo_id)
        );
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            album_id INTEGER,
            photo_ids TEXT,
            expires_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS favorites (
            photo_id INTEGER PRIMARY KEY,
            created_at TEXT
        );
    """)
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    set_sqlite_pragmas(conn)
    conn.row_factory = sqlite3.Row
    return conn


# ── 收藏/喜欢 API ────────────────────────────────────────

@app.route("/api/photos/<int:photo_id>/favorite", methods=["POST"])
@require_auth
def toggle_favorite(photo_id):
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT 1 FROM favorites WHERE photo_id=?", (photo_id,)).fetchone()
    if row:
        cur.execute("DELETE FROM favorites WHERE photo_id=?", (photo_id,))
        conn.commit()
        conn.close()
        return jsonify({"favorited": False})
    else:
        cur.execute(
            "INSERT INTO favorites (photo_id, created_at) VALUES (?, ?)",
            (photo_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({"favorited": True})

@app.route("/api/favorites", methods=["GET"])
@require_auth
def get_favorites():
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    conn = get_db()
    c = conn.cursor()
    fav_rows = c.execute(
        "SELECT f.photo_id, p.* FROM favorites f JOIN photos p ON f.photo_id=p.id ORDER BY f.created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    total = c.execute(
        "SELECT COUNT(*) FROM favorites"
    ).fetchone()[0]
    results = []
    for r in fav_rows:
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
            "size": r["size"],
            "thumb_url": f"/api/thumb/{r['id']}",
            "original_url": f"/api/photo/{r['id']}",
            "is_favorite": True,
        })
    conn.close()
    return jsonify({"results": results, "total": total, "limit": limit, "offset": offset})

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
      has_person - true/false（只返回有人脸/无人脸）
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

    # 查询所有结果的id对应的收藏状态
    photo_ids = [r["id"] for r in rows]
    fav_set = set()
    if photo_ids:
        qmark = ','.join(['?'] * len(photo_ids))
        rows_fav = c.execute(f"SELECT photo_id FROM favorites WHERE photo_id IN ({qmark})", photo_ids).fetchall()
        fav_set = set(row["photo_id"] for row in rows_fav)

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
            "is_favorite": r["id"] in fav_set
        })

    conn.close()
    return jsonify({"results": results, "total": total, "limit": limit, "offset": offset})


# 2026/04/14: 可进一步服务化到 geocode.py (暂保留)
def _is_person_query(q: str, c) -> bool:
    """判断查询词是否命中已知人名"""
    row = c.execute("SELECT id FROM persons WHERE name LIKE ?", (f"%{q}%",)).fetchone()
    return row is not None


# ── 缩略图 API ────────────────────────────────────────────

@app.route("/api/thumb/<int:photo_id>")
@require_auth
def thumbnail(photo_id):
    """
    缩略图接口：根据 photo_id 返回图片或视频缩略图。包含本地缓存，兼容原行为。
    """
    from backend.services.thumbnail import generate_image_thumbnail, generate_video_thumbnail, placeholder_thumbnail
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
        try:
            data = generate_video_thumbnail(path, size)
            return send_file(io.BytesIO(data), mimetype="image/jpeg")
        except Exception:
            data = placeholder_thumbnail(size, "🎬")
            return send_file(io.BytesIO(data), mimetype="image/jpeg")

    # 缩略图本地缓存
    cache_dir = Path(DB_PATH).parent / "thumbs"
    cache_dir.mkdir(exist_ok=True)
    try:
        mtime = int(os.path.getmtime(path))
    except Exception:
        mtime = 0
    cache_file = cache_dir / f"{photo_id}_{size}_{mtime}.jpg"
    if cache_file.exists():
        return send_file(str(cache_file), mimetype="image/jpeg")

    # 生成图片缩略图，异常兜底占位
    try:
        data = generate_image_thumbnail(path, size)
        try:
            cache_file.write_bytes(data)
        except Exception:
            pass
        return send_file(io.BytesIO(data), mimetype="image/jpeg")
    except Exception as e:
        from traceback import print_exc
        print(f"[THUMB ERROR] photo_id={photo_id} path={path} error={e}")
        print_exc()
        data = placeholder_thumbnail(size)
        return send_file(io.BytesIO(data), mimetype="image/jpeg")



# 2026/04/14 提取到 backend/services/thumbnail.py

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
               -- 选 det_score 最高的脸作为代表头像
               (SELECT f2.id FROM faces f2
                WHERE f2.person_id = p.id
                ORDER BY f2.det_score DESC LIMIT 1) as sample_face_id
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


@app.route("/api/persons/<int:person_id>/photos")
@require_auth
def person_photos(person_id):
    """返回某个人物的所有照片（带缩略图）"""
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT p.id, p.path, p.taken_at, p.gps_city
        FROM photos p
        JOIN faces f ON f.photo_id = p.id
        WHERE f.person_id = ?
        ORDER BY p.taken_at DESC
    """, (person_id,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "thumb_url": f"/api/thumb/{r['id']}",
            "photo_url": f"/api/photo/{r['id']}",
            "taken_at": r["taken_at"],
            "city": r["gps_city"],
        })
    return jsonify({"photos": results, "total": len(results)})


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
@require_auth
def face_thumbnail(face_id):
    conn = get_db()
    row = conn.execute("SELECT photo_path, bbox, person_id FROM faces WHERE id=?", (face_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)

    def crop_face(photo_path, bbox_json, pad=30):
        from PIL import ImageOps
        img = ImageOps.exif_transpose(Image.open(photo_path))  # 先旋转（与 phase2 检测一致）
        bbox = json.loads(bbox_json)
        x1, y1, x2, y2 = [int(v) for v in bbox]
        w, h = img.size
        x1 = max(0, x1-pad); y1 = max(0, y1-pad)
        x2 = min(w, x2+pad); y2 = min(h, y2+pad)
        face = img.crop((x1, y1, x2, y2))
        return face

    try:
        face = crop_face(row["photo_path"], row["bbox"])

        # 亮度检测：若太暗，从同人物其他脸中找更亮的
        import statistics
        thumb_check = face.copy(); thumb_check.thumbnail((50, 50))
        brightness = statistics.mean(thumb_check.convert('L').getdata())

        if brightness < 40 and row["person_id"]:
            conn2 = get_db()
            others = conn2.execute(
                "SELECT photo_path, bbox FROM faces WHERE person_id=? AND id!=? ORDER BY det_score DESC LIMIT 10",
                (row["person_id"], face_id)
            ).fetchall()
            conn2.close()
            best_face, best_brightness = face, brightness
            for other in others:
                try:
                    f2 = crop_face(other["photo_path"], other["bbox"])
                    t2 = f2.copy(); t2.thumbnail((50,50))
                    b2 = statistics.mean(t2.convert('L').getdata())
                    if b2 > best_brightness:
                        best_brightness = b2
                        best_face = f2
                        if b2 > 60:  # 够亮就停
                            break
                except Exception:
                    continue
            face = best_face

        face.thumbnail((150, 150))
        buf = io.BytesIO()
        face.convert("RGB").save(buf, "JPEG", quality=90)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")
    except Exception as e:
        abort(500)


@app.route("/api/photo_persons/<int:photo_id>")
@require_auth
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

@app.route("/api/stats/timeline", methods=["GET"])
@require_auth
@cached(ttl=60)
def stats_timeline():
    """返回按月统计的照片数量"""
    try:
        conn = get_db()
        c = conn.cursor()
        rows = c.execute("""
            SELECT strftime('%Y-%m', taken_at) as month, COUNT(*) as count
            FROM photos
            GROUP BY month
            ORDER BY month ASC
        """).fetchall()
        conn.close()
        result = [{"month": r["month"], "count": r["count"]} for r in rows if r["month"]]
        return jsonify(result)
    except Exception as e:
        print(f"[stats_timeline] error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats/persons", methods=["GET"])
@require_auth
@cached(ttl=60)
def stats_persons():
    """返回人物照片数量排行"""
    try:
        conn = get_db()
        c = conn.cursor()
        rows = c.execute("""
            SELECT p.id, p.name, COUNT(f.id) as count
            FROM persons p
            JOIN faces f ON f.person_id = p.id
            WHERE p.name IS NOT NULL
            GROUP BY p.id
            ORDER BY count DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        result = [
            {"id": r["id"], "name": r["name"], "count": r["count"]}
            for r in rows if r["name"] is not None
        ]
        return jsonify(result)
    except Exception as e:
        print(f"[stats_persons] error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/photos/random", methods=["GET"])
@require_auth
def photos_random():
    """随机返回N张照片"""
    try:
        limit = int(request.args.get("limit", 9))
        limit = max(1, min(limit, 50))
        conn = get_db()
        c = conn.cursor()
        rows = c.execute("""
            SELECT p.id, p.path, p.filename, p.taken_at,
                   p.gps_lat, p.gps_lon, p.gps_city,
                   p.width, p.height, p.is_screenshot, p.is_duplicate,
                   p.dir_label, p.size
            FROM photos p
            ORDER BY RANDOM()
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
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
                "original_url": f"/api/photo/{r['id']}"
            })
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        print(f"[photos_random] error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
@require_auth
@cached(ttl=60)
@cached(ttl=60)
def stats():
    conn = get_db()
    c = conn.cursor()

    def safe_count(sql):
        try:
            return c.execute(sql).fetchone()[0]
        except Exception:
            return 0

    total = safe_count("SELECT COUNT(*) FROM photos")
    screenshots = safe_count("SELECT COUNT(*) FROM photos WHERE is_screenshot=1")
    duplicates = safe_count("SELECT COUNT(*) FROM photos WHERE is_duplicate=1")
    persons = safe_count("SELECT COUNT(*) FROM persons WHERE name IS NOT NULL")
    faces = safe_count("SELECT COUNT(*) FROM faces")
    try:
        dirs = c.execute("SELECT path, label, file_count, last_scan FROM directories").fetchall()
    except Exception:
        dirs = []
    conn.close()

    return jsonify({
        "total_photos": total,
        "screenshots": screenshots,
        "duplicates": duplicates,
        "persons": persons,
        "faces": faces,
        "cities_count": 0,
    })


@app.route("/api/photos/map", methods=["GET"])
@require_auth
def photos_map():
    """返回所有有GPS坐标的照片"""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, gps_lat, gps_lon, taken_at, filename, gps_city
        FROM photos
        WHERE gps_lat IS NOT NULL AND gps_lat != 0
        """
    ).fetchall()
    markers = []
    for r in rows:
        markers.append({
            "id": r["id"],
            "lat": r["gps_lat"],
            "lon": r["gps_lon"],
            "taken_at": r["taken_at"],
            "filename": r["filename"],
            "city": r["gps_city"],
            "thumb_url": f"/api/thumb/{r['id']}"
        })
    conn.close()
    return jsonify({"markers": markers})


@app.route("/api/stats/locations", methods=["GET"])
@require_auth
@cached(ttl=60)
def stats_locations():
    """按城市分组统计"""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT gps_city, COUNT(*) as cnt, AVG(gps_lat) as lat, AVG(gps_lon) as lon
        FROM photos
        WHERE gps_city IS NOT NULL AND gps_city != ""
        GROUP BY gps_city
        ORDER BY cnt DESC
        """
    ).fetchall()
    ret = []
    for r in rows:
        ret.append({
            "city": r["gps_city"],
            "count": r["cnt"],
            "lat": r["lat"],
            "lon": r["lon"]
        })
    conn.close()
    return jsonify({"locations": ret})


@app.route("/api/photos/random", methods=["GET"])
@require_auth
def api_photos_random():
    """随机返回N张照片"""
    try:
        limit = int(request.args.get("limit", 9))
        limit = max(1, min(limit, 50))
        conn = get_db()
        c = conn.cursor()
        rows = c.execute(
            """
            SELECT * FROM photos WHERE is_screenshot=0 ORDER BY RANDOM() LIMIT ?
            """, (limit,)).fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({key: r[key] for key in r.keys()})
            results[-1]["thumb_url"] = f"/api/thumb/{r['id']}"
            results[-1]["original_url"] = f"/api/photo/{r['id']}"
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        print(f"[api_photos_random] error: {e}")
        return jsonify({"error": str(e)}), 500


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


# ── 删除照片 API ──────────────────────────────────────────

@app.route("/api/photos/<int:photo_id>", methods=["DELETE"])
@require_auth
def delete_photo(photo_id):
    conn = get_db()
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute("DELETE FROM faces WHERE photo_id=?", (photo_id,))
    conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": photo_id})


# ── 删除人物 API ──────────────────────────────────────────

@app.route("/api/persons/<int:person_id>", methods=["DELETE"])
@require_auth
def delete_person(person_id):
    conn = get_db()
    # 取消 faces 关联，但保留 faces 记录（便于重新聚类）
    conn.execute("UPDATE faces SET person_id=NULL WHERE person_id=?", (person_id,))
    conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": person_id})


# ── 一键清理 API ──────────────────────────────────────────

@app.route("/api/cleanup/duplicates", methods=["POST"])
@require_admin
def cleanup_duplicates():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM photos WHERE is_duplicate=1").fetchone()[0]
    conn.execute("DELETE FROM faces WHERE photo_id IN (SELECT id FROM photos WHERE is_duplicate=1)")
    conn.execute("DELETE FROM photos WHERE is_duplicate=1")
    conn.commit()
    conn.close()
    return jsonify({"deleted": count})


@app.route("/api/cleanup/screenshots", methods=["POST"])
@require_admin
def cleanup_screenshots():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM photos WHERE is_screenshot=1").fetchone()[0]
    conn.execute("DELETE FROM faces WHERE photo_id IN (SELECT id FROM photos WHERE is_screenshot=1)")
    conn.execute("DELETE FROM photos WHERE is_screenshot=1")
    conn.commit()
    conn.close()
    return jsonify({"deleted": count})


# ── 增量人脸扫描 API ──────────────────────────────────────

@app.route("/api/face_scan", methods=["POST"])
@require_auth
def start_face_scan():
    global _face_scan_state
    if _face_scan_state["running"]:
        return jsonify({"status": "already_running",
                        "processed": _face_scan_state["processed"],
                        "total": _face_scan_state["total"]})

    db_path = DB_PATH
    conn = get_db()
    IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.heic', '.heif', '.bmp', '.tiff', '.tif')
    already = {r[0] for r in conn.execute("SELECT DISTINCT photo_id FROM faces").fetchall()}
    all_photos = conn.execute("SELECT id, path FROM photos WHERE is_screenshot=0").fetchall()
    pending = [(pid, path) for pid, path in all_photos
               if pid not in already and Path(path).suffix.lower() in IMAGE_EXTS]
    conn.close()

    _face_scan_state = {"running": True, "total": len(pending), "processed": 0, "error": None}

    def run_scan():
        global _face_scan_state
        import sys
        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        try:
            from phase2_faces import detect_faces, cluster_faces
            detect_faces(db_path)
            cluster_faces(db_path)
        except Exception as e:
            _face_scan_state["error"] = str(e)
        finally:
            _face_scan_state["running"] = False

    t = threading.Thread(target=run_scan, daemon=True)
    t.start()
    return jsonify({"status": "started", "new_photos": len(pending)})


@app.route("/api/face_scan/status", methods=["GET"])
@require_auth
def face_scan_status():
    return jsonify(_face_scan_state)


# ── 健康检查 ──────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "db": DB_PATH})


# ── 主入口 ────────────────────────────────────────────────

# 相册API
@app.route("/api/albums", methods=["GET"])
@require_auth
def list_albums():
    conn = get_db()
    q = '''SELECT a.id, a.name, a.description, a.created_at, a.updated_at,
                  COUNT(ap.photo_id) as photo_count,
                  a.cover_photo_id,
                  (SELECT path FROM photos WHERE id=a.cover_photo_id) as cover_path
           FROM albums a
           LEFT JOIN album_photos ap ON ap.album_id = a.id
           GROUP BY a.id
           ORDER BY a.updated_at DESC, a.created_at DESC'''
    rows = conn.execute(q).fetchall()
    albums = []
    for r in rows:
        thumb_url = f"/api/thumb/{r['cover_photo_id']}" if r['cover_photo_id'] else None
        albums.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "photo_count": r["photo_count"],
            "cover_photo_id": r["cover_photo_id"],
            "cover_thumb": thumb_url,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    conn.close()
    return jsonify({"albums": albums})

@app.route("/api/albums", methods=["POST"])
@require_auth
def create_album():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    desc = data.get("description", "").strip()
    cover_photo_id = data.get("cover_photo_id")
    if not name:
        return jsonify({"error": "name required"}), 400
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO albums (name, description, cover_photo_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)""", (name, desc, cover_photo_id, now, now))
    album_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": album_id, "ok": True})

@app.route("/api/albums/<int:album_id>/photos", methods=["GET"])
@require_auth
def album_photos(album_id):
    conn = get_db()
    q = '''SELECT p.id, p.path, p.filename, p.taken_at, p.gps_city, p.width, p.height, p.size
           FROM album_photos ap
           JOIN photos p ON ap.photo_id = p.id
           WHERE ap.album_id = ?
           ORDER BY ap.sort_order, p.taken_at DESC'''
    rows = conn.execute(q, (album_id,)).fetchall()
    photos = []
    for r in rows:
        photos.append({
            "id": r["id"],
            "filename": r["filename"],
            "taken_at": r["taken_at"],
            "gps_city": r["gps_city"],
            "width": r["width"],
            "height": r["height"],
            "size": r["size"],
            "thumb_url": f"/api/thumb/{r['id']}",
            "original_url": f"/api/photo/{r['id']}"
        })
    conn.close()
    return jsonify({"photos": photos, "total": len(photos)})

@app.route("/api/albums/<int:album_id>/photos", methods=["POST"])
@require_auth
def add_photos_to_album(album_id):
    data = request.get_json() or {}
    ids = data.get("photo_ids") or []
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "photo_ids required"}), 400
    conn = get_db()
    cur = conn.cursor()
    existing = set(row[0] for row in cur.execute(
        "SELECT photo_id FROM album_photos WHERE album_id=?", (album_id,)))
    for idx, pid in enumerate(ids):
        if pid not in existing:
            cur.execute(
                "INSERT OR IGNORE INTO album_photos (album_id, photo_id, sort_order) VALUES (?, ?, ?)",
                (album_id, pid, idx))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/albums/<int:album_id>/photos/<int:photo_id>", methods=["DELETE"])
@require_auth
def remove_photo_from_album(album_id, photo_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM album_photos WHERE album_id=? AND photo_id=?",
        (album_id, photo_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "removed": photo_id})

@app.route("/api/albums/<int:album_id>", methods=["DELETE"])
@require_auth
def delete_album(album_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM album_photos WHERE album_id=?", (album_id,))
    cur.execute("DELETE FROM albums WHERE id=?", (album_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": album_id})

# ── 照片下载/批量下载/分享链接 API ───────────────

from zipfile import ZipFile
import uuid

@app.route("/api/photo/<int:photo_id>/download")
@require_auth
def download_photo(photo_id):
    conn = get_db()
    row = conn.execute("SELECT path, filename FROM photos WHERE id=?", (photo_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    path, filename = row["path"], row["filename"]
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename or f"photo_{photo_id}")

@app.route("/api/photos/download", methods=["POST"])
@require_auth
def batch_download_photos():
    data = request.get_json() or {}
    ids = data.get("photo_ids")
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "photo_ids required"}), 400
    if len(ids) > 50:
        return jsonify({"error": "最多支持50张批量下载"}), 400
    conn = get_db()
    q = f"SELECT id, path, filename FROM photos WHERE id IN ({','.join(['?']*len(ids))})"
    rows = conn.execute(q, ids).fetchall()
    conn.close()
    mem_zip = io.BytesIO()
    with ZipFile(mem_zip, 'w') as zf:
        for r in rows:
            fp = r["path"]
            fname = r["filename"] or f"photo_{r['id']}"
            if os.path.exists(fp):
                # zip内路径去掉文件夹名
                arcname = fname
                try:
                    zf.write(fp, arcname)
                except Exception:
                    continue
    mem_zip.seek(0)
    return send_file(mem_zip, mimetype="application/zip", as_attachment=True, download_name="photos.zip")

@app.route("/api/shares", methods=["POST"])
@require_auth
def create_share():
    data = request.get_json() or {}
    album_id = data.get("album_id")
    photo_ids = data.get("photo_ids")
    expires_hours = int(data.get("expires_hours", 72))
    expires_at = (datetime.now() + timedelta(hours=expires_hours)).isoformat()
    share_id = secrets.token_urlsafe(16)  # 128-bit entropy
    created_at = datetime.now().isoformat()
    conn = get_db()
    if album_id:
        row = conn.execute("SELECT id FROM albums WHERE id=?", (album_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "album_id not found"}), 404
        conn.execute(
            "INSERT INTO shares (id, album_id, expires_at, created_at) VALUES (?,?,?,?)",
            (share_id, album_id, expires_at, created_at)
        )
    elif photo_ids:
        if not isinstance(photo_ids, list):
            return jsonify({"error": "photo_ids must be list"}), 400
        if len(photo_ids) > 200:
            return jsonify({"error": "最多200张照片"}), 400
        conn.execute(
            "INSERT INTO shares (id, photo_ids, expires_at, created_at) VALUES (?,?,?,?)",
            (share_id, json.dumps(photo_ids, ensure_ascii=False), expires_at, created_at)
        )
    else:
        return jsonify({"error": "album_id 或 photo_ids 必须提供"}), 400
    conn.commit()
    conn.close()
    return jsonify({"share_id": share_id,
                    "url": f"/share/{share_id}",
                    "expires_at": expires_at})

@app.route("/api/shares/<share_id>")
def get_share(share_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    expires_at = row["expires_at"]
    if expires_at and datetime.now() > datetime.fromisoformat(expires_at):
        conn.close()
        return ("已经过期", 410)
    if row["album_id"]:
        # 按相册照片取
        a_id = row["album_id"]
        photos = conn.execute(
            """SELECT p.id, p.path, p.filename, p.taken_at, p.gps_city, p.width, p.height, p.size
                FROM album_photos ap JOIN photos p ON ap.photo_id = p.id WHERE ap.album_id=?
                ORDER BY ap.sort_order, p.taken_at DESC""", (a_id,)).fetchall()
    else:
        # 按照片id列表取
        ids = json.loads(row["photo_ids"]) if row["photo_ids"] else []
        if not ids:
            conn.close()
            return jsonify({"results": [], "total": 0})
        q = f"SELECT id, path, filename, taken_at, gps_city, width, height, size FROM photos WHERE id IN ({','.join(['?']*len(ids))})"
        photos = conn.execute(q, ids).fetchall()
    results = []
    for r in photos:
        results.append({
            "id": r["id"],
            "filename": r["filename"],
            "taken_at": r["taken_at"],
            "gps_city": r["gps_city"],
            "width": r["width"],
            "height": r["height"],
            "size": r["size"],
            "thumb_url": f"/api/thumb/{r['id']}",
            "original_url": f"/api/photo/{r['id']}"
        })
    conn.close()
    return jsonify({"results": results, "total": len(results)})

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

    _ensure_tables()

    # 设备持久化文件（与 DB 同目录）
    _DEVICES_FILE = Path(DB_PATH).parent / "photomemory_devices.json"
    globals()['_DEVICES_FILE'] = _DEVICES_FILE
    from backend.auth.pairing import load_devices
    _devices.update(load_devices(_DEVICES_FILE))

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
