import hashlib
import hmac
import json
import os
import sys
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks, Request, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from app.config import settings
from app.database import (
    get_conn, init_db, get_setting, set_setting, get_all_settings,
    get_raw_signal, save_signal_and_draft
)
from app.scheduler import start_background_scheduler, execute_radar_cycle, get_scan_state
from app.engine.synthesizer import SynthesisEngine

init_db()

app = FastAPI(title="Personal Alpha Studio", docs_url=None, redoc_url=None)

SESSION_COOKIE_NAME = "alpha_session"
SESSION_MAX_AGE = 86400 * 30  # 30 天免登录


@app.on_event("startup")
def startup_event():
    start_background_scheduler()
    try:
        from app.bot.poller import start_telegram_bot_poller
        start_telegram_bot_poller()
    except Exception as e:
        print(f"⚠️ [Telegram Bot] 启动异常: {e}")


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
        secure=settings.COOKIE_SECURE,
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


@app.get("/rss.xml", response_class=Response)
@app.get("/feed.xml", response_class=Response)
def get_rss_feed(request: Request):
    """输出标准 W3C RSS 2.0 规范源，用于自动同步至个人博客、RSS 阅读器或邮件通讯"""
    conn = get_conn()
    query = """
        SELECT d.*, r.title as raw_title, r.permalink as raw_link, r.category as raw_category, r.subreddit
        FROM drafts d
        JOIN raw_signals r ON d.post_id = r.post_id
        WHERE d.worth_posting = 1 AND d.status = 'published'
        ORDER BY d.created_at DESC LIMIT 50
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    base_url = str(request.base_url).rstrip("/")
    build_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    items_xml = []
    for r in rows:
        title = saxutils.escape(r["raw_title"] or "Alpha Intelligence Memo")
        link = saxutils.escape(r["raw_link"] or base_url)
        desc_text = r["short_post"] or (r["long_post"][:300] if r["long_post"] else "")
        desc = saxutils.escape(desc_text)
        category = saxutils.escape(r["raw_category"] or "Tech")
        guid = saxutils.escape(f"alpha_{r['post_id']}")

        pub_date = build_date
        if r["created_at"]:
            try:
                dt = datetime.fromisoformat(r["created_at"])
                pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
            except Exception:
                pass

        body_content = r["long_post"] or r["short_post"] or ""
        items_xml.append(f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="false">{guid}</guid>
      <category>{category}</category>
      <pubDate>{pub_date}</pubDate>
      <description>{desc}</description>
      <content:encoded><![CDATA[{body_content}]]></content:encoded>
    </item>""")

    items_joined = "\n".join(items_xml)
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Personal Alpha Studio — Research Memos</title>
    <link>{base_url}</link>
    <description>AI &amp; Capital Cross-Domain Intelligence &amp; Open Source Teardowns</description>
    <language>en</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="{base_url}/rss.xml" rel="self" type="application/rss+xml"/>
{items_joined}
  </channel>
