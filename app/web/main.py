import json
import os
import sys
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from app.config import settings
from app.database import get_conn, init_db
from app.scheduler import start_background_scheduler, execute_radar_cycle

init_db()

app = FastAPI(title="Personal Alpha Studio", docs_url=None, redoc_url=None)
security = HTTPBasic()


@app.on_event("startup")
def startup_event():
    start_background_scheduler()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin" or credentials.password != settings.STUDIO_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/api/config")
def get_config(username: str = Depends(verify_credentials)):
    """返回前端渲染所需的基础配置（避免硬编码）"""
    return {
        "x_handle": settings.X_HANDLE,
        "has_gemini_key": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your_gemini_api_key_here"),
        "scan_interval": settings.SCAN_INTERVAL_MINUTES,
        "triage_model": settings.TRIAGE_MODEL,
        "synthesis_model": settings.SYNTHESIS_MODEL,
    }


@app.get("/api/drafts")
def get_drafts(category: str = "ALL", status: str = "pending", username: str = Depends(verify_credentials)):
    conn = get_conn()
    query = """
        SELECT d.*, r.subreddit, r.title, r.permalink, r.score, r.num_comments, r.velocity, r.controversy, r.category
        FROM drafts d
        JOIN raw_signals r ON d.post_id = r.post_id
        WHERE 1=1
    """
    params = []
    if category != "ALL":
        query += " AND r.category = ?"
        params.append(category)
    if status != "ALL":
        query += " AND d.status = ?"
        params.append(status)

    query += " ORDER BY d.created_at DESC LIMIT 100"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item["hooks"] = json.loads(item["hooks_json"]) if item["hooks_json"] else []
            item["card"] = json.loads(item["card_json"]) if item["card_json"] else {}
        except Exception:
            item["hooks"] = []
            item["card"] = {}
        results.append(item)
    return results


class StatusUpdate(BaseModel):
    status: str


@app.post("/api/drafts/{post_id}/status")
def update_status(post_id: str, payload: StatusUpdate, username: str = Depends(verify_credentials)):
    conn = get_conn()
    conn.execute("UPDATE drafts SET status = ? WHERE post_id = ?", (payload.status, post_id))
    conn.commit()
    conn.close()
    return {"ok": True}


class DraftEdit(BaseModel):
    long_post: str
    sniper_reply: str


@app.post("/api/drafts/{post_id}/save")
def save_draft(post_id: str, payload: DraftEdit, username: str = Depends(verify_credentials)):
    conn = get_conn()
    conn.execute("UPDATE drafts SET long_post = ?, sniper_reply = ? WHERE post_id = ?",
                 (payload.long_post, payload.sniper_reply, post_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks, username: str = Depends(verify_credentials)):
    """使用 FastAPI 原生 BackgroundTasks 异步执行，保证稳定安全、跨平台零子进程报错"""
    background_tasks.add_task(execute_radar_cycle)
    return {"ok": True, "message": "全网雷达扫描已在后台启动，1-2 分钟后刷新页面即可查看最新草稿。"}


@app.get("/api/sources")
def get_sources(username: str = Depends(verify_credentials)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM watch_sources").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class SourceCreate(BaseModel):
    subreddit: str
    category: str
    min_score: int
    min_velocity: float
    min_controversy: float


@app.post("/api/sources")
def add_source(payload: SourceCreate, username: str = Depends(verify_credentials)):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO watch_sources (subreddit, category, min_score, min_velocity, min_controversy, enabled) VALUES (?, ?, ?, ?, ?, 1)",
            (payload.subreddit.strip(), payload.category, payload.min_score, payload.min_velocity,
             payload.min_controversy)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"添加失败或板块已存在: {e}")
    conn.close()
    return {"ok": True}


@app.post("/api/sources/{source_id}/toggle")
def toggle_source(source_id: int, username: str = Depends(verify_credentials)):
    conn = get_conn()
    row = conn.execute("SELECT enabled FROM watch_sources WHERE id = ?", (source_id,)).fetchone()
    if row:
        new_val = 0 if row["enabled"] == 1 else 1
        conn.execute("UPDATE watch_sources SET enabled = ? WHERE id = ?", (new_val, source_id))
        conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(username: str = Depends(verify_credentials)):
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
