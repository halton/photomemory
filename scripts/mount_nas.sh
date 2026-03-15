#!/bin/bash
# PhotoMemory - 挂载脚本
# 用法: ./mount_nas.sh

NAS_HOST="nengcloud"
NAS_PATH="/volume1/backup_photos"
MOUNT_POINT="/Volumes/nas-photos"

echo "🔗 挂载 NAS: $NAS_HOST$NAS_PATH → $MOUNT_POINT"

# 确保挂载点存在
sudo mkdir -p "$MOUNT_POINT"

# 尝试 NFS 挂载（快）
echo "尝试 NFS 挂载..."
sudo mount -t nfs -o resvport,soft,timeo=10 "$NAS_HOST:$NAS_PATH" "$MOUNT_POINT" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ NFS 挂载成功: $MOUNT_POINT"
    ls "$MOUNT_POINT" | head -5
else
    echo "⚠️  NFS 失败，请在 Finder 中手动挂载:"
    echo "   Cmd+K → smb://$NAS_HOST/backup_photos"
fi
