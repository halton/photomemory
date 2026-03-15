#!/usr/bin/env python3
"""
PhotoMemory - Phase 3: API Server
启动: python3 api_server.py --db ./photomemory.db --port 8765
"""

import os
import io
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, send_file, abort
from flask_cors import CORS
from PIL import Image

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")
CORS(app)

@app.route("/")
def index():
    return app.send_static_file("index.html")

DB_PATH = None

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.bmp', '.tiff', '.gif', '.webp'}

# ── DB Helper ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 搜索 API ──────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
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

    # 地点文本搜索（GPS城市字段，未来扩展）
    if q and not person_name and not _is_person_query(q, c):
        conditions.append("(p.gps_city LIKE ? OR p.filename LIKE ? OR p.dir_label LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

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
    try:
        img = Image.open(path)
        img.thumbnail((size, size), Image.LANCZOS)
        # 处理 EXIF 旋转
        try:
            from PIL.ExifTags import TAGS
            exif = img._getexif()
            if exif:
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
    except Exception as e:
        abort(500)


# ── 原图 API ──────────────────────────────────────────────

@app.route("/api/photo/<int:photo_id>")
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


# ── 统计 API ──────────────────────────────────────────────

@app.route("/api/stats")
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
    args = parser.parse_args()

    DB_PATH = os.path.abspath(args.db)
    print(f"🚀 PhotoMemory API 启动")
    print(f"   DB  : {DB_PATH}")
    print(f"   URL : http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
