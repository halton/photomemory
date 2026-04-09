#!/bin/bash
# PhotoMemory - 增量备份到 NAS
# 备份内容：SQLite DB、设备文件、人脸向量（qdrant）
# 保留策略：保留最近 7 个 DB 快照

set -e

BACKUP_DIR="/Volumes/backup/photomemory-backup"
DB_SRC="/tmp/photomemory_test.db"
DEVICES_SRC="/tmp/photomemory_devices.json"
QDRANT_SRC="$HOME/.openclaw/workspace-daddy/projects/photomemory/qdrant_storage"
MAX_SNAPSHOTS=7

DATE=$(date +%Y%m%d-%H%M%S)

echo "[$(date)] 开始备份 PhotoMemory..."

# 确保备份目录存在
mkdir -p "$BACKUP_DIR/db-snapshots"
mkdir -p "$BACKUP_DIR/devices"

# 1. SQLite DB 增量快照（使用 sqlite3 .backup，热备份安全）
if [ -f "$DB_SRC" ]; then
    SNAP="$BACKUP_DIR/db-snapshots/photomemory_${DATE}.db"
    sqlite3 "$DB_SRC" ".backup '$SNAP'"
    echo "[$(date)] DB 快照完成: $SNAP"

    # 清理超过 MAX_SNAPSHOTS 的旧快照
    ls -t "$BACKUP_DIR/db-snapshots/"*.db 2>/dev/null | tail -n +$((MAX_SNAPSHOTS + 1)) | xargs rm -f 2>/dev/null && true
    echo "[$(date)] 保留最近 $MAX_SNAPSHOTS 个快照"
else
    echo "[$(date)] ⚠️  DB 不存在，跳过: $DB_SRC"
fi

# 2. 设备文件（全量覆盖，文件小）
if [ -f "$DEVICES_SRC" ]; then
    cp "$DEVICES_SRC" "$BACKUP_DIR/devices/photomemory_devices_${DATE}.json"
    # 同时保留一份 latest
    cp "$DEVICES_SRC" "$BACKUP_DIR/devices/photomemory_devices_latest.json"
    # 清理旧设备文件，只保留 7 个
    ls -t "$BACKUP_DIR/devices/"photomemory_devices_2*.json 2>/dev/null | tail -n +$((MAX_SNAPSHOTS + 1)) | xargs rm -f 2>/dev/null && true
    echo "[$(date)] 设备文件备份完成"
fi

# 3. Qdrant 向量存储（rsync 增量）
if [ -d "$QDRANT_SRC" ]; then
    rsync -a --delete "$QDRANT_SRC/" "$BACKUP_DIR/qdrant_storage/"
    echo "[$(date)] Qdrant 向量库增量同步完成"
fi

echo "[$(date)] ✅ 备份完成 → $BACKUP_DIR"
