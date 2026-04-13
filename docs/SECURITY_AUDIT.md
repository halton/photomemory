# PhotoMemory 安全审计报告

**审计日期**: 2026-04-13  
**审计员**: AI Security Engineer  
**代码版本**: 当前 main 分支  
**审计范围**: api_server.py, index.html, scripts/

---

## 1. 认证系统分析 — Device Pairing 机制

### 1.1 架构概述

PhotoMemory 使用自研的 Device Pairing 认证方案：

1. 客户端 `POST /api/pair/request` 提交 `device_id` + `device_name`
2. 管理员用 Admin Token 调 `POST /api/pair/approve` 审批
3. 审批后颁发绑定 `device_id` 的随机 token（`secrets.token_urlsafe(32)`）
4. 后续请求需要 `Authorization: Bearer <token>` + `X-Device-ID: <device_id>`

### 1.2 认证旁路

- **localhost 免认证**：`_check_auth()` 对 `remote_addr` 为 `127.0.0.1` / `::1` 且无代理头的请求直接放行
- **未配置 admin-token 时完全开放**：`PAIRING_ENABLED = False` 时所有端点无认证
- **URL query 参数传 token**：`_t` + `_d` 参数支持在 URL 中携带凭证（为 `<img src>` 设计）

### 1.3 Token 存储

- 内存 + JSON 文件双写（`photomemory_devices.json`），**token 明文存储在文件中**
- 重启后从文件恢复

---

## 2. 发现的安全问题

### 🔴 Critical

#### C-1: SQL 注入 — 批量下载端点

**位置**: `batch_download_photos()` 和 `get_share()` 中的 SQL 拼接

```python
q = f"SELECT id, path, filename FROM photos WHERE id IN ({','.join(['?']*len(ids))})"
rows = conn.execute(q, ids).fetchall()
```

**分析**: 这里实际使用了参数化查询（`?` 占位符），**不存在注入**。虽然拼接了 `?` 数量，但值通过参数传递。这个模式是安全的。

**结论**: 经复查，此项降级为 ✅ 安全。全文使用 `?` 参数化，无直接字符串拼接 SQL 值。

#### C-2: 路径遍历 — 原图/缩略图 API 通过数据库间接访问

**位置**: `original_photo()`, `thumbnail()`, `download_photo()`

```python
row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
path = row["path"]
return send_file(path, ...)
```

**分析**: 路径来自数据库而非用户输入，但如果数据库被污染（例如通过扫描恶意构造的符号链接目录），`send_file()` 会跟随符号链接读取任意文件。

**影响**: 如果攻击者能控制被扫描的目录内容，可通过符号链接读取 `/etc/passwd` 等敏感文件。  
**风险等级**: Medium（需要先控制扫描目录）  
**修复建议**: 在 `send_file` 前验证路径在允许的目录白名单内：`os.path.realpath(path).startswith(allowed_base)`

---

### 🔴 Critical（真正的）

#### C-3: 分享链接绕过认证 — 任意照片访问

**位置**: `get_share()` 端点无 `@require_auth`，且分享链接中的 `thumb_url` / `original_url` 指向需要认证的端点。

**但更严重的问题是**: `face_thumbnail()` 和 `photo_persons()` **没有 `@require_auth` 装饰器**！

```python
@app.route("/api/face_thumb/<int:face_id>")
def face_thumbnail(face_id):  # ← 无认证！

@app.route("/api/photo_persons/<int:photo_id>")
def photo_persons(photo_id):  # ← 无认证！
```

**影响**: 任何人可以枚举 face_id 获取所有人脸缩略图，获取任何照片中出现的人物信息。这是**严重的隐私泄露**。  
**修复建议**: 添加 `@require_auth` 装饰器。

#### C-4: 分享 API 的 thumb_url/original_url 指向认证端点

**位置**: `get_share()` 返回的 URL 如 `/api/thumb/{id}`、`/api/photo/{id}` 需要认证。

**影响**: 分享链接实际无法正常工作（功能 bug），或者如果为了让分享工作而把这些端点也去掉认证，则会导致所有照片可被未认证访问。  
**修复建议**: 为分享创建独立的端点 `/api/shares/<share_id>/thumb/<photo_id>`，仅验证 share_id 有效性。

---

### 🟠 High

#### H-1: Admin Token 通过 URL 参数传递

**位置**: `/admin` 页面

