#!/bin/bash
# PhotoMemory - 挂载脚本
# 用法: ./mount_nas.sh

NAS_HOST="nengcloud"
NAS_PATH="/volume1/photo"
MOUNT_POINT="/Volumes/photo"

echo "🔗 挂载 NAS: $NAS_HOST$NAS_PATH → $MOUNT_POINT"

# 确保挂载点存在
mkdir -p "$MOUNT_POINT"

# 优先 SMB 挂载（Synology photo 共享）
echo "尝试 SMB 挂载..."
mount_smbfs "//guest@$NAS_HOST/photo" "$MOUNT_POINT" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ SMB 挂载成功 (guest): $MOUNT_POINT"
    ls "$MOUNT_POINT" | head -5
else
    # 如果 guest 不行，提示输入账号
    echo "guest 失败，尝试带账号挂载..."
    echo "⚠️  请手动在 Finder 中挂载:"
    echo "   Cmd+K → smb://$NAS_HOST/photo"
    echo "   或运行: mount_smbfs '//用户名:密码@$NAS_HOST/photo' $MOUNT_POINT"
fi
