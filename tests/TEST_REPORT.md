# PhotoMemory 测试报告

> 生成时间：2026-04-14 21:40

## 测试概况

| 指标 | 数值 |
|------|------|
| 总测试数 | 130 |
| 通过 | 130 |
| 失败 | 0 |
| 通过率 | **100%** |
| 运行时间 | 4.32s |
| Python | 3.9.6 |
| 框架 | pytest 8.4.2 |

## 测试分布

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| test_health.py | 5 | 健康检查、根页面、auth_check、404 |
| test_search.py | 12 | 按城市/日期/年/月/人物搜索、分页、特殊字符、Unicode |
| test_photos.py | 15 | 照片 CRUD、缩略图、下载、收藏、地图、随机、批量 |
| test_persons.py | 12 | 人物列表、命名、Unicode 名、删除、人脸缩略图 |
| test_albums.py | 12 | 相册 CRUD、照片管理、推荐、边界条件 |
| test_shares.py | 10 | 创建分享、访问、过期、单张/多张/整相册 |
| test_stats.py | 12 | 基础统计、时间线、人物/地点统计、缓存、字段验证 |
| test_auth.py | 12 | 配对流程（request/approve/revoke/reject）、登录、管理页 |
| test_admin.py | 11 | 目录列表、重复/截图清理、人脸扫描、管理页访问 |
| test_security.py | 12 | SQL 注入、XSS、路径遍历、大请求体、负数/零 ID、并发写入 |
| **总计** | **130** | |

## 发现并修复的代码 Bug

### Bug 1: `import time` 缺失（Critical）
- **位置**: `backend/api_server.py:8`
- **症状**: `/api/pair/request` 调用 `time.time()` 报 `NameError`
- **影响**: 配对功能完全不可用
- **修复**: 添加 `import time`

### Bug 2: `p.dir_label` 列不存在（Critical）
- **位置**: `backend/api_server.py:492, 501, 537`
- **症状**: `/api/search` 报 `sqlite3.OperationalError: no such column: p.dir_label`
- **影响**: 搜索功能完全不可用
- **修复**: 改为 `p.directory`

### Bug 3: `added_at` 列不存在（High）
- **位置**: `backend/api_server.py:1087`
- **症状**: `/api/directories` 报 `sqlite3.OperationalError: no such column: added_at`
- **影响**: 目录列表功能不可用
- **修复**: 改为 `last_scan`

## 测试策略

- **集成测试为主**：使用真实 Flask test_client + 临时 SQLite DB
- **不 mock 服务层**：因为业务逻辑尚未从 api_server.py 拆分
- **每个测试独立 DB**：pytest function-scope fixture 确保隔离
- **包含安全测试**：SQL 注入、XSS、路径遍历等常见攻击向量

## 已知限制

1. 缩略图/照片下载测试只能验证 404（因为测试 DB 中的照片文件不存在）
2. FastAPI 版本（api_fastapi.py）未测试
3. 未覆盖 WebSocket 或长连接场景
4. 性能/压力测试较简单（仅 5 并发线程）
