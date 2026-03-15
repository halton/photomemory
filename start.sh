#!/bin/bash
# PhotoMemory 一键启动
# 用法: ./start.sh [db路径]

DB=${1:-"/tmp/photomemory_test.db"}
PORT=8765
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 PhotoMemory 启动"
echo "   DB  : $DB"
echo "   UI  : http://localhost:$PORT"
echo ""

# 停止旧进程
pkill -f "api_server.py" 2>/dev/null

# 启动 API + 前端
python3 "$SCRIPT_DIR/backend/api_server.py" --db "$DB" --port $PORT &
API_PID=$!

sleep 1.5

# 检查是否启动成功
if curl -s "http://localhost:$PORT/api/health" > /dev/null 2>&1; then
    echo "✅ 服务启动成功 (PID: $API_PID)"
    echo ""
    echo "打开浏览器: http://localhost:$PORT"
    open "http://localhost:$PORT" 2>/dev/null || true
else
    echo "❌ 启动失败，检查端口 $PORT 是否被占用"
    exit 1
fi

wait $API_PID
