"""
photos 相关后端路由模块。
负责 /api/photos 等图片相关接口
"""
from flask import Blueprint, jsonify, request, abort, send_file
from backend.api_server import require_auth, get_db
from backend.cache_util import cached
import os
from pathlib import Path
import io
from datetime import datetime

photos_bp = Blueprint('photos', __name__)

@photos_bp.route("/api/photos/<int:photo_id>/favorite", methods=["POST"])
@require_auth
def toggle_favorite(photo_id):
    """收藏或取消收藏图片"""
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

@photos_bp.route("/api/favorites", methods=["GET"])
@require_auth
def get_favorites():
    """获取所有收藏的图片"""
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    conn = get_db()
    c = conn.cursor()
    fav_rows = c.execute(
        "SELECT f.photo_id, p.* FROM favorites f JOIN photos p ON f.photo_id=p.id ORDER BY f.created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    total = c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
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
