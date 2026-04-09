#!/bin/bash
# PhotoMemory 一键启动
# 用法: ./start.sh [--db 路径] [--skip-tunnel]

DB="/tmp/photomemory_test.db"
SKIP_TUNNEL=0
PORT=8765
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 解析参数
while [[ $# -gt 0 ]]; do
  case $1 in
    --db)
      DB="$2"; shift 2;;
    --skip-tunnel)
      SKIP_TUNNEL=1; shift;;
    *)
      # 向后兼容 ./start.sh [db路径]
      if [[ -z "$DB_PARAM_USED" ]]; then
        DB="$1"; DB_PARAM_USED=1; shift;
      else
        shift;
      fi
      ;;
  esac
done

export PM_DB="$DB"

echo "🚀 PhotoMemory 启动"
echo "   DB  : $DB"
echo "   UI  : http://localhost:$PORT"
echo ""

# 启动后健康检查
bash "$SCRIPT_DIR/scripts/health_check.sh"
echo ""

# 停止旧进程
pkill -f "api_server.py" 2>/dev/null

# 启动 API + 前端
python3 "$SCRIPT_DIR/backend/api_server.py" --db "$DB" --port $PORT &
API_PID=$!

sleep 1.5

# 启动 Cloudflare Tunnel（可跳过）
if [[ $SKIP_TUNNEL -eq 0 ]]; then
  if [ -f "$HOME/.cloudflared/config.yml" ]; then
    echo "使用 Cloudflare Named Tunnel..."
    cloudflared tunnel run photomemory &
    TUNNEL_PID=$!
  else
    echo "未检测到 config.yml，使用临时 Cloudflare Tunnel..."
    cloudflared tunnel --url http://localhost:$PORT &
    TUNNEL_PID=$!
  fi
else
  echo "--skip-tunnel: 跳过 Cloudflare Tunnel 启动"
fi

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