```python
token = request.args.get("token", "") or ...
```

**影响**: Admin token 出现在 URL 中，会被浏览器历史、服务器日志、Referer 头泄露。  
**修复建议**: 使用 POST 表单或 HTTP-only cookie 传递 admin token。

#### H-2: Token 明文存储

**位置**: `photomemory_devices.json`

```json
{"paired": {"device_xxx": {"token": "actual_token_value", ...}}}
```

**影响**: 任何能读取该文件的人/进程可获取所有设备 token。  
**修复建议**: 存储 token 的 SHA-256 哈希，验证时比较哈希。

#### H-3: 无速率限制

**位置**: 所有端点，特别是 `/api/pair/request`、`/api/login`

**影响**: 暴力破解 device_id / token，DoS 攻击。  
**修复建议**: 使用 Flask-Limiter 添加速率限制。

#### H-4: CORS 完全开放

**位置**: `CORS(app)` 无任何限制

```python
CORS(app)  # 允许所有来源
```

**影响**: 任何网站可跨域调用 PhotoMemory API，若用户浏览器携带了 cookie/token，攻击者网站可代为请求。  
**修复建议**: `CORS(app, origins=["https://your-domain.com"])`

#### H-5: 删除照片不删除文件

**位置**: `delete_photo()`

```python
conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
# 文件仍在磁盘上
```

**影响**: 用户以为删除了照片，实际文件仍存在。如果是隐私敏感照片，这是问题。  
**修复建议**: 可选参数 `delete_file=true` 时 `os.remove(path)`。

#### H-6: subprocess 调用 ffmpeg 无输入验证

**位置**: `_video_thumbnail()`

```python
result = subprocess.run([ffmpeg, "-y", "-ss", "00:00:01", "-i", path, ...])
```

**分析**: `path` 来自数据库，使用列表形式调用（非 shell=True），不易注入。但恶意构造的视频文件可能触发 ffmpeg 漏洞。  
**修复建议**: 限制 ffmpeg 执行时间（已有 timeout=10），可增加 `nice` 降低优先级。

---

### 🟡 Medium

#### M-1: pair_status 泄露 token

**位置**: `/api/pair/status`

```python
return jsonify({"status": "approved", "token": d["token"]})
```

**影响**: 任何知道 device_id 的人可轮询此端点获取 token。device_id 在配对请求日志中可见。  
**修复建议**: token 只在 approve 响应中返回一次，之后 pair_status 只返回 `{"status": "approved"}` 不含 token。

#### M-2: 缺少 HTTPS 强制（自身层面）

**位置**: `force_https()` 只检查 `X-Forwarded-Proto`

**分析**: 依赖反向代理设置此头。直接访问 HTTP 时不会触发跳转。  
**修复建议**: 生产环境确保只通过反向代理暴露。

#### M-3: 错误信息泄露

**位置**: 多处 `str(e)` 返回给客户端

```python
return jsonify({"error": str(e)}), 500
```

**影响**: 泄露内部路径、数据库结构等信息。  
**修复建议**: 生产环境返回通用错误消息，详细错误只记录日志。

#### M-4: 批量下载无大小限制

**位置**: `batch_download_photos()` 限制 50 张但无总大小限制

**影响**: 50 张高分辨率照片可能产生数 GB 的 zip，消耗服务器内存（zip 在内存中构建）。  
**修复建议**: 流式 zip 生成，或限制总大小。

#### M-5: 分享链接 ID 可预测性

**位置**: `uuid.uuid4().hex[:12]` — 12 字符 hex = 48 bit

**影响**: 48 bit 熵对于面向公网的分享链接偏低。  
**修复建议**: 使用 `secrets.token_urlsafe(16)` (128 bit)。

#### M-6: 重复路由定义

**位置**: `/api/photos/random` 被定义了两次

```python
@app.route("/api/photos/random", methods=["GET"])
def photos_random(): ...

@app.route("/api/photos/random", methods=["GET"])
def api_photos_random(): ...
```

**影响**: Flask 会使用后注册的路由，前一个被覆盖。第二个函数后有悬空的 return 语句。代码混乱可能隐藏 bug。  
**修复建议**: 删除重复定义。

---

### 🟢 Low

#### L-1: DEBUG 模式硬编码为 False

`app.run(debug=False)` — 正确，无问题。

#### L-2: 无请求日志/审计日志

