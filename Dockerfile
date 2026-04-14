# PhotoMemory Dockerfile
# 基于官方 python 镜像构建，最小、稳定，带注释

FROM python:3.11-slim AS base

# 1. 装常用工具库可选
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential git curl libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. 拷贝 requirements 和安装依赖。分别处理通用和 phase1 依赖（其它依赖按需再补）
COPY scripts/requirements.txt scripts/requirements-phase1.txt ./scripts/
RUN pip install --no-cache-dir -r scripts/requirements.txt

# 3. 拷贝项目主代码（可优化：只拷贝必须目录，减小镜像体积）
COPY backend ./backend
COPY db ./db
COPY scripts ./scripts
COPY start.sh run_server.sh ./

# 4. 镜像中预置启动方式，提供参数化入口（推荐用 start.sh，兼容 run_server.sh）
EXPOSE 8765
CMD ["/bin/bash", "./start.sh", "--skip-tunnel"]

# 详细说明：
# - python3.11-slim 足够新且可减小镜像。
# - 依赖如opencv需libgl，sqlite用python自带。
# - start.sh 实现了 API 启动和健康检查、适配参数。新环境建议参数 --skip-tunnel 防止 cf tunnel 报错。
