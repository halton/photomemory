# PhotoMemory - 项目状态

## 测试数据集
- 路径: `/Volumes/backup/photos/Halton/iPhone/2026`
- 文件数: 68（图片+视频）
- 结构: `Halton/iPhone/年/月/`
- 用途: **开发和测试专用**，正式数据集待换

## 进度
- [x] Phase 1: EXIF索引 + 重复检测 + 截图过滤 ✅
- [ ] Phase 2: 人脸检测 + Embedding + 人物标签
- [ ] Phase 3: API Server
- [ ] Phase 4: Web UI
- [ ] Phase 5: OpenClaw Chat 接入

## 数据库
- 测试DB: `/tmp/photomemory_test.db`
- 正式DB: `待定`

## NAS 连接
- Host: `nengcloud` (198.20.2.165)
- 挂载: SMB via Finder → `/Volumes/backup`
- NFS: 未启用（RPC连接被拒）

## 待办
- [ ] Phase 2: 人脸识别开发
- [ ] 正式数据集路径确认（用户会告知）
- [ ] NFS 优化（可选）