**影响**: 安全事件发生后无法追溯。  
**修复建议**: 添加结构化访问日志。

#### L-3: Session cookie 机制定义但未使用

`SESSION_COOKIE` 和 `_sessions` 定义了但从未在请求流程中使用。死代码。

#### L-4: `_face_scan_state` 重复定义

同一变量定义了两次，无功能影响但代码质量问题。

---

## 3. 安全问题汇总

| 等级 | 数量 | 问题编号 |
|------|------|---------|
| Critical | 2 | C-3, C-4 |
| High | 6 | H-1 ~ H-6 |
| Medium | 6 | M-1 ~ M-6 |
| Low | 4 | L-1 ~ L-4 |
| **合计** | **18** | |

---

## 4. 前端安全分析（index.html）

### 🟠 High

#### FE-H1: Token 在 URL 参数中传递（所有图片请求）

**位置**: `authUrl()` 函数

```javascript
function authUrl(path) {
  u.searchParams.set('_t', token);
  u.searchParams.set('_d', did);
  return u.toString();
}
```

**影响**: 每张缩略图的 URL 都包含明文 token。这些 URL 会出现在：
- 浏览器历史记录
- 服务器访问日志
- Referer 头（如果图片被外部页面引用）
- 浏览器开发者工具网络面板
- 任何中间代理日志

**修复建议**: 使用 HTTP-only cookie 传递认证信息，或使用短期 session token。

#### FE-H2: Token 明文存储在 localStorage

**位置**: 多处 `localStorage.setItem('pm_token', token)`

**影响**: 任何 XSS 漏洞都可读取 localStorage 窃取永久 token。localStorage 无过期机制。
**修复建议**: 使用 HTTP-only Secure cookie 存储 token。

### 🟡 Medium

#### FE-M1: 潜在 XSS — innerHTML 拼接用户数据

**位置**: 多处使用 `innerHTML` 拼接从 API 返回的数据

```javascript
// person name 直接拼接到 HTML
`<div class="pname">${p.name || '未命名'}</div>`

// loadLightboxPersons 中
`<div class="lb-person-chip" onclick="filterByPerson('${person.name}')">`
```

**影响**: 如果 person.name 包含恶意 HTML/JS（如 `<img onerror=alert(1)>`），会触发 XSS。攻击路径：修改数据库中的 person name → 所有访问者被 XSS。
**修复建议**: 使用 `textContent` 而非 `innerHTML`，或对动态内容进行 HTML 转义。

#### FE-M2: onclick 内联事件中的注入

**位置**: `filterByPerson('${person.name}')` 等

```javascript
`onclick="filterByPerson('${person.name}')"`
```

**影响**: 如果 person.name 包含单引号（如 `O'Brien`），会破坏 JS 语法。如果包含 `'); alert(1); //`，则触发 XSS。
**修复建议**: 使用 `addEventListener` 绑定事件，不在 HTML 属性中拼接动态数据。

#### FE-M3: 第三方 CDN 依赖无 SRI

**位置**: 
```html
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
```

**影响**: 如果 CDN 被入侵，可注入恶意 JS。
**修复建议**: 添加 `integrity` 和 `crossorigin` 属性（SRI）。

#### FE-M4: 无 Content Security Policy

**影响**: 没有 CSP 头，XSS 攻击无任何缓解。
**修复建议**: 添加 CSP 响应头限制脚本/样式来源。

### 🟢 Low

#### FE-L1: 设备 ID 使用 `crypto.randomUUID()` 仅在 HTTPS 下可用

```javascript
did = 'web-' + crypto.randomUUID(); // 仅支持 HTTPS
```

**影响**: HTTP 环境下会报错。代码注释已提到，但无 fallback。

#### FE-L2: 轮询间隔过短

`startPollApproval()` 每 3 秒轮询一次配对状态，可能产生不必要的服务器负载。

---

## 5. 前端安全问题汇总

| 等级 | 数量 | 问题编号 |
|------|------|----------|
| High | 2 | FE-H1, FE-H2 |
| Medium | 4 | FE-M1 ~ FE-M4 |
| Low | 2 | FE-L1, FE-L2 |
| **合计** | **8** | |

## 6. 总安全问题汇总

**后端**: 18 个（2 Critical, 6 High, 6 Medium, 4 Low）  
**前端**: 8 个（2 High, 4 Medium, 2 Low）  
**总计**: 26 个安全问题

---
