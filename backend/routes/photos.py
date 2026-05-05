"""
photos 相关后端路由模块。
负责 /api/photos 等图片相关接口
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from backend.db import get_db
from backend.schemas.photos import FavoritesResponse, PhotoItem, ToggleFavoriteResponse

router = APIRouter()

@router.post("/api/photos/{photo_id}/favorite", response_model=ToggleFavoriteResponse)
async def toggle_favorite(photo_id: int, db=Depends(get_db)):
    """收藏或取消收藏图片"""
    cur = db.cursor()
    row = cur.execute("SELECT 1 FROM favorites WHERE photo_id=?", (photo_id,)).fetchone()
    if row:
        cur.execute("DELETE FROM favorites WHERE photo_id=?", (photo_id,))
        db.commit()
        return ToggleFavoriteResponse(favorited=False)
    else:
        cur.execute(
            "INSERT INTO favorites (photo_id, created_at) VALUES (?, ?)",
            (photo_id, datetime.now().isoformat())
        )
        db.commit()
        return ToggleFavoriteResponse(favorited=True)

@router.get("/api/favorites", response_model=FavoritesResponse)
async def get_favorites(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db=Depends(get_db)):
    """获取所有收藏的图片"""
    c = db.cursor()
    fav_rows = c.execute(
        "SELECT f.photo_id, p.* FROM favorites f JOIN photos p ON f.photo_id=p.id ORDER BY f.created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    total = c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    results = []
    for r in fav_rows:
        results.append(PhotoItem(
            id=r["id"],
            path=r["path"],
            filename=r["filename"],
            taken_at=r["taken_at"],
            gps_lat=r["gps_lat"],
            gps_lon=r["gps_lon"],
            gps_city=r["gps_city"],
            width=r["width"],
            height=r["height"],
            is_screenshot=bool(r["is_screenshot"]),
            is_duplicate=bool(r["is_duplicate"]),
            dir_label=r["dir_label"],
            size=r["size"],
            thumb_url=f"/api/thumb/{r['id']}",
            original_url=f"/api/photo/{r['id']}",
            is_favorite=True,
        ))
    return FavoritesResponse(results=results, total=total, limit=limit, offset=offset)
