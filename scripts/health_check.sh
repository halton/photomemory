#!/bin/bash
# PhotoMemory 健康检查脚本

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# API Server 检查
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/health)
if [ "$API_STATUS" == "200" ]; then
    API_MSG="${GREEN}✅ API Server 正常${NC}"
else
    API_MSG="${RED}❌ API Server 异常${NC}"
fi

# NAS 检查
if ls /Volumes/backup/photos/ 1>/dev/null 2>&1; then
    NAS_MSG="${GREEN}✅ NAS 已挂载${NC} ( /Volumes/backup/photos )"
else
    NAS_MSG="${RED}❌ NAS 未挂载${NC} (/Volumes/backup/photos)"
fi

# cloudflared 检查
CLOUDFLARE_STATUS=$(pgrep -f "[c]loudflared.*tunnel" | wc -l)
if [ "$CLOUDFLARE_STATUS" -ge 1 ]; then
    CLOUDFLARE_MSG="${GREEN}✅ cloudflared 运行中${NC}"
else
    CLOUDFLARE_MSG="${RED}❌ cloudflared 未运行${NC}"
fi

# DB 文件与统计
DB_PATH=${PM_DB:-/tmp/photomemory_test.db}
if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(du -h "$DB_PATH" | awk '{print $1}')
    PHOTO_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM photos;" 2>/dev/null || echo "?")
    DB_MSG="${GREEN}✅ DB 正常${NC} ($DB_PATH, $DB_SIZE, ${PHOTO_COUNT} 张)"
else
    DB_MSG="${RED}❌ DB 未找到${NC} ($DB_PATH)"
fi

# 彩色输出
cat <<EOF
================= Health Check =================
$API_MSG
$NAS_MSG
$CLOUDFLARE_MSG
$DB_MSG
================================================
EOF
