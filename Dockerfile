FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=28828

# 安装系统字体包 (含 DejaVu 与 Noto Sans CJK 中文字体，确保数据研报卡片中文排版清晰不乱码)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fonts-noto-cjk \
    fontconfig \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 优先复制依赖清单并安装，充分利用 Docker 镜像层缓存（代码改动不触发依赖重装）
COPY requirements.txt /workspace/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# 复制代码与模板
COPY . /workspace

EXPOSE 28828

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT}/login || exit 1

CMD ["sh", "-c", "uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT:-28828}"]
