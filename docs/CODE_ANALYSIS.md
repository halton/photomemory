# PhotoMemory 代码分析报告（后端&工具&重构建议）

> 本报告聚焦于 PhotoMemory 项目 backend、scripts 及 docs/REFACTOR_PLAN.md，便于后续持续自动化开发。前端分析留待下一步。

---

## 1. backend/api_server.py 分析

### 架构
- 基于 Flask，统一 API 入口，数据存储采用 SQLite。
- 主体包含：设备配对认证、相册与照片管理、人脸识别、数据统计、资源下载分享等模块。
- 各类功能高度集中在单文件，尚未模块化拆分。

### 路由列表（核心功能分类）
- 设备管理相关：/api/pair/request, /api/pair/status, /api/pair/approve, /api/pair/revoke, /api/pair/list, /auto-login/*, /reset-auth
- 用户鉴权/会话查询：/api/auth_check, /api/login
- 照片相关：/api/photos/<id>/favorite, /api/favorites, /api/search, /api/thumb/<id>, /api/photo/<id>, /api/photos/<id>, /api/photos/download, /api/photos/random, /api/photos/map, /api/photos/<id>/download
- 人脸与人物相关：/api/persons*, /api/face_thumb/<id>, /api/photo_persons/<id>
- 相册与分享：/api/albums*, /api/shares*, /api/albums/<id>/photos, /api/albums/<id>/photos/<photo_id>, /api/albums/<id>
- 统计与数据清理：/api/stats, /api/stats/timeline, /api/stats/persons, /api/stats/locations, /api/cleanup/duplicates, /api/cleanup/screenshots, /api/duplicates, /api/directories
- 健康/管理面板：/api/health, /admin

### 认证机制
- “Pairing” 机制：设备先请求审核，管理员批准后分配 token 使用。
- API 校验 `Authorization: Bearer <token>` + `X-Device-ID` 或 URL 参数，否则只允许运行于本地或无认证模式。
- 管理员操作需单独 ADMIN_TOKEN，具备更高权限。
- 支持 localhost 环境下免认证。

### 数据库操作模式
- SQLite，API 层每次操作新建连接，无连接池及 WAL 优化。
- 表结构明细参见 _ensure_tables。
- JOIN/分页/排序等 SQL 直接在 API 内编写，业务与数据访问层未分离。
- 设备信息除 DB 外还用磁盘文件 JSON 持久化。
- 大量 dict、list 转换和字段映射手动处理。

### 性能瓶颈
- 频繁 sqlite3.connect()，并发写入及 I/O 密集型会受限（无连接池、无 WAL、无 async/await）。
- 部分 SQL 查询未加显式索引和 limit，数据量大时易阻塞。
- 缩略图/人脸图像实时生成，虽有磁盘缓存，但首次访问高并发时较慢。
- ZIP 打包批量下载采用内存 BytesIO，易 OOM。

### 安全风险
- 部分 API 未做认证处理，应核查覆盖率和认证注解（如 /api/* 是否都 @require_auth）。
- 用户输入参数直接拼接到 SQL 或文件操作，需防注入/路径穿越风险。
- 设备与管理员 token 均为 Bearer 明文，建议考虑 TLS、过期与吊销机制。
- 设备配对流程对攻击面的暴露较大，需关注暴力破解、重放攻击风险。

---

## 2. scripts/ 工具脚本分析

### scripts/phase1_index.py
- 功能：递归扫描图片/视频目录，提取 EXIF/GPS、判定截图/重复文件，批量入库并维护去重分组。
- 质量：依赖 PIL/piexif/reverse_geocode，可单次/递归批量处理，支持基础数据统计与重复项报告。
- 优点：自动区分 screenshot，支持大目录高效增量。
- 改进：异常处理部分可补充日志，数据库接口与主线逻辑可分层。

### scripts/pm_stats.py
- 功能：汇总 photo/faces/persons/duplicates/screenshots 等常用统计数字，支持命令行 JSON 输出。
- 质量：简单实用，支持异常表结构自动处理。建议后继可直接调用 API/DB ORM。

### scripts/backfill_geocode.py
- 功能：批量填充 gps_city 字段，使用 reverse_geocode，缺失的按 (lat,lon) 查询逆地理。
- 质量：生产脚本，具 dry-run，异常处理基本到位。
- 建议支持断点续跑/重试，详细日志。

### scripts/cluster_faces.py
- 功能：直接聚类 faces 表 embedding 字段，采用 DBSCAN，自动写入新 person，并回写 faces.person_id。
- 用于独立聚类任务，易于集成到 CLI/workflow。
- 建议参数化聚类超参、metrics，并输出更详尽聚类统计。

### scripts/phase2_faces.py
- 功能：完整的人脸检测 + embedding + 聚类 + 人物命名 + 统计 CLI
- 高依赖（Pillow/insightface/sklearn/cv2 等），细节处理如 EXIF 旋转、亮度过滤等较为完善。
- CLI 四大命令 --detect/--cluster/--label/--stats，适用于流水线集成。
- 建议人脸检测/聚类步骤参数化可并行、引入更稳健的 CLI/日志库、支持配置化。

---

## 3. docs/REFACTOR_PLAN.md 方案评估

### 可行性 & 建议：
- **Flask → FastAPI**：完全可行，相关路由/参数模式一一对应，重用现有测试用例。需重写依赖注入与认证装饰器。
- **数据库优化**：优先实施 WAL 模式和连接池，长期可考虑 PostgreSQL+pgvector。
- **代码模块化**：现有 monolith 单文件已阻碍功能演进，分层（auth/routes/services/db/utils）有清晰边界。
- **性能优化点**：缩略图磁盘缓存、批量操作分页、统计类接口缓存都有明确落地点。
- **拆分优先级**：建议先做安全修复、性能（缩略图缓存/索引）、代码拆分、再移步 FastAPI。

---

## 4. 拆分为独立任务的功能点建议

### 1. 缩略图磁盘缓存优化
- 输入：当前照片库、访问高频图片
- 输出：稳定命中缓存，I/O 明显下降
- 依赖：photos 表、/api/thumb

### 2. 数据库 WAL + 连接池
- 输入：现有 DB+API
- 输出：API 层大幅提升并发读写（见 WAL 生效指标）
- 依赖：Flask/FastAPI DB 层重构

### 3. 代码结构解耦拆分
- 输入：backend/api_server.py
- 输出：模块化多文件结构、每层独立可测试
- 依赖：编码规范与目录结构优先确定

### 4. 设备配对认证流程安全增强
- 输入：当前配对认证相关接口
- 输出：认证全流程日志与风控、暴力破解防护、token 过期/吊销管理
- 依赖：auth 服务、DB 新字段

### 5. 批量 ZIP 下载流式/分片输出
- 输入：多照片大批量下载请求
- 输出：不 OOM 的流式下载响应
- 依赖：照片存储分布、API 扩展

### 6. 人脸检测/聚类参数化优化 CLI
- 输入：现有 phase2_faces.py
- 输出：支持命令行调参、自动日志、友好报错
- 依赖：insightface、sklearn

### 7. SQLite 优化 → PostgreSQL（百万量级以上）
- 输入：照片量突破 100 万以上的生产数据
- 输出：数据+API 顺利无损迁移，支持高可用
- 依赖：数据迁移脚本、pgvector

### 8. 统计/地图/搜索等慢接口缓存
- 输入：慢查询接口的历史查询
- 输出：接口 RT 降低+缓存命中统计
- 依赖：缓存中间件/内存方案/路由改造

---

