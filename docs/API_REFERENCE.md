# PhotoMemory API Reference

**Base URL**: `http://localhost:8765/api`  
**认证**: Device Pairing (Bearer token + X-Device-ID header) 或开放模式  
**版本**: Phase 3

---

## 认证说明

### 认证方式

1. **Bearer Token + Device ID**（推荐）
   ```
   Authorization: Bearer <token>
   X-Device-ID: <device_id>
   ```

2. **URL Query 参数**（用于 `<img src>` 等场景）
   ```
   ?_t=<token>&_d=<device_id>
   ```

3. **开放模式**：未设置 `--admin-token` 时无需认证

### 认证级别

| 标记 | 说明 |
|------|------|
| 🔓 | 无需认证 |
| 🔐 | 需要 Device Token |
| 🔑 | 需要 Admin Token |

---

## 配对接口

### POST /api/pair/request 🔓
申请设备配对。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| device_id | string | ✅ | 设备唯一标识 |
| device_name | string | ❌ | 设备名称，默认 "Unknown Device" |

**响应**:
```json
{"status": "pending", "message": "申请已提交，等待管理员审批"}
```

### GET /api/pair/status 🔓
轮询配对状态。

| 参数 | 类型 | 说明 |
|------|------|------|
| device_id | query/header/cookie | 设备 ID |

**响应**:
```json
{"status": "approved", "token": "xxx"}  // 已批准
{"status": "pending"}                    // 等待审批
{"status": "revoked"}                    // 已吊销 (403)
```

### POST /api/pair/approve 🔑
审批设备。

| 参数 | 类型 | 必填 |
|------|------|------|
| device_id | string | ✅ |

**响应**: `{"ok": true, "device_id": "...", "device_name": "..."}`

### POST /api/pair/reject 🔑
拒绝待审批设备。

| 参数 | 类型 | 必填 |
|------|------|------|
| device_id | string | ✅ |

### POST /api/pair/revoke 🔑
吊销已配对设备。

| 参数 | 类型 | 必填 |
|------|------|------|
| device_id | string | ✅ |

### GET /api/pair/list 🔑
列出所有设备（不含 token）。

**响应**:
```json
{
  "pending": [{"device_id": "...", "device_name": "...", "requested_at": "..."}],
  "paired": [{"device_id": "...", "device_name": "...", "status": "active"}]
}
```

---

## 认证检查

### GET /api/auth_check 🔓
检查当前请求的认证状态。

**响应**:
```json
{"authenticated": true, "mode": "paired", "device_id": "xxx"}
{"authenticated": false, "mode": "pairing"}
{"authenticated": true, "mode": "open"}
```

### POST /api/login 🔓
兼容接口，验证 device_id + token。

---

## 搜索与浏览

### GET /api/search 🔐
通用搜索接口。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| q | string | | 文本搜索（人物名/地点） |
| date_from | string | | 开始日期 YYYY-MM-DD |
| date_to | string | | 结束日期 YYYY-MM-DD |
| year | string | | 年份 |
| month | string | | 月份（需配合 year） |
| person | string | | 人物名 |
| exclude_screenshots | 0/1 | 1 | 排除截图 |
| exclude_duplicates | 0/1 | 0 | 排除重复 |
| limit | int | 50 | 最大 200 |
| offset | int | 0 | 分页偏移 |

**响应**:
```json
{
  "results": [
    {
      "id": 1, "path": "/photos/img.jpg", "filename": "img.jpg",
      "taken_at": "2024:01:15 10:30:00", "gps_lat": 39.9, "gps_lon": 116.3,
      "gps_city": "Beijing", "width": 4032, "height": 3024,
      "is_screenshot": false, "is_duplicate": false, "dir_label": "旅行",
      "thumb_url": "/api/thumb/1", "original_url": "/api/photo/1",
      "is_favorite": false
    }
  ],
  "total": 1234, "limit": 50, "offset": 0
}
```

### GET /api/photos/random 🔐
随机返回 N 张照片。

| 参数 | 类型 | 默认值 |
|------|------|--------|
| limit | int | 9 (max 50) |

### GET /api/photos/map 🔐
返回所有有 GPS 坐标的照片标记点。

