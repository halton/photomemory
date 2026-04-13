# PhotoMemory 重构计划

## 1. Flask → FastAPI 迁移

### 动机
- Flask 的同步模型在处理 I/O 密集操作（图片处理、数据库查询）时效率低
- FastAPI 自带 OpenAPI 文档、请求验证、依赖注入
- 更好的 async/await 支持

### 迁移路径

**阶段 1：兼容层（1 周）**
```python
# 路由一一对应迁移
@app.get("/api/search")
async def search(
    q: str = "", date_from: str = "", date_to: str = "",
    year: str = "", month: str = "", person: str = "",
    exclude_screenshots: bool = True,
    limit: int = Query(50, le=200),
    offset: int = 0,
    auth: DeviceAuth = Depends(require_auth)
):
    ...
```

**阶段 2：依赖注入**
```python
# 数据库连接池
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

# 认证依赖
async def require_auth(
    authorization: str = Header(None),
    x_device_id: str = Header(None, alias="X-Device-ID"),
):
    ...
```

**阶段 3：Pydantic 模型**
```python
class PhotoResponse(BaseModel):
    id: int
    path: str
    filename: str
    taken_at: str | None
    gps_lat: float | None
    gps_lon: float | None
    thumb_url: str
    original_url: str
```

### 关键变更
| Flask | FastAPI |
|-------|---------|
| `@app.route("/path", methods=["GET"])` | `@app.get("/path")` |
| `request.args.get("q")` | 函数参数 `q: str = ""` |
| `jsonify({})` | 直接返回 dict |
| `@require_auth` 装饰器 | `Depends(require_auth)` |
| `send_file()` | `FileResponse()` / `StreamingResponse()` |

---

## 2. SQLite → 更好方案

### 现状
- 单文件 SQLite，写锁全局
- 无连接池，每次请求 `sqlite3.connect()`
- 人脸 embedding 存为 BLOB

### 建议：保留 SQLite，但优化使用方式

SQLite 对于 10 万级照片完全够用。问题在于使用方式：

1. **连接池**：使用 `aiosqlite` + 连接池
2. **WAL 模式**：`PRAGMA journal_mode=WAL` 允许并发读
3. **索引优化**：
   ```sql
   CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photos(taken_at);
   CREATE INDEX IF NOT EXISTS idx_photos_gps_city ON photos(gps_city);
   CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces(person_id);
   CREATE INDEX IF NOT EXISTS idx_faces_photo_id ON faces(photo_id);
   ```

### 若数据量超过 100 万照片
考虑 PostgreSQL：
- 支持 `pgvector` 扩展做人脸向量检索
- 真正的并发写入
- 迁移工具：`pgloader`

---

## 3. 代码拆分建议

### 现状：`api_server.py` ~900 行单文件

### 目标结构
```
backend/
├── app.py              # FastAPI 应用初始化
├── config.py           # 配置管理
├── auth/
│   ├── __init__.py
│   ├── pairing.py      # Device Pairing 逻辑
│   ├── middleware.py    # 认证中间件/依赖
│   └── models.py       # 设备/Token 模型
├── routes/
│   ├── __init__.py
│   ├── photos.py       # 照片 CRUD
│   ├── search.py       # 搜索
│   ├── persons.py      # 人物管理
│   ├── albums.py       # 相册管理
│   ├── shares.py       # 分享
│   ├── stats.py        # 统计
│   ├── admin.py        # 管理接口
│   └── health.py       # 健康检查
├── services/
│   ├── thumbnail.py    # 缩略图生成
│   ├── face_scan.py    # 人脸扫描
│   └── geocode.py      # 地理编码
├── db/
│   ├── connection.py   # 连接管理
│   ├── migrations.py   # 表结构初始化/迁移
│   └── queries.py      # 常用查询
└── utils/
    ├── image.py        # 图片处理工具
    └── video.py        # 视频处理工具
```

### 拆分原则
- 每个路由文件对应一个 FastAPI `APIRouter`
- 业务逻辑放 `services/`，路由层只做参数提取和响应格式化
- 数据库操作集中在 `db/`

---

## 4. 性能优化 Top 10

### P-1: 缩略图缓存（影响：⭐⭐⭐⭐⭐）
**现状**: 每次请求实时读取原图 → resize → 返回  
**方案**: 生成缩略图时缓存到磁盘（`/data/thumbs/{photo_id}_{size}.jpg`），后续直接 serve 静态文件

### P-2: 数据库连接复用（影响：⭐⭐⭐⭐⭐）
**现状**: 每次请求 `sqlite3.connect()`  
**方案**: 使用连接池或全局连接 + WAL 模式

### P-3: 搜索性能 — 添加索引（影响：⭐⭐⭐⭐）
**现状**: 无显式索引，大表全扫描  
**方案**: 添加 taken_at、gps_city、person_id 索引

### P-4: 照片地图端点 — 全量加载优化（影响：⭐⭐⭐⭐）
**现状**: `/api/photos/map` 返回所有有 GPS 的照片，可能数万条  
**方案**: 返回聚合数据（按城市聚合坐标 + 计数），详细数据按 bounds 分页加载

### P-5: ZIP 下载 — 流式生成（影响：⭐⭐⭐）
**现状**: `BytesIO` 内存中构建 ZIP  
**方案**: 使用 `StreamingResponse` + `zipfly` 流式生成

### P-6: 人脸缩略图缓存（影响：⭐⭐⭐）
**现状**: 每次裁剪 + 亮度检测 + 可能遍历 10 张其他照片  
**方案**: 首次生成后缓存到磁盘

### P-7: 前端图片懒加载优化（影响：⭐⭐⭐）
**现状**: IntersectionObserver 已实现，但 rootMargin 较小  
**方案**: 加大预加载距离，使用 `loading="lazy"` 原生属性

### P-8: 搜索 — 人物查询优化（影响：⭐⭐）
**现状**: 先查所有匹配 photo_path，再 `IN (...)` 查询  
**方案**: 使用 JOIN 一次查询完成

### P-9: 统计接口缓存（影响：⭐⭐）
**现状**: 每次实时计算  
**方案**: 内存缓存 + 60 秒 TTL

### P-10: 前端资源合并/压缩（影响：⭐⭐）
**现状**: 单个 HTML 文件内联所有 CSS/JS  
**方案**: 分离 CSS/JS 文件，启用 gzip 压缩，添加版本哈希

---

## 5. 优先级路线图

| 阶段 | 内容 | 预计时间 |
|------|------|---------|
| 1 | 安全漏洞修复（Critical/High） | 1 天 |
| 2 | 缩略图缓存 + 数据库索引 | 2 天 |
| 3 | 代码拆分为模块 | 3 天 |
| 4 | Flask → FastAPI 迁移 | 1 周 |
| 5 | 连接池 + WAL | 1 天 |
| 6 | 前端重构（Vue/React SPA） | 2 周 |
