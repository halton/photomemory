#!/bin/bash
for pid in $(lsof -ti :8765 2>/dev/null); do
  kill -9 "$pid" 2>/dev/null
done
sleep 1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/backend/api_server.py" \
  --db "$SCRIPT_DIR/data/photomemory.db" \
  --port 8765 \
  --admin-token "1VsnIeo2KbxpDcSMKSo501WAlxjJyEaAXtsLxwLqCGU"
