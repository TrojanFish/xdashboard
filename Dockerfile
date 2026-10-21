FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    requests \
    pydantic \
    google-genai \
    apscheduler \
    python-dotenv

COPY . /workspace

EXPOSE 28828

CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "28828"]
