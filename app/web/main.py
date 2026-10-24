import hashlib
import hmac
import json
import os
import sys
import time
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks, Request, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from app.config import settings
from app.database import get_conn, init_db
from app.scheduler import start_background_scheduler, execute_radar_cycle

init_db()

app = FastAPI(title="Personal Alpha Studio", docs_url=None, redoc_url=None)

SESSION_COOKIE_NAME = "alpha_session"
SESSION_MAX_AGE = 86400 * 30  # 30 天免登录


@app.on_event("startup")
def startup_event():
    start_background_scheduler()


def create_session_token(username: str = "admin") -> str:
    """使用 HMAC-SHA256 生成安全的防篡改会话 Token"""
    ts = int(time.time())
    data = f"{username}:{ts}"
    sig = hmac.new(settings.STUDIO_PASSWORD.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{sig}"


def verify_session_token(token: Optional[str]) -> bool:
    """验证会话 Token 的有效性与防篡改签名"""
    if not token:
        return False
    parts = token.split(":")
    if len(parts) != 3:
        return False
    username, ts_str, sig = parts
    if username != "admin":
        return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if time.time() - ts > SESSION_MAX_AGE:
        return False
    expected_data = f"{username}:{ts}"
    expected_sig = hmac.new(settings.STUDIO_PASSWORD.encode(), expected_data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def verify_credentials(request: Request, alpha_session: Optional[str] = Cookie(default=None)) -> str:
    """API 鉴权逻辑：优先 Cookie 会话，兼顾 cURL/脚本的 HTTP Basic Auth"""
    # 1. 优先校验 Cookie 会话
    if alpha_session and verify_session_token(alpha_session):
        return "admin"

    # 2. 兼容 HTTP Basic Auth (用于脚本或 cURL 请求)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Basic "):
        try:
            import base64
            encoded = auth_header.split(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            u, p = decoded.split(":", 1)
            if u == "admin" and p == settings.STUDIO_PASSWORD:
                return "admin"
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未授权访问，请先登录",
    )


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(payload: LoginRequest, response: Response):
    """登录接口：校验密码并下发 HttpOnly 签名 Cookie"""
    if payload.username != "admin" or payload.password != settings.STUDIO_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码错误，请检查 .env 中的 STUDIO_PASSWORD"
        )
    token = create_session_token(payload.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    return {"ok": True, "message": "登录成功"}


@app.post("/api/logout")
def logout(response: Response):
    """登出接口：销毁客户端 Cookie"""
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"ok": True, "message": "已退出登录"}


@app.get("/login", response_class=HTMLResponse)
def login_page(alpha_session: Optional[str] = Cookie(default=None)):
    """独立深色登录页面，已登录则直接跳转首页"""
    if alpha_session and verify_session_token(alpha_session):
        return RedirectResponse(url="/", status_code=302)
    template_path = os.path.join(os.path.dirname(__file__), "templates", "login.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse)
def index(alpha_session: Optional[str] = Cookie(default=None)):
    """工作台主页：未登录自动重定向至 /login"""
    if not (alpha_session and verify_session_token(alpha_session)):
        return RedirectResponse(url="/login", status_code=302)
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/config")
def get_config(username: str = Depends(verify_credentials)):
    """返回前端渲染所需的基础配置（避免硬编码）"""
    return {
        "x_handle": settings.X_HANDLE,
        "has_gemini_key": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your_gemini_api_key_here"),
        "scan_interval": settings.SCAN_INTERVAL_MINUTES,
        "triage_model": settings.TRIAGE_MODEL,
        "synthesis_model": settings.SYNTHESIS_MODEL,
        "username": username,
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
    short_post: Optional[str] = None
    sniper_reply: str


@app.post("/api/drafts/{post_id}/save")
def save_draft(post_id: str, payload: DraftEdit, username: str = Depends(verify_credentials)):
    conn = get_conn()
    if payload.short_post is not None:
        conn.execute("UPDATE drafts SET long_post = ?, short_post = ?, sniper_reply = ? WHERE post_id = ?",
                     (payload.long_post, payload.short_post, payload.sniper_reply, post_id))
    else:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
