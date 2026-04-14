# PhotoMemory 持续开发计划

> 基于 Claude Code 代码分析 + REFACTOR_PLAN.md，设计 OpenClaw cron 驱动的持续自动化开发流程。

## 项目现状概要

| 指标 | 数值 |
|------|------|
| 后端 | `api_server.py` 1623行 单文件 Flask |
| 前端 | `index.html` 2628行 单文件 HTML |
| 工具脚本 | 5个 Python 脚本（phase1/phase2/backfill/cluster/stats） |
| 照片数据 | 12,796 张，4,061 张人脸，249 个聚类 |
| Git 提交 | 51 commits |
| 公网地址 | https://photomemory.ciyuanllm.net |

## 开发阶段（6个Sprint）

### Sprint 1: 性能急救 🔥
**预计耗时：1-2个 Claude Code session**
- [x] SQLite WAL 模式 + `PRAGMA` 优化 ✅ 2026-04-14 09:50 — 新增 db_util.py，api_server + 所有脚本统一应用 WAL/NORMAL/cache/mmap ✅ (2026-04-14 09:52)
- [x] 添加关键索引（taken_at, gps_city, person_id, photo_id） ✅ (2026-04-14 09:55)
- [x] 统计接口内存缓存（60s TTL） ✅ 2026-04-14 09:58 — 新增 cache_util.py 装饰器，stats 相关接口加 60s 缓存 ✅ (2026-04-14 09:59)
- [x] 验收：API 响应时间对比 ✅ (2026-04-14 10:02)

### Sprint 2: 后端模块化拆分 🏗️
**预计耗时：2-3个 session**
- [x] 建立目标目录结构（routes/services/db/auth/utils） ✅ (2026-04-14 10:04)
- [x] 提取认证模块 → `auth/pairing.py` + `auth/middleware.py` ✅ (2026-04-14 10:12)
- [x] 提取路由 → `routes/photos.py`, `routes/persons.py`, `routes/albums.py`, `routes/search.py`, `routes/stats.py`, `routes/admin.py`, `routes/shares.py` ✅ (2026-04-14 10:13)
- [x] 提取服务 → `services/thumbnail.py`, `services/geocode.py` ✅ (2026-04-14 10:19)
- [x] 提取数据库层 → `db/connection.py`, `db/queries.py`, `db/migrations.py` ✅ (2026-04-14 10:25)
- [ ] 验收：所有 API 端点功能不变，`api_server.py` 缩减到 <100 行入口

### Sprint 3: Flask → FastAPI 迁移 ⚡
**预计耗时：2-3个 session**
- [ ] FastAPI app 初始化 + 依赖注入框架
- [ ] aiosqlite 连接池
- [ ] Pydantic 请求/响应模型
- [ ] 全部路由迁移为 async
- [ ] 静态文件 serving（前端 HTML）
- [ ] 验收：公网访问正常，所有功能回归通过

### Sprint 4: 安全加固 🔒
**预计耗时：1-2个 session**
- [ ] SQL 参数化查询全面审计
- [ ] 路径遍历防护（照片下载/缩略图接口）
- [ ] Token 过期机制
- [ ] Rate limiting（配对请求防暴力破解）
- [ ] CORS 配置收紧
- [ ] 验收：安全扫描通过

### Sprint 5: 前端现代化 🎨
**预计耗时：3-4个 session**
- [ ] 拆分 CSS/JS 独立文件
- [ ] 引入轻量框架（Alpine.js 或 Vue 3 CDN）
- [ ] 组件化拆分（搜索栏、照片网格、灯箱、地图、人物管理等）
- [ ] 响应式优化
- [ ] 验收：移动端/桌面端体验对比

### Sprint 6: 高级功能 🚀
**预计耗时：按需**
- [ ] 人脸聚类调参（eps 自动调优）
- [ ] GPS backfill 自动化
- [ ] 相册智能推荐
- [ ] 照片/地图聚合展示优化
- [ ] Docker 化部署
- [ ] CI/CD 流水线

---

## OpenClaw 持续开发方案

### 方案：Cron 定时 + Claude Code Session

每个 Sprint 拆成独立的 cron agentTurn 任务：

```
[cron job] → [isolated agentTurn] → [Claude Code session] → [git commit] → [announce 完成]
```

**工作流程：**
1. Cron 触发 isolated session
2. Session 读取本文件，获取当前 Sprint 和待办项
3. 启动 Claude Code 执行具体编码任务
4. 完成后 git commit + 更新本文件的 checkbox
5. Announce 到飞书报告进展

**每个任务的约束：**
- 单次只做一个明确的子任务（如"提取认证模块"）
- 必须保持功能不退化（跑完后服务能正常启动）
- 必须 git commit 并写清楚 commit message
- 遇到需要人工决策的问题，报告并暂停

### 任务粒度示例（Sprint 2 拆分）

| Task ID | 描述 | 依赖 |
|---------|------|------|
| S2-T1 | 创建目录结构 + `__init__.py` | 无 |
| S2-T2 | 提取 `db/connection.py` + `db/migrations.py` | S2-T1 |
| S2-T3 | 提取 `auth/pairing.py` + `auth/middleware.py` | S2-T2 |
| S2-T4 | 提取 `routes/photos.py` + `routes/search.py` | S2-T2, S2-T3 |
| S2-T5 | 提取 `routes/persons.py` + `routes/albums.py` | S2-T2, S2-T3 |
| S2-T6 | 提取 `routes/stats.py` + `routes/admin.py` + `routes/shares.py` | S2-T2, S2-T3 |
| S2-T7 | 提取 `services/thumbnail.py` + `services/geocode.py` | S2-T2 |
| S2-T8 | 重写 `api_server.py` 为 app entry point | S2-T2 ~ S2-T7 |
| S2-T9 | 集成测试 + 修复 | S2-T8 |

---

## 当前状态

**Active Sprint:** 未开始
**Next Action:** 等待用户确认后启动 Sprint 1
