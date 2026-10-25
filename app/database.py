import json
import os
import sqlite3
from typing import List, Dict, Any, Optional
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

    # 5. 系统开关与全局偏好设置表
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    default_settings = [
        ("auto_synthesize", "0"),    # 0: 仅抓取原始情报，待用户手动挑选二创 (省 Token / 默认推荐); 1: 抓取后自动二创
        ("auto_scan_enabled", "1"),  # 1: 开启后台定时巡航; 0: 暂停后台自动巡航 (仅允许手动点击扫描)
        ("content_language", "en"),  # 'en' = English, 'zh' = Simplified Chinese
        ("hook_pref_1", "0"),        # count of times Hook #1 was chosen
        ("hook_pref_2", "0"),
        ("hook_pref_3", "0"),
    ]
    c.executemany("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", default_settings)

    # 动态平滑迁移：为已有数据库追加 content_tier 与 short_post 字段（零数据丢失）
    c.execute("PRAGMA table_info(drafts)")
    draft_cols = [col[1] for col in c.fetchall()]
    if "content_tier" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN content_tier TEXT DEFAULT 'DEEP_DIVE_MEMO'")
    if "short_post" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN short_post TEXT")
    if "hashtags_json" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN hashtags_json TEXT DEFAULT '[]'")
    if "thread_json" not in draft_cols:
        c.execute("ALTER TABLE drafts ADD COLUMN thread_json TEXT DEFAULT '[]'")

    # 动态平滑迁移：将已有旧版 'FINANCE' 细化归类为清晰的二级赛道
    c.execute("UPDATE watch_sources SET category = 'MACRO_STOCKS' WHERE subreddit IN ('stocks', 'wallstreetbets', 'investing', 'ValueInvesting', 'options', 'algotrading') AND category = 'FINANCE'")
    c.execute("UPDATE watch_sources SET category = 'CRYPTO_ALPHA' WHERE subreddit IN ('BitcoinMarkets', 'ethfinance', 'defi') AND category = 'FINANCE'")
    c.execute("UPDATE raw_signals SET category = 'MACRO_STOCKS' WHERE subreddit IN ('stocks', 'wallstreetbets', 'investing', 'ValueInvesting', 'options', 'algotrading') AND category = 'FINANCE'")
    c.execute("UPDATE raw_signals SET category = 'CRYPTO_ALPHA' WHERE subreddit IN ('BitcoinMarkets', 'ethfinance', 'defi') AND category = 'FINANCE'")

    # 预置默认监控源（四条核心商业化赛道，保证已有库平滑补全）
    default_sources = [
        # 1. 深度 AI 与独立工程生态 (AI_DEV)
        ("LocalLLaMA", "AI_DEV", 25, 0.4, 0.35),
        ("ClaudeAI", "AI_DEV", 25, 0.4, 0.35),
        ("singularity", "AI_DEV", 40, 0.7, 0.40),
        ("SaaS", "AI_DEV", 20, 0.3, 0.40),
        ("ChatGPTCoding", "AI_DEV", 20, 0.3, 0.35),

        # 2. 美股异动、华尔街宏观与期权异动 (MACRO_STOCKS)
        ("stocks", "MACRO_STOCKS", 35, 0.5, 0.40),
        ("wallstreetbets", "MACRO_STOCKS", 60, 0.8, 0.45),
        ("investing", "MACRO_STOCKS", 35, 0.45, 0.35),
        ("options", "MACRO_STOCKS", 25, 0.35, 0.40),
        ("ValueInvesting", "MACRO_STOCKS", 25, 0.3, 0.35),
        ("algotrading", "MACRO_STOCKS", 20, 0.25, 0.35),

        # 3. 能源大宗、石油、黄金与清洁核电 (COMMODITIES_ENERGY)
        ("commodities", "COMMODITIES_ENERGY", 30, 0.35, 0.35),
        ("Gold", "COMMODITIES_ENERGY", 30, 0.35, 0.35),
        ("energy", "COMMODITIES_ENERGY", 30, 0.35, 0.35),
        ("UraniumSqueeze", "COMMODITIES_ENERGY", 35, 0.45, 0.40),

        # 4. 加密资本与链上量化流动性 (CRYPTO_ALPHA)
        ("BitcoinMarkets", "CRYPTO_ALPHA", 40, 0.45, 0.35),
        ("ethfinance", "CRYPTO_ALPHA", 30, 0.35, 0.35),
        ("defi", "CRYPTO_ALPHA", 25, 0.30, 0.35),
    ]
    c.executemany(
        "INSERT OR IGNORE INTO watch_sources (subreddit, category, min_score, min_velocity, min_controversy) VALUES (?, ?, ?, ?, ?)",
        default_sources
    )

    # 预置默认「AI × 能源 × 宏观资本商业化人设」（直击 X 爆款变现）
    c.execute("SELECT COUNT(*) FROM personas")
    if c.fetchone()[0] == 0:
        cross_domain_persona = (
            "You are a Silicon Valley AI Systems Architect & Quantitative Tech Investor on X. "
            "You bridge the gap between deep engineering reality, commodity energy constraints, and capital market pricing:\n"
            "- When analyzing AI & Open Source: focus on real production bottlenecks, VRAM/compute unit economics, inference latency tradeoffs, open-weight vs closed-source moats, and how this impacts Big Tech ($NVDA, $MSFT, $GOOGL, $META) margins.\n"
            "- When analyzing US Equities & Macro: apply an engineer's first-principles data mindset to dissect earnings quality, institutional 13F positioning, asymmetric risk/reward, and retail crowd psychology.\n"
            "- When analyzing Energy, Oil & Gold: connect the global energy bottleneck (grid capacity, WTI crude, nuclear SMRs) directly to data center buildouts, and evaluate gold/fiat debasement against tech valuations.\n"
            "- When analyzing Crypto/Web3: focus purely on real protocol cash flow, on-chain liquidity depth, and decentralized compute unit economics, discarding meme slop."
        )
        banned = "delve,tapestry,testament,game-changer,revolutionize,in conclusion,let's dive in,buckle up,realm,beacon,🚀,🧵"
        c.execute(
            "INSERT INTO personas (name, handle, system_prompt, banned_words, is_default) VALUES (?, ?, ?, ?, 1)",
            ("AI × Capital Alpha (商业主号)", settings.X_HANDLE, cross_domain_persona, banned)
        )

    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, str]:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def save_raw_signal_only(signal: Dict[str, Any]):
    """仅存入原始情报池，不调用 AI 二创（省 Token / 手动精选模式）"""
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
        json.dumps(signal.get("top_comments", []), ensure_ascii=False)
    ))
    # 创建待二创占位记录
    c.execute("""
        INSERT OR IGNORE INTO drafts
        (post_id, persona_id, status, worth_posting, skip_reason, narrative_framework, content_tier, hooks_json, short_post, long_post, sniper_reply, x_search_query, card_json, hashtags_json, thread_json)
        VALUES (?, 1, 'raw_unprocessed', 1, '', 'Pending AI Synthesis', 'DEEP_DIVE_MEMO', '[]', '', '', '', '', '{}', '[]', '[]')
    """, (signal["post_id"],))
    conn.commit()
    conn.close()


def get_raw_signal(post_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM raw_signals WHERE post_id = ?", (post_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["top_comments"] = json.loads(d["top_comments_json"]) if d["top_comments_json"] else []
    except Exception:
        d["top_comments"] = []
    return d


def get_processed_signal_ids() -> set:
    """批量获取已入库的情报 ID 集合，用于采集器快速去重（避免 N+1 频繁连接数据库）"""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT post_id FROM raw_signals").fetchall()
        conn.close()
        return {r["post_id"] for r in rows}
    except Exception:
        conn.close()
        return set()


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
        json.dumps(signal.get("top_comments", []), ensure_ascii=False)
    ))

    c.execute("""
        INSERT OR REPLACE INTO drafts
        (post_id, persona_id, status, worth_posting, skip_reason, narrative_framework, content_tier, hooks_json, short_post, long_post, sniper_reply, x_search_query, card_json, hashtags_json, thread_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        signal["post_id"],
        persona_id,
        "pending" if draft_data.get("is_worth_posting", True) else "archived",
        1 if draft_data.get("is_worth_posting", True) else 0,
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
        }, ensure_ascii=False),
        json.dumps(draft_data.get("hashtags", []), ensure_ascii=False),
        json.dumps(draft_data.get("thread_posts", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()
