import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests
from app.config import settings
from app.database import get_conn, is_signal_processed


class RedditIngestor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.USER_AGENT})
        if settings.REDDIT_PROXY_URL:
            self.session.proxies = {
                "http": settings.REDDIT_PROXY_URL,
                "https": settings.REDDIT_PROXY_URL,
            }
        self.oauth_token: Optional[str] = None
        self.token_expiry: float = 0

    def _ensure_oauth(self):
        """如果配置了官方免费 Script Key，自动获取 Token 绕过海外 VPS 机房 IP 封锁"""
        if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
            return
        now = time.time()
        if self.oauth_token and now < self.token_expiry:
            return
        try:
            auth = requests.auth.HTTPBasicAuth(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET)
            data = {"grant_type": "client_credentials"}
            resp = self.session.post("https://www.reddit.com/api/v1/access_token", auth=auth, data=data, timeout=10)
            if resp.status_code == 200:
                token_data = resp.json()
                self.oauth_token = token_data["access_token"]
                self.token_expiry = now + token_data.get("expires_in", 3600) - 60
                self.session.headers.update({"Authorization": f"bearer {self.oauth_token}"})
        except Exception as e:
            print(f"[Reddit OAuth 告警] 获取 Token 失败，降级为公开接口: {e}")

    def _build_url(self, path: str) -> str:
        self._ensure_oauth()
        domain = "https://oauth.reddit.com" if self.oauth_token else "https://www.reddit.com"
        return f"{domain}{path}"

    def fetch_qualified_signals(self, max_signals: int = 5) -> List[Dict[str, Any]]:
        conn = get_conn()
        sources = conn.execute("SELECT * FROM watch_sources WHERE enabled = 1").fetchall()
        conn.close()

        candidates = []
        now_ts = datetime.now(timezone.utc).timestamp()

        for src in sources:
            sub = src["subreddit"]
            for feed in ["rising", "hot"]:
                url = self._build_url(f"/r/{sub}/{feed}.json?limit=25&raw_json=1")
                try:
                    resp = self.session.get(url, timeout=12)
                    if resp.status_code != 200:
                        print(f"[采集跳过] r/{sub}/{feed} HTTP {resp.status_code}")
                        continue

                    children = resp.json().get("data", {}).get("children", [])
                    for item in children:
                        p = item.get("data", {})
                        post_id = p.get("id")
                        if not post_id or p.get("stickied") or is_signal_processed(post_id):
                            continue

                        score = p.get("score", 0)
                        num_comments = p.get("num_comments", 0)
                        created_utc = p.get("created_utc", now_ts)
                        age_minutes = max((now_ts - created_utc) / 60.0, 1.0)

                        if age_minutes > 1080 or score < src["min_score"]:
                            continue

                        velocity = round(score / age_minutes, 2)
                        controversy = round(num_comments / max(score, 1), 2)
                        selftext = p.get("selftext", "")
                        is_deep_dd = len(selftext.split()) > 280 and score >= src["min_score"] * 1.3

                        if velocity >= src["min_velocity"] or controversy >= src["min_controversy"] or is_deep_dd:
                            candidates.append({
                                "post_id": post_id,
                                "subreddit": sub,
                                "category": src["category"],
                                "title": p.get("title", ""),
                                "selftext": selftext[:4500],
                                "permalink": f"https://www.reddit.com{p.get('permalink')}",
                                "raw_permalink": p.get("permalink"),
                                "flair": p.get("link_flair_text") or "Discussion",
                                "score": score,
                                "num_comments": num_comments,
                                "velocity": velocity,
                                "controversy": controversy,
                            })
                    time.sleep(1.2)
                except Exception as e:
                    print(f"[采集异常] r/{sub}: {e}")

        unique_map = {c["post_id"]: c for c in candidates}
        sorted_list = sorted(unique_map.values(), key=lambda x: (x["velocity"] * 2 + x["controversy"]), reverse=True)
        top_signals = sorted_list[:max_signals]

        for sig in top_signals:
            sig["top_comments"] = self.fetch_top_comments(sig["raw_permalink"])
            time.sleep(1.0)

        return top_signals

    def fetch_top_comments(self, raw_permalink: str, limit: int = 14) -> List[str]:
        url = self._build_url(f"{raw_permalink.rstrip('/')}.json?sort=top&limit=25&raw_json=1")
        comments = []
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code != 200:
                return []
            data = resp.json()
            if len(data) < 2:
                return []
            for c in data[1].get("data", {}).get("children", []):
                if c.get("kind") != "t1":
                    continue
                cd = c.get("data", {})
                body = cd.get("body", "")
                author = cd.get("author", "")
                if author == "AutoModerator" or body in ["[deleted]", "[removed]"] or len(body) < 35:
                    continue
                comments.append(f"[+{cd.get('score', 0)} upvotes] {body[:550]}")
                if len(comments) >= limit:
                    break
        except Exception as e:
            print(f"[评论拉取异常]: {e}")
        return comments
