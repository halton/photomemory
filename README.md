# PhotoMemory

本地图片智能检索系统 — 按时间、地点、人物检索 NAS 上的照片。

## 功能
- EXIF 时间/地点索引
- 人脸识别 + 人物标签
- 重复图检测提醒
- 截图过滤
- 多用户支持
- Web UI + OpenClaw Chat 接入

## 技术栈
- Python (处理管线)
- SQLite (元数据)
- Qdrant (向量数据库)
- Flask (API)
- Docker Compose (部署)

## 目录结构
- `backend/` — API 服务 + 处理逻辑
- `frontend/` — Web UI
- `scripts/` — 批处理脚本
- `docker/` — Docker Compose 配置
- `docs/` — 设计文档
