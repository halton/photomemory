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
def _lifespan(app) -> AsyncGenerator[None, None]:
    import os
    db_path = os.environ.get("PHOTOMEMORY_DB", "./photomemory.db")
    set_async_db_path(db_path)
    set_async_pool_size(5)  # default
    yield
    await close_pool()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

from backend.db.async_connection import set_async_db_path, set_async_pool_size, close_pool

app = FastAPI(
    lifespan=lambda app: _lifespan(app)
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

# 以下 API 路由只做示意, 实际路由可逐步迁移
@app.get("/api/health")
async def health():
    return {"status": "ok"}

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