</rss>"""

    return Response(content=xml_content, media_type="application/xml")


@app.get("/api/config")
def get_config(username: str = Depends(verify_credentials)):
    """返回前端渲染所需的基础配置与系统开关"""
    return {
        "x_handle": settings.X_HANDLE,
        "has_gemini_key": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your_gemini_api_key_here"),
        "has_reddit_auth": bool((settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET) or settings.REDDIT_PROXY_URL),
        "has_telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ADMIN_CHAT_ID),
        "telegram_channel": settings.TELEGRAM_CHANNEL_ID,
        "scan_interval": settings.SCAN_INTERVAL_MINUTES,
        "triage_model": settings.TRIAGE_MODEL,
        "synthesis_model": settings.SYNTHESIS_MODEL,
        "username": username,
        "settings": get_all_settings(),
    }


@app.get("/api/settings")
def fetch_settings(username: str = Depends(verify_credentials)):
    """获取所有系统开关设置"""
    return {"ok": True, "settings": get_all_settings()}


class SettingUpdate(BaseModel):
    key: str
    value: str


@app.post("/api/settings")
def update_setting(payload: SettingUpdate, username: str = Depends(verify_credentials)):
    """更新单个系统开关设置"""
    set_setting(payload.key, payload.value)
    return {"ok": True, "settings": get_all_settings()}


@app.get("/api/drafts")
def get_drafts(category: str = "ALL", status: str = "all_active", limit: int = 100, offset: int = 0, username: str = Depends(verify_credentials)):
    conn = get_conn()
    query = """
        SELECT d.*, r.subreddit, r.title, r.permalink, r.score, r.num_comments, r.velocity, r.controversy, r.category
        FROM drafts d
        JOIN raw_signals r ON d.post_id = r.post_id
        WHERE 1=1
    """
    params = []
    if category == "HACKER_NEWS":
        query += " AND r.subreddit = 'hackernews'"
    elif category == "GITHUB_TRENDING":
        query += " AND r.category = 'GITHUB_TRENDING'"
    elif category != "ALL":
        query += " AND r.category = ?"
        params.append(category)
    if status == "all_active":
        query += " AND d.status IN ('raw_unprocessed', 'pending')"
    elif status != "ALL":
        query += " AND d.status = ?"
        params.append(status)

    query += " ORDER BY d.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
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

    # 如果在 Web 端标记为已发布，自动联动广播至 Telegram Channel
    if payload.status == "published":
        try:
            from app.bot.manager import broadcast_published_draft
            broadcast_published_draft(post_id)
        except Exception as e_bc:
            print(f"[Telegram Broadcast 异常]: {e_bc}")

    return {"ok": True}


class DraftEdit(BaseModel):
    long_post: str
    short_post: Optional[str] = None
    sniper_reply: str
    hooks: Optional[list] = None


@app.post("/api/drafts/{post_id}/save")
def save_draft(post_id: str, payload: DraftEdit, username: str = Depends(verify_credentials)):
    conn = get_conn()
    hooks_json = json.dumps(payload.hooks, ensure_ascii=False) if payload.hooks is not None else None
    if payload.short_post is not None:
        if hooks_json is not None:
            conn.execute("UPDATE drafts SET long_post = ?, short_post = ?, sniper_reply = ?, hooks_json = ? WHERE post_id = ?",
                         (payload.long_post, payload.short_post, payload.sniper_reply, hooks_json, post_id))
        else:
            conn.execute("UPDATE drafts SET long_post = ?, short_post = ?, sniper_reply = ? WHERE post_id = ?",
                         (payload.long_post, payload.short_post, payload.sniper_reply, post_id))
    else:
        if hooks_json is not None:
            conn.execute("UPDATE drafts SET long_post = ?, sniper_reply = ?, hooks_json = ? WHERE post_id = ?",
                         (payload.long_post, payload.sniper_reply, hooks_json, post_id))
        else:
            conn.execute("UPDATE drafts SET long_post = ?, sniper_reply = ? WHERE post_id = ?",
                         (payload.long_post, payload.sniper_reply, post_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/drafts/{post_id}/synthesize")
def synthesize_post(post_id: str, username: str = Depends(verify_credentials)):
    """针对单条情报执行/重新执行 AI 深度二创（支持待二创情报与历史草稿一键重塑）"""
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未检测到有效的 GEMINI_API_KEY！请先在 .env 文件中填入 Google Gemini API Key 后再调用 AI 二创。"
        )
    raw_sig = get_raw_signal(post_id)
    if not raw_sig:
        raise HTTPException(status_code=404, detail="未找到对应的原始情报数据")

    engine = SynthesisEngine()
    try:
        draft_data = engine.synthesize(raw_sig)
        save_signal_and_draft(raw_sig, draft_data)
        return {"ok": True, "message": "AI 二创加工成功！", "draft": draft_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 二创加工失败: {e}")


@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks, username: str = Depends(verify_credentials)):
    """使用 FastAPI 原生 BackgroundTasks 异步执行，带密钥检测与防重复并发保护"""
    auto_synthesize = (get_setting("auto_synthesize", "0") == "1")
    if auto_synthesize and (not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key_here"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前处于「自动 AI 二创」模式，但未检测到有效的 GEMINI_API_KEY！请在 .env 中填入 Google Gemini API Key，或切换为「仅抓取原始情报 (省 Token)」模式。"
        )
    state = get_scan_state()
    if state.get("running"):
        return {"ok": True, "message": "全网扫描流水线正在进行中，请观察进度...", "state": state}

    background_tasks.add_task(execute_radar_cycle)
    mode_tag = "全自动扫描+二创" if auto_synthesize else "原始线索抓取(手动模式)"
    return {"ok": True, "message": f"雷达扫描已启动 [{mode_tag}]！", "state": state}


@app.get("/api/scan/status")
def get_scan_status_api(username: str = Depends(verify_credentials)):
    """获取当前扫描流水线的实时进度"""
    return get_scan_state()


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
    sub = payload.subreddit.strip().lstrip("/").removeprefix("r/").removeprefix("R/").rstrip("/")
    if not sub:
        conn.close()
        raise HTTPException(status_code=400, detail="社区名称不能为空")
    try:
        conn.execute(
            "INSERT INTO watch_sources (subreddit, category, min_score, min_velocity, min_controversy, enabled) VALUES (?, ?, ?, ?, ?, 1)",
            (sub, payload.category, payload.min_score, payload.min_velocity,
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
