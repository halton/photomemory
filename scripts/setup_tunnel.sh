#!/bin/bash
# PhotoMemory - Cloudflare Named Tunnel 初始化脚本
set -e
TUNNEL_NAME="photomemory"
echo "步骤1: 登录 Cloudflare..."
cloudflared tunnel login
echo "步骤2: 创建 Named Tunnel..."
cloudflared tunnel create $TUNNEL_NAME
TUNNEL_ID=$(cloudflared tunnel list | grep $TUNNEL_NAME | awk "{print \$1}")
echo "Tunnel ID: $TUNNEL_ID"
echo "步骤3: 生成 config.yml..."
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_NAME
credentials-file: ~/.cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: photomemory.yourdomain.com
    service: http://localhost:8765
  - service: http_status:404
EOF
echo "步骤4: 配置 launchd 自启动..."
cat > ~/Library/LaunchAgents/com.photomemory.cloudflared.plist << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.photomemory.cloudflared</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/cloudflared</string>
    <string>tunnel</string><string>run</string><string>photomemory</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/cloudflared.log</string>
  <key>StandardErrorPath</key><string>/tmp/cloudflared.err</string>
</dict>
</plist>
PLIST
launchctl load ~/Library/LaunchAgents/com.photomemory.cloudflared.plist
echo "✅ Named Tunnel 配置完成！编辑 ~/.cloudflared/config.yml 填入你的域名"
