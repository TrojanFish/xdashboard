import json
import os
import sqlite3
from typing import List, Dict, Any
from app.config import settings


def get_conn() -> sqlite3.Connection:
    dirname = os.path.dirname(settings.DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False, timeout=20.0)
    # 开启 WAL 模式与繁忙重试，保证多线程与 Web 并发读写零死锁
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # 1. 动态监控源表
    c.execute("""
        CREATE TABLE IF NOT EXISTS watch_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            min_score INTEGER DEFAULT 30,
            min_velocity REAL DEFAULT 0.45,
            min_controversy REAL DEFAULT 0.35,
            enabled INTEGER DEFAULT 1
        )
    """)

    # 2. 账号人设与策略表
    c.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            handle TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            banned_words TEXT NOT NULL,
            is_default INTEGER DEFAULT 1
        )
    """)

    # 3. 原始情报池表
    c.execute("""
        CREATE TABLE IF NOT EXISTS raw_signals (
            post_id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            selftext TEXT,
            permalink TEXT NOT NULL,
            flair TEXT,
            score INTEGER,
            num_comments INTEGER,
            velocity REAL,
            controversy REAL,
            top_comments_json TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. 二创与评论狙击草稿箱
    c.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT UNIQUE NOT NULL,
            persona_id INTEGER,
            status TEXT DEFAULT 'pending',
            worth_posting INTEGER DEFAULT 1,
            skip_reason TEXT,
            narrative_framework TEXT,
            content_tier TEXT DEFAULT 'DEEP_DIVE_MEMO',
            hooks_json TEXT,
            short_post TEXT,
            long_post TEXT,
            sniper_reply TEXT,
            x_search_query TEXT,
            card_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES raw_signals(post_id)
        )
    """)

    # 动态平滑迁移：为已有数据库追加 content_tier 与 short_post 字段（零数据丢失）
    c.execute("PRAGMA table_info(drafts)")
    draft_cols = [col[1] for col in c.fetchall()]
    if "content_tier" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN content_tier TEXT DEFAULT 'DEEP_DIVE_MEMO'")
    if "short_post" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN short_post TEXT")

    # 预置默认监控源（使用 INSERT OR IGNORE 保证已有库平滑补全）
    default_sources = [
        # 1. 深度 AI 与独立开发
        ("LocalLLaMA", "AI_DEV", 25, 0.4, 0.35),
        ("ClaudeAI", "AI_DEV", 25, 0.4, 0.35),
        ("singularity", "AI_DEV", 40, 0.7, 0.40),
        ("SaaS", "AI_DEV", 20, 0.3, 0.40),
        ("ChatGPTCoding", "AI_DEV", 20, 0.3, 0.35),
        # 2. 华尔街宏观、美股期权与量化
        ("wallstreetbets", "FINANCE", 60, 0.8, 0.45),
        ("stocks", "FINANCE", 35, 0.5, 0.40),
        ("algotrading", "FINANCE", 20, 0.25, 0.35),
        ("ValueInvesting", "FINANCE", 25, 0.3, 0.35),
        ("options", "FINANCE", 25, 0.35, 0.40),
        # 3. 头部纯正加密资本与链上金融（严选高信噪比，坚决剔除土狗与Meme水贴）
        ("BitcoinMarkets", "FINANCE", 40, 0.45, 0.35),
        ("ethfinance", "FINANCE", 30, 0.35, 0.35),
        ("defi", "FINANCE", 25, 0.30, 0.35),
    ]
    c.executemany(
        "INSERT OR IGNORE INTO watch_sources (subreddit, category, min_score, min_velocity, min_controversy) VALUES (?, ?, ?, ?, ?)",
        default_sources
    )

    # 预置默认「AI × 金融复合人设」（解决单号跨界问题）
    c.execute("SELECT COUNT(*) FROM personas")
    if c.fetchone()[0] == 0:
        cross_domain_persona = (
            "You are a Silicon Valley AI Systems Architect & Quantitative Tech Investor on X. "
            "You bridge the gap between deep engineering reality and capital market implications:\n"
            "- When analyzing AI/Dev topics: focus on real production bottlenecks, VRAM/compute unit economics, open-source vs closed-source moats, and how this impacts Big Tech ($NVDA, $MSFT, $GOOGL, $META) or SaaS margins.\n"
            "- When analyzing Finance/Trading topics: apply an engineer's first-principles data mindset to dissect market thesis, institutional positioning, asymmetric risk/reward, and retail crowd psychology."
        )
        banned = "delve,tapestry,testament,game-changer,revolutionize,in conclusion,let's dive in,buckle up,realm,beacon,🚀,🧵"
        c.execute(
            "INSERT INTO personas (name, handle, system_prompt, banned_words, is_default) VALUES (?, ?, ?, ?, 1)",
            ("AI × Capital Alpha (复合主号)", settings.X_HANDLE, cross_domain_persona, banned)
        )

    conn.commit()
    conn.close()


def is_signal_processed(post_id: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM raw_signals WHERE post_id = ?", (post_id,)).fetchone()
        conn.close()
        return row is not None
    except sqlite3.OperationalError:
        conn.close()
        init_db()
        return False


def save_signal_and_draft(signal: Dict[str, Any], draft_data: Dict[str, Any], persona_id: int = 1):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO raw_signals
        (post_id, subreddit, category, title, selftext, permalink, flair, score, num_comments, velocity, controversy, top_comments_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal["post_id"], signal["subreddit"], signal["category"], signal["title"],
        signal["selftext"], signal["permalink"], signal["flair"], signal["score"],
        signal["num_comments"], signal["velocity"], signal["controversy"],
        json.dumps(signal["top_comments"], ensure_ascii=False)
    ))

    c.execute("""
        INSERT OR REPLACE INTO drafts
        (post_id, persona_id, status, worth_posting, skip_reason, narrative_framework, content_tier, hooks_json, short_post, long_post, sniper_reply, x_search_query, card_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal["post_id"],
        persona_id,
        "pending" if draft_data["is_worth_posting"] else "archived",
        1 if draft_data["is_worth_posting"] else 0,
        draft_data.get("skip_reason", ""),
        draft_data.get("narrative_framework", "Deep Dive"),
        draft_data.get("content_tier", "DEEP_DIVE_MEMO"),
        json.dumps(draft_data.get("hook_options", []), ensure_ascii=False),
        draft_data.get("short_post", ""),
        draft_data.get("long_form_body", ""),
        draft_data.get("reply_sniper_text", ""),
        draft_data.get("x_search_query", ""),
        json.dumps({
            "title": draft_data.get("visual_card_title", ""),
            "type": draft_data.get("visual_card_type", "terminal_benchmark"),
            "metrics": draft_data.get("visual_card_metrics", [])
        }, ensure_ascii=False)
    ))
    conn.commit()
    conn.close()
