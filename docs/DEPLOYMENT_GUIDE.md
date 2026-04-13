# PhotoMemory 生产部署指南

## 目录

1. [系统要求](#1-系统要求)
2. [快速部署（macOS 本地）](#2-快速部署macos-本地)
3. [Docker 化部署](#3-docker-化部署)
4. [Nginx 反向代理](#4-nginx-反向代理)
5. [Cloudflare Tunnel 公网暴露](#5-cloudflare-tunnel-公网暴露)
6. [NAS 挂载与备份](#6-nas-挂载与备份)
7. [Systemd / Launchd 服务管理](#7-服务管理)
8. [监控与健康检查](#8-监控与健康检查)

---

## 1. 系统要求

| 组件 | 最低要求 |
|------|---------|
| Python | 3.10+ |
| 磁盘 | 数据库 ~1GB/10万照片 |
| 内存 | 2GB（人脸检测需 4GB+） |
| ffmpeg | 视频缩略图需要 |
| SQLite | 3.35+ |

**Python 依赖**（`scripts/requirements.txt`）:
```
flask
flask-cors
pillow
pillow-heif
insightface
onnxruntime
scikit-learn
geopy
```

## 2. 快速部署（macOS 本地）

```bash
cd /path/to/photomemory

# 安装依赖
pip3 install -r scripts/requirements.txt

# Phase 1: 索引照片
python3 scripts/phase1_index.py --dirs /Volumes/photo --db ./photomemory.db

# Phase 2: 人脸检测与聚类
python3 scripts/phase2_faces.py --db ./photomemory.db

# Phase 3: 启动 API
python3 backend/api_server.py --db ./photomemory.db --port 8765 --admin-token "your-secret-token"
```

**挂载 NAS 照片源**:
```bash
./scripts/mount_nas.sh
# 或手动: mount_smbfs "//guest@nengcloud/photo" /Volumes/photo
```

## 3. Docker 化部署

### Dockerfile

```dockerfile
FROM python:3.11-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1-mesa-glx libglib2.0-0 sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY scripts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/

# 数据目录
VOLUME ["/data", "/photos"]

EXPOSE 8765

ENV PM_ADMIN_TOKEN=""

CMD ["python3", "backend/api_server.py", \
     "--db", "/data/photomemory.db", \
     "--port", "8765", \
     "--host", "0.0.0.0"]
```

### docker-compose.yml

```yaml
version: "3.8"
services:
  photomemory:
    build: .
    ports:
      - "8765:8765"
    volumes:
      - ./data:/data              # 数据库 + 设备文件
      - /Volumes/photo:/photos:ro # 照片源（只读）
    environment:
      - PM_ADMIN_TOKEN=your-secret-token-here
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

```bash
docker compose up -d
```

## 4. Nginx 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name photomemory.yourdomain.com;

    ssl_certificate     /etc/ssl/certs/photomemory.crt;
    ssl_certificate_key /etc/ssl/private/photomemory.key;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: blob: https://basemaps.cartocdn.com https://*.tile.openstreetmap.org;" always;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 大文件下载超时
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # 缩略图缓存
    location /api/thumb/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_cache_valid 200 1h;
        expires 1h;
        add_header Cache-Control "public, max-age=3600";
    }
}

# HTTP → HTTPS
server {
    listen 80;
    server_name photomemory.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

## 5. Cloudflare Tunnel 公网暴露

项目已提供 `scripts/setup_tunnel.sh`，执行：

```bash
./scripts/setup_tunnel.sh
```

该脚本会：
1. 登录 Cloudflare
2. 创建 Named Tunnel `photomemory`
3. 生成 `~/.cloudflared/config.yml`
4. 配置 macOS launchd 自启动

手动启动隧道：
```bash
cloudflared tunnel run photomemory
```

## 6. NAS 挂载与备份

### 挂载

```bash
./scripts/mount_nas.sh
# SMB: //guest@nengcloud/photo → /Volumes/photo
```

### 自动备份

```bash
./scripts/backup_to_nas.sh
```

备份内容：
- SQLite DB 热快照（`sqlite3 .backup`）
- 设备配对文件
- 保留最近 7 个快照

建议 cron 配置：
```cron
0 3 * * * /path/to/photomemory/scripts/backup_to_nas.sh >> /var/log/pm-backup.log 2>&1
```

## 7. 服务管理

### macOS launchd

```xml
<!-- ~/Library/LaunchAgents/com.photomemory.api.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.photomemory.api</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/photomemory/backend/api_server.py</string>
    <string>--db</string><string>/path/to/photomemory.db</string>
    <string>--port</string><string>8765</string>
    <string>--admin-token</string><string>YOUR_TOKEN</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/photomemory.log</string>
  <key>StandardErrorPath</key><string>/tmp/photomemory.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.photomemory.api.plist
```

### Linux systemd

```ini
# /etc/systemd/system/photomemory.service
[Unit]
Description=PhotoMemory API Server
After=network.target

[Service]
Type=simple
User=photomemory
WorkingDirectory=/opt/photomemory
Environment=PM_ADMIN_TOKEN=your-secret-token
ExecStart=/usr/bin/python3 backend/api_server.py --db /opt/photomemory/data/photomemory.db --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now photomemory
```

## 8. 监控与健康检查

项目提供 `scripts/health_check.sh`，检查：
- API Server 状态（`/api/health`）
- NAS 挂载状态
- Cloudflared 进程
- 数据库文件大小

```bash
./scripts/health_check.sh
```

建议通过 cron 每 5 分钟运行一次，异常时发送通知。

---

## 安全清单

- [ ] 设置 `--admin-token`（**必须**）
- [ ] 使用 HTTPS（Cloudflare Tunnel 或 Nginx SSL）
- [ ] 限制 `photomemory_devices.json` 文件权限：`chmod 600`
- [ ] 数据库文件权限：`chmod 600 photomemory.db`
- [ ] 定期备份数据库
- [ ] 配置防火墙，不直接暴露 8765 端口
