# PhotoMemory 项目开发记录

> 本地 NAS 智能照片检索系统 | 开发起始：2026-03-15
> 
> 技术栈：Python · Flask · SQLite · InsightFace · Cloudflare Tunnel

---

## 目录

1. [项目目标](#1-项目目标)
2. [技术架构](#2-技术架构)
3. [各阶段开发内容](#3-各阶段开发内容)
   - [Phase 1：索引 & 元数据](#phase-1索引--元数据)
   - [Phase 2：人脸识别 & 聚类](#phase-2人脸识别--聚类)
   - [Phase 3：API Server](#phase-3api-server)
   - [Phase 4：Web UI](#phase-4web-ui)
   - [Phase 5：Chat 接入](#phase-5chat-接入)
4. [认证系统：Device Pairing](#4-认证系统device-pairing)
5. [遇到的坑 & 解决方案](#5-遇到的坑--解决方案)
6. [当前状态 & 配置](#6-当前状态--配置)
7. [待办事项](#7-待办事项)
8. [git 提交历史](#8-git-提交历史)

---

## 1. 项目目标

在本地 NAS 上构建家庭照片智能检索系统，支持：

- 按**时间、地点、人物（人脸）**搜索
- 通过 **OpenClaw Chat 对话**查图（自然语言）
- **多用户**（家庭成员）共用，各自独立人脸标签
- 所有数据**全本地**，人脸 embedding 不上云
- 重复/截图**只标记**，不自动删除

**硬件环境**
- NAS：`nengcloud`（IP: 198.20.2.165），群晖 NAS
- Mac 通过 SMB 挂载：`/Volumes/backup`
- 照片路径示例：`/Volumes/backup/photos/Halton/iPhone/2026/02/IMG_xxxx.JPG`

---

## 2. 技术架构

```
NAS (SMB) ─── Mac 本地处理
                 │
    ┌────────────┼─────────────────┐
    │            │                 │
 Phase1       Phase2            Qdrant
 (SQLite)   (InsightFace)     (向量DB)
    │            │                 │
    └────────────┴─────────────────┘
                 │
           Flask API Server (port 8765)
                 │
    ┌────────────┼───────────────┐
    │            │               │
  Web UI      Admin UI      Chat Tools
 (暗色主题)   (/admin)    (OpenClaw Chat)
                 │
         Cloudflare Tunnel
          (公网访问入口)
```

| 组件 | 选型 | 原因 |
|------|------|------|
| 元数据库 | SQLite | 轻量，无需独立服务 |
| 人脸识别 | InsightFace (buffalo_l) | 全本地，精度高 |
| 向量数据库 | Qdrant (Docker) | 支持本地部署 |
| API 框架 | Flask | 快速开发 |
| 逆地理编码 | reverse_geocode 库 | 离线，无 API 限制 |
| 公网隧道 | Cloudflare Tunnel | 免费，无需公网 IP |

---

## 3. 各阶段开发内容

### Phase 1：索引 & 元数据

**功能**
- EXIF 信息提取（拍摄时间、GPS 坐标、设备型号）
- GPS 坐标 → 城市名（逆地理编码，离线）
- 重复检测（MD5 哈希对比，只标记不删除）
- 截图过滤（目录名匹配 + 分辨率特征，只打标签不删除）
- 支持按目录白名单增量添加索引

**测试结果**
- 扫描 `/Volumes/backup/photos/Halton/iPhone/2026`（68 个文件）
- 全部索引成功，3 张截图被标记，0 错误

---

### Phase 2：人脸识别 & 聚类

**功能**
- 使用 InsightFace buffalo_l 模型检测人脸
- DBSCAN 聚类（eps=0.5）自动分组为"人物"
- 命名管道（交互式 + API）

**关键参数**
- 置信度阈值：`0.85`（经过多次调整）
- 聚类半径：`eps=0.5`
- 最小人脸尺寸：50×50 px

---

### Phase 3：API Server

Flask 后端，8 个核心接口：

| 接口 | 功能 |
|------|------|
| `GET /api/photos` | 搜索照片（时间/地点/人物/关键词） |
| `GET /api/thumb/<id>` | 获取缩略图 |
| `GET /api/photo/<id>` | 获取原图 |
| `GET /api/persons` | 人物列表（含头像） |
| `GET /api/persons/<id>/photos` | 某人所有照片 |
| `PATCH /api/persons/<id>` | 命名人物 |
| `GET /api/face_thumb/<face_id>` | 人脸头像裁剪 |
| `GET /api/stats` | 统计信息 |

---

### Phase 4：Web UI

- 暗色主题，响应式布局
- 搜索栏（时间/地点/人物/关键词）
- 瀑布流照片网格
- **灯箱**：全屏查看，右侧 300px 信息面板（GPS/时间/地点/人物/尺寸/目录）
- **人物管理**：卡片点击 → 弹出浏览 Modal，查看该人所有照片后再命名

---

### Phase 5：Chat 接入

通过 `backend/chat_tools.py` 接入 OpenClaw Chat：
- 自然语言查图（"帮我找上周在北京拍的照片"）
- 返回缩略图预览 + 原图访问链接

---

## 4. 认证系统：Device Pairing

### 设计背景

Cloudflare Tunnel 场景下 Session Cookie 不可靠（跨域、重定向丢失），需要完全无状态认证。

### 认证流程

```
浏览器                    API Server               管理员
  │                          │                        │
  │── 申请配对(设备名) ──────>│                        │
  │<─ pending 状态 ──────────│                        │
  │                          │<── 审批(admin token) ──│
  │── 轮询状态 ──────────────>│                        │
  │<─ approved + token ──────│                        │
  │── 存 localStorage+cookie │                        │
  │                          │                        │
  │── 后续请求 ──────────────>│ 验证 token+device_id   │
  │   Bearer token           │                        │
  │   X-Device-ID header     │                        │
```

### 技术细节

- **认证**：`Authorization: Bearer <token>` + `X-Device-ID: <did>` Header
- **图片 URL**：带 `?_t=<token>&_d=<device_id>` 参数（`<img src>` 无法带 Header）
- **持久化**：token + device_id 同时写入 `localStorage` 和 Cookie（1年有效期）
- **设备文件**：`/tmp/photomemory_devices.json`（`{"paired": {}, "pending": {}}`）

### 管理界面

- 路径：`/admin?token=<admin_token>`
- 功能：待审批列表（批准/拒绝）、已配对列表（吊销）、5秒自动刷新

---

## 5. 遇到的坑 & 解决方案

### 🐛 坑1：人脸头像显示错误（衣服/地板/黑图）

**现象**：人物卡片显示的不是人脸，而是衣服、地板、暗区  
**根因**：InsightFace 用 `cv2.imread` 读图，不处理 EXIF 旋转。演出夜景照片大量误检（置信度 0.5 太低）  
**解决**：
1. Phase 2 检测前用 `PIL.ImageOps.exif_transpose` 先旋转图片再检测
2. 置信度阈值从 `0.5` 提高到 `0.85`
3. 新增亮度过滤（裁剪区域平均亮度 < 30 跳过）
4. 新增最小尺寸过滤（人脸 bbox < 50px 跳过）
5. 后端 `face_thumbnail` 同步改为先旋转再裁剪

---

### 🐛 坑2：Cloudflare Tunnel 下登录状态丢失

**现象**：刷新页面后需要重新登录  
**根因**：Session Cookie 在 Cloudflare Tunnel 跨域场景下丢失  
**解决**：彻底移除 Session Cookie，改为 Bearer Token + device_id 完全无状态认证，localStorage + Cookie 双重持久化

---

### 🐛 坑3：`apiFetch` 死循环

**现象**：认证失败后页面卡死，Network 请求无限循环  
**根因**：`apiFetch` 遇到 401 调 `checkAuth`，`checkAuth` 里又用 `apiFetch` 调接口，形成递归  
**解决**：`checkAuth` 内部全部改用原生 `fetch`，`apiFetch` 去掉重试逻辑；`auth_check` 接口始终返回 200（认证结果在 body 里）

---

### 🐛 坑4：中文城市搜索不到照片

**现象**：搜索"北京"找不到照片，英文"Beijing"可以找到  
**根因**：逆地理编码库返回英文城市名（如 `Beijing Jinrongjie`）  
**解决**：维护静态 `CITY_ALIASES` 字典，"北京" → `["beijing", "bj"]`，搜索时展开别名

---

### 🐛 坑5：`/admin` 无任何保护

**现象**：任何人不需要认证就可以访问 `/admin` 页面  
**解决**：后端路由检查 `Authorization: Bearer <admin_token>` 或 URL `?token=<admin_token>`，缺少则返回 403

---

### 🐛 坑6：登录 Overlay 无法隐藏

**现象**：`hideLoginOverlay()` 调用后页面仍然显示遮罩  
**根因**：CSS 写成 `.login-overlay { display: flex; }` + `.login-overlay.show { display: flex; }`，移除 `.show` 类无效（默认样式仍是 flex）  
**解决**：改为 `.login-overlay { display: none; }` + `.login-overlay.show { display: flex; }`

---

### 🐛 坑7：视频文件无缩略图

**现象**：视频文件显示黑色占位图  
**根因**：ffmpeg 未安装  
**解决**：添加 ffmpeg 路径探测（`/opt/homebrew/bin/ffmpeg` → `/usr/local/bin/ffmpeg` → `which ffmpeg`），不可用时生成纯色占位图；待安装 ffmpeg 后自动启用

---

### 🐛 坑8：Python 3.9 语法不兼容

**现象**：`str | None` 类型注解报错  
**根因**：`X | Y` union 语法是 Python 3.10+ 新特性  
**解决**：改为 `Optional[str]`（`from typing import Optional`）

---

### 🐛 坑9：设备 token 泄露后的安全问题

**场景**：仅凭 token 能否访问数据？  
**设计**：认证必须同时提供 `token` + `device_id`，二者缺一不可，单独泄露无效

---

### 🐛 坑10：人物命名时看不清是谁

**现象**：人物管理页只显示小头像，无法判断是哪个家人  
**解决**：新增人物浏览 Modal，点击人物卡片弹出该人所有照片的网格预览，底部附命名输入框

---

## 6. 当前状态 & 配置

### 运行参数

| 项目 | 值 |
|------|-----|
| API 端口 | `8765` |
| 数据库 | `/tmp/photomemory_test.db` |
| 设备文件 | `/tmp/photomemory_devices.json` |
| Admin Token | `1VsnIeo2KbxpDcSMKSo501WAlxjJyEaAXtsLxwLqCGU` |
| 公网隧道 | `https://tin-sticky-van-msgid.trycloudflare.com`（临时，重启变） |

### 启动命令

```bash
cd ~/.openclaw/workspace-daddy/projects/photomemory
python3 backend/api_server.py \
  --db /tmp/photomemory_test.db \
  --admin-token "1VsnIeo2KbxpDcSMKSo501WAlxjJyEaAXtsLxwLqCGU"
```

### 访问地址

- 主界面：`http://localhost:8765/`
- 管理界面：`http://localhost:8765/admin?token=<admin_token>`
- 公网（需配对）：`https://tin-sticky-van-msgid.trycloudflare.com/`

### 测试数据（2026/02 目录，68张）

- 人物聚类：3 个（经过阈值优化后均为真实人脸）
- 城市分布：北京（19张）、山西（7张）等

---

## 7. 待办事项

- [ ] 全量扫描：确认 `/Volumes/backup/photos/` 下完整目录，跑全量 Phase 1 + Phase 2
- [ ] ffmpeg 安装确认 + 视频缩略图测试
- [ ] HEIC 格式缩略图失败问题排查
- [ ] Cloudflare Tunnel 持久化（注册账号使用 Named Tunnel）
- [ ] 配置正式 git 用户信息（`git config --global --edit`）
- [ ] 确认其他家庭成员照片目录（iPhone 之外的设备）
- [ ] 给 3 个人物聚类正式命名

---

## 8. git 提交历史

| Commit | 内容 |
|--------|------|
| `84082a3` | 项目初始化 |
| `0b20dcf` | Phase 1：EXIF 索引 + 重复检测 + 截图过滤 |
| `d7cb59c` | Phase 2：人脸检测 + DBSCAN 聚类 |
| `cd88648` | Phase 3+4+5：API + Web UI + Chat |
| `2e2f6c0` | fix: 逆地理编码 + 聚类调参 |
| `84fd829` | fix: 认证死循环 + auth_check 200 |
| `f4398f3` | feat: 强制 HTTPS + crypto.randomUUID |
| `7402119` | feat: 吊销后允许重新申请配对 |
| `65b7f8d` | fix: overlay display:none 修复 |
| `c1e31e8` | feat: device_id + token 双写 cookie 备份 |
| `d73d290` | fix: /admin 路由加 admin token 保护 |
| `6fc97ff` | feat: 人物浏览 Modal + Phase 2 EXIF 旋转修复 |

---

*最后更新：2026-03-16*
