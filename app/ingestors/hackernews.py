import html
import re
import time
from datetime import datetime, timezone
from typing import List, Dict, Any
import requests
from app.database import is_signal_processed

# 赛道关键词特征匹配库
AI_DEV_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "deepseek", "model", "models", "gpu", "cuda",
    "vram", "inference", "benchmark", "agent", "agents", "compiler", "rust", "python",
    "linux", "kernel", "database", "postgres", "sqlite", "server", "architecture",
    "open-source", "framework", "prompt", "fine-tuning", "rag", "transformer", "neural",
    "huggingface", "kimi", "anthropic", "openai", "nvidia", "meta", "algorithm"
}

FINANCE_KEYWORDS = {
    "stock", "stocks", "market", "markets", "capital", "fund", "venture", "vc",
    "valuation", "ipo", "sec", "inflation", "tariff", "tariffs", "fed", "interest",
    "rate", "revenue", "margin", "margins", "earnings", "profit", "crypto", "bitcoin",
    "ethereum", "dollar", "treasury", "macro", "trade", "trading", "hedge"
}


class HackerNewsIngestor:
    """
    Hacker News (Y Combinator) 官方 Firebase REST API 采集器
    无需任何 API Key，官方永久免费开放，海外 VPS 机房 IP 绝无 403 阻断！
    汇聚硅谷顶尖架构师、量化交易员与 AI 一线从业者的高信噪比深度争议。
    """
    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        })

    def _clean_html(self, text: str) -> str:
        """剥离 HN 评论中的 HTML 标签并还原转义字符"""
        if not text:
            return ""
        # 换行标签替换为空格换行
        clean = re.sub(r"<p>", "\n", text)
        clean = re.sub(r"<[^<]+?>", "", clean)
        clean = html.unescape(clean).strip()
        return clean

    def _classify_category(self, title: str, text: str) -> str:
        """根据标题与内容自动归类为 AI_DEV 或 FINANCE"""
        combined = f"{title.lower()} {text.lower()}"
        tokens = set(re.findall(r"\b[a-zA-Z-]{2,}\b", combined))

        ai_matches = len(tokens.intersection(AI_DEV_KEYWORDS))
        fin_matches = len(tokens.intersection(FINANCE_KEYWORDS))

        if fin_matches > ai_matches:
            return "FINANCE"
        return "AI_DEV"

    def fetch_top_signals(self, max_signals: int = 4) -> List[Dict[str, Any]]:
        print("   [Hacker News] 正在从 YC Hacker News 获取全球热门深度技术与宏观讨论...")
        candidates = []
        now_ts = datetime.now(timezone.utc).timestamp()

        try:
            # 抓取 Top Stories 前 40 个 ID
            resp = self.session.get(f"{self.BASE_URL}/topstories.json", timeout=10)
            if resp.status_code != 200:
                print(f"   ❌ [Hacker News] 获取 Top 列表失败: HTTP {resp.status_code}")
                return []
            
            story_ids = resp.json()[:40]
            for s_id in story_ids:
                post_id = f"hn_{s_id}"
                if is_signal_processed(post_id):
                    continue

                try:
                    item_resp = self.session.get(f"{self.BASE_URL}/item/{s_id}.json", timeout=6)
                    if item_resp.status_code != 200:
                        continue
                    item = item_resp.json() or {}

                    score = item.get("score", 0)
                    num_comments = item.get("descendants", 0)
                    title = item.get("title", "")
                    created_time = item.get("time", now_ts)
                    age_minutes = max((now_ts - created_time) / 60.0, 1.0)

                    # 基础信噪比初筛：点赞 >= 40 且 评论数 >= 10
                    if score < 40 or num_comments < 10 or age_minutes > 1440:
                        continue

                    velocity = round(score / age_minutes, 2)
                    controversy = round(num_comments / max(score, 1), 2)
                    raw_text = self._clean_html(item.get("text", ""))
                    story_url = item.get("url", "")
                    selftext = raw_text or f"Original URL: {story_url}"

                    category = self._classify_category(title, selftext)

                    candidates.append({
                        "post_id": post_id,
                        "subreddit": "hackernews",
                        "category": category,
                        "title": title,
                        "selftext": selftext[:4500],
                        "permalink": f"https://news.ycombinator.com/item?id={s_id}",
                        "raw_permalink": str(s_id),
                        "flair": "HN Discussion",
                        "score": score,
                        "num_comments": num_comments,
                        "velocity": velocity,
                        "controversy": controversy,
                        "kids": item.get("kids", []),
                    })

                    if len(candidates) >= max_signals * 2:
                        break
                except Exception:
                    continue

        except Exception as e:
            print(f"   ❌ [Hacker News] 采集异常: {e}")
            return []

        # 按热度与争议度综合排序
        sorted_candidates = sorted(candidates, key=lambda x: (x["velocity"] * 1.5 + x["controversy"]), reverse=True)
        selected_signals = sorted_candidates[:max_signals]

        # 抓取第一手高赞评论
        for sig in selected_signals:
            sig["top_comments"] = self.fetch_top_comments(sig.pop("kids", []))

        print(f"   [Hacker News] 成功筛选出 {len(selected_signals)} 条高信噪比技术与资本议题。")
        return selected_signals

    def fetch_top_comments(self, kid_ids: List[int], limit: int = 8) -> List[str]:
        comments = []
        if not kid_ids:
            return comments

        for k_id in kid_ids[:limit * 2]:
            try:
                c_resp = self.session.get(f"{self.BASE_URL}/item/{k_id}.json", timeout=5)
                if c_resp.status_code != 200:
                    continue
                c_data = c_resp.json() or {}
                if c_data.get("deleted") or c_data.get("dead"):
                    continue

                body = self._clean_html(c_data.get("text", ""))
                by = c_data.get("by", "engineer")
                if len(body) >= 30:
                    comments.append(f"[@{by} 推演] {body[:550]}")
                if len(comments) >= limit:
                    break
            except Exception:
                continue
        return comments