**响应**: `{"markers": [{"id": 1, "lat": 39.9, "lon": 116.3, "taken_at": "...", "city": "Beijing", "thumb_url": "..."}]}`

---

## 照片操作

### GET /api/thumb/{photo_id} 🔐
获取缩略图（支持图片和视频）。

| 参数 | 类型 | 默认值 |
|------|------|--------|
| size | int | 300 |

### GET /api/photo/{photo_id} 🔐
获取原图/原视频。

### GET /api/photo/{photo_id}/download 🔐
下载原文件（Content-Disposition: attachment）。

### POST /api/photos/download 🔐
批量下载（ZIP）。

| 参数 | 类型 | 说明 |
|------|------|------|
| photo_ids | int[] | 照片 ID 列表（最多 50） |

### DELETE /api/photos/{photo_id} 🔐
删除照片记录（不删除磁盘文件）。

---

## 收藏

### POST /api/photos/{photo_id}/favorite 🔐
切换收藏状态（toggle）。

**响应**: `{"favorited": true}` 或 `{"favorited": false}`

### GET /api/favorites 🔐
获取收藏列表。

| 参数 | 类型 | 默认值 |
|------|------|--------|
| limit | int | 50 (max 200) |
| offset | int | 0 |

---

## 人物

### GET /api/persons 🔐
列出所有已识别人物。

### GET /api/persons/{person_id}/photos 🔐
获取人物的所有照片。

### PATCH /api/persons/{person_id} 🔐
重命名人物。

| 参数 | 类型 | 必填 |
|------|------|------|
| name | string | ✅ |

### DELETE /api/persons/{person_id} 🔐
删除人物（取消 faces 关联，保留 face 记录）。

### GET /api/face_thumb/{face_id} 🔓 ⚠️
获取人脸缩略图。**注意：此端点无认证！**

### GET /api/photo_persons/{photo_id} 🔓 ⚠️
获取照片中的人物。**注意：此端点无认证！**

---

## 相册

### GET /api/albums 🔐
列出所有相册。

### POST /api/albums 🔐
创建相册。

| 参数 | 类型 | 必填 |
|------|------|------|
| name | string | ✅ |
| description | string | ❌ |
| cover_photo_id | int | ❌ |

### GET /api/albums/{album_id}/photos 🔐
获取相册内的照片。

### POST /api/albums/{album_id}/photos 🔐
添加照片到相册。

| 参数 | 类型 |
|------|------|
| photo_ids | int[] |

### DELETE /api/albums/{album_id}/photos/{photo_id} 🔐
从相册移除照片。

### DELETE /api/albums/{album_id} 🔐
删除相册。

---

## 分享

### POST /api/shares 🔐
创建分享链接。

| 参数 | 类型 | 说明 |
|------|------|------|
| album_id | int | 分享相册（二选一） |
| photo_ids | int[] | 分享照片（二选一，最多 200） |
| expires_hours | int | 过期时间，默认 72 小时 |

**响应**: `{"share_id": "abc123", "url": "/share/abc123", "expires_at": "..."}`

### GET /api/shares/{share_id} 🔓
访问分享内容（验证过期时间）。

---

## 统计

### GET /api/stats 🔐
基础统计（总照片数等）。

### GET /api/stats/timeline 🔐
按月统计照片数量。

### GET /api/stats/persons 🔐
人物照片数量排行。

### GET /api/stats/locations 🔐
按城市分组统计。

---

## 管理

### GET /api/directories 🔐
列出扫描目录。

### GET /api/duplicates 🔐
重复图片报告。

### POST /api/cleanup/duplicates 🔑
清理重复照片记录。

### POST /api/cleanup/screenshots 🔑
清理截图记录。

### POST /api/face_scan 🔐
启动增量人脸扫描。

### GET /api/face_scan/status 🔐
查询人脸扫描进度。

**响应**: `{"running": true, "total": 100, "processed": 45, "error": null}`

---

## 系统

### GET /api/health 🔓
健康检查。

**响应**: `{"status": "ok", "db": "/path/to/photomemory.db"}`

### GET /admin 🔓
管理界面（需 URL 参数 `?token=ADMIN_TOKEN`）。

### GET /reset-auth 🔓
清除浏览器认证凭证，强制重新配对。

---

## 静态文件

### GET / 🔓
前端首页（index.html）。
