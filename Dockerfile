FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 优先复制依赖清单并安装，充分利用 Docker 镜像层缓存（代码改动不触发依赖重装）
COPY requirements.txt /workspace/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# 复制代码与模板
COPY . /workspace

EXPOSE 28828

CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "28828"]
