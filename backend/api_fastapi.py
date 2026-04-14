"""
FastAPI 入口，兼容 Flask 启动方案，迁移过程可并行运行。
"""
import os
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.db import get_db, set_db_path, close_db, set_sqlite_pragmas, fetch_one, fetch_all, execute, executescript, ensure_tables
from backend.cache_util import cached
from backend.auth.pairing import load_devices, save_devices, get_request_device_id
from backend.auth.middleware import require_auth, require_admin
from backend.services.geocode import CITY_ALIASES
import pillow_heif
from PIL import Image
import argparse
import secrets

# 项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from typing import AsyncGenerator
from contextlib import asynccontextmanager

# FastAPI lifespan for managing async DB pool
@asynccontextmanager
async def _lifespan(app) -> AsyncGenerator[None, None]:
    import os
    db_path = os.environ.get("PHOTOMEMORY_DB", "./photomemory.db")
    set_async_db_path(db_path)
    set_async_pool_size(5)  # default
    try:
        yield
    finally:
        await close_pool()


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

from backend.db.async_connection import set_async_db_path, set_async_pool_size, close_pool

app = FastAPI(
    lifespan=_lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "https://localhost:*"] ,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def force_https(request: Request, call_next):
    proto = request.headers.get("x-forwarded-proto", "")
    if proto == "http":
        url = str(request.url).replace("http://", "https://", 1)
        return RedirectResponse(url, status_code=301)
    return await call_next(request)

@app.get("/")
async def index():
    frontend_index = Path(FRONTEND_DIR) / "index.html"
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return FileResponse(frontend_index, headers=headers)

# ==== 静态文件与特殊 HTML 路由实现 ====
from fastapi import HTTPException
from fastapi.responses import Response


def get_admin_token():
    """从环境变量或命令行参数读取 admin token（兼容 Flask 行为）"""
    token = os.environ.get("ADMIN_TOKEN")
    # 补充参数注入：可用 argparse 或全局变量，如果有迁移可以进一步完善
    return token

@app.get("/admin")
async def admin_page(request: Request):
    """管理界面：须 admin token，兼容 /admin?token=xxx && Authorization header"""
    token = request.query_params.get("token") or \
            request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    admin_token = get_admin_token()
    pairing_enabled = True if admin_token else False
    # 保持向后兼容：未设 token 时允许访问
    if pairing_enabled and (not token or not secrets.compare_digest(token, admin_token)):
        html = '''<!DOCTYPE html><html><body style="background:#0f0f0f;color:#666;display:flex;align-items:center;justify-content:center;height:100vh;font-family:monospace;flex-direction:column"><div style="font-size:48px">🔒</div><div style="margin:16px 0;color:#fff">需要管理员权限</div><div style="font-size:13px">访问 /admin?token=YOUR_ADMIN_TOKEN</div></body></html>'''
        return Response(content=html, media_type="text/html", status_code=403)
    admin_path = Path(FRONTEND_DIR) / "admin.html"
    if not admin_path.is_file():
        raise HTTPException(status_code=404, detail="admin.html not found")
    return FileResponse(admin_path)

@app.get("/auto-login/{device_id}/{token}")
async def auto_login(device_id: str, token: str):
    """自动登录：把 device_id 和 token 注入 localStorage，然后跳首页"""
    # 验证逻辑略——如需校验可接入 DB
    html = f"""
    <!DOCTYPE html><html><head><meta charset='utf-8'><title>PhotoMemory</title></head>
    <body style='background:#111;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:16px'>
    <div style='font-size:48px'>📸</div><h2>正在登录...</h2>
    <script>
    localStorage.setItem('pm_device_id','{device_id}');
    localStorage.setItem('pm_token','{token}');
    setTimeout(()=>{{window.location.href='/';}},500);
    </script></body></html>"""
    return Response(content=html, media_type="text/html")

@app.get("/reset-auth")
async def reset_auth_page():
    """清除 localStorage/cookie 中的配对凭证，强制重新配对"""
    html = """
    <!DOCTYPE html><html><head><meta charset='utf-8'><title>Reset Auth - PhotoMemory</title>
    <style>body{background:#111;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}</style></head><body><div style='text-align:center'>
    <div style='font-size:48px'>🔄</div><h2>正在清除凭证...</h2><p style='color:#888'>清除后自动跳转到配对页面</p></div>
    <script>['pm_device_id','pm_token'].forEach(k=>{localStorage.removeItem(k);document.cookie=k+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';});setTimeout(()=>{window.location.href='/';},1000);</script></body></html>
    """
    return Response(content=html, media_type="text/html")

from fastapi.staticfiles import StaticFiles
app.mount("", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")

# 以下 API 路由只做示意, 实际路由可逐步迁移
@app.get("/api/health")
async def health():
    return {"status": "ok"}

# 收藏/喜欢 API —— FastAPI/Pydantic 迁移（只实现迁移核心部分）
from backend.api_models import FavoriteToggleResponse, PhotoInfo, FavoritesResponse
from typing import List

@app.post("/api/photos/{photo_id}/favorite", response_model=FavoriteToggleResponse)
async def toggle_favorite(photo_id: int):
    """
    收藏或取消收藏图片。用 sqlite3 实现最小功能，生产环境请用异步。
    """
    import aiosqlite
    from datetime import datetime
    from backend.db.async_connection import get_async_db
    async with await get_async_db() as conn:
        cur = await conn.execute("SELECT 1 FROM favorites WHERE photo_id=?", (photo_id,))
        row = await cur.fetchone()
        if row:
            await conn.execute("DELETE FROM favorites WHERE photo_id=?", (photo_id,))
            await conn.commit()
            return FavoriteToggleResponse(favorited=False)
        else:
            await conn.execute(
                "INSERT INTO favorites (photo_id, created_at) VALUES (?, ?)",
                (photo_id, datetime.now().isoformat())
            )
            await conn.commit()
            return FavoriteToggleResponse(favorited=True)

@app.get("/api/favorites", response_model=FavoritesResponse)
async def get_favorites(limit: int = 50, offset: int = 0):
    """
    获取所有收藏的图片（核心结构迁移，仅演示）
    """
    import aiosqlite
    from backend.db.async_connection import get_async_db
    limit = min(limit, 200)
    async with await get_async_db() as conn:
        async with conn.execute(
            "SELECT f.photo_id, p.* FROM favorites f JOIN photos p ON f.photo_id=p.id "
            "ORDER BY f.created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ) as cursor:
            fav_rows = await cursor.fetchall()
        async with conn.execute("SELECT COUNT(*) FROM favorites") as cursor:
            total = (await cursor.fetchone())[0]
        results = [
            PhotoInfo(
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
                is_favorite=True
            ) for r in fav_rows
        ]
        return FavoritesResponse(results=results, total=total, limit=limit, offset=offset)

# TODO: 继续迁移 /api 相关路由和依赖

# CLI 启动（可选）
if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=str, default="./photomemory.db")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", type=str, default=None)
    parser.add_argument("--admin-token", type=str, default=None)
    args = parser.parse_args()
    set_db_path(args.db)
    uvicorn.run("backend.api_fastapi:app", host="0.0.0.0", port=args.port, reload=True)
