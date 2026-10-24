import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests
from app.config import settings
from app.database import get_conn, is_signal_processed


class RedditIngestor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT,
            "Accept": "application/json"
        })
        if settings.REDDIT_COOKIE:
            self.session.headers.update({"Cookie": settings.REDDIT_COOKIE.strip()})
        if settings.REDDIT_PROXY_URL:
            self.session.proxies = {
                "http": settings.REDDIT_PROXY_URL,
                "https": settings.REDDIT_PROXY_URL,
            }
        self.oauth_token: Optional[str] = None
        self.token_expiry: float = 0

    def _ensure_oauth(self):
        """如果配置了官方免费 Script Key，自动获取 Token 绕过海外 VPS 机房 IP 403 封锁"""
        if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
            return
        now = time.time()
        if self.oauth_token and now < self.token_expiry:
            return
        try:
            auth = requests.auth.HTTPBasicAuth(settings.REDDIT_CLIENT_ID.strip(), settings.REDDIT_CLIENT_SECRET.strip())
            data = {"grant_type": "client_credentials"}
            headers = {"User-Agent": settings.USER_AGENT}
            resp = self.session.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data=data,
                headers=headers,
                timeout=12
            )
            if resp.status_code == 200:
                token_data = resp.json()
                self.oauth_token = token_data.get("access_token")
                self.token_expiry = now + token_data.get("expires_in", 3600) - 60
                self.session.headers.update({"Authorization": f"Bearer {self.oauth_token}"})
                print("   🔑 [Reddit OAuth] 官方 API Token 获取成功，已启用绿色通道！")
            else:
                print(f"   ⚠️ [Reddit OAuth] 获取 Token 失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"   ⚠️ [Reddit OAuth 告警] 获取 Token 异常: {e}")

    def _build_url(self, path: str) -> str:
        self._ensure_oauth()
        if self.oauth_token:
            # 在 oauth.reddit.com 上，标准 listing 既支持干净路径也支持 .json
            return f"https://oauth.reddit.com{path}"
        return f"https://www.reddit.com{path}"

    def fetch_qualified_signals(self, max_signals: int = 5) -> List[Dict[str, Any]]:
        conn = get_conn()
        sources = conn.execute("SELECT * FROM watch_sources WHERE enabled = 1").fetchall()
        conn.close()

        candidates = []
        now_ts = datetime.now(timezone.utc).timestamp()
        consecutive_403 = 0

        for src in sources:
            if consecutive_403 >= 3:
                print("   [Reddit] 检测到连续 403 阻断（海外 VPS 机房 IP 被 Reddit 拦截）。")
                if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
                    print("   💡 解决方式：只需在 https://www.reddit.com/prefs/apps 免费创建 Script 应用，在 .env 中填入 REDDIT_CLIENT_ID 与 SECRET 即可彻底解除阻断！")
                break

            sub = src["subreddit"]
            for feed in ["rising", "hot"]:
                url = self._build_url(f"/r/{sub}/{feed}.json?limit=25&raw_json=1")
                try:
                    resp = self.session.get(url, timeout=10)
                    if resp.status_code == 401 and self.oauth_token:
                        # Token 可能意外失效，重置重试一次
                        self.oauth_token = None
                        self._ensure_oauth()
                        resp = self.session.get(url, timeout=10)

                    if resp.status_code == 403:
                        consecutive_403 += 1
                        print(f"   [采集跳过] r/{sub}/{feed} HTTP 403 (海外 VPS 机房 IP 阻断，需配置 REDDIT_CLIENT_ID 或代理)")
                        break # 跳过该 sub 的后续 feed，进入下一个
                    if resp.status_code != 200:
                        print(f"   [采集跳过] r/{sub}/{feed} HTTP {resp.status_code}")
                        continue

                    consecutive_403 = 0
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
                    time.sleep(1.0)
                except Exception as e:
                    print(f"   [采集异常] r/{sub}: {e}")

        unique_map = {c["post_id"]: c for c in candidates}
        sorted_list = sorted(unique_map.values(), key=lambda x: (x["velocity"] * 2 + x["controversy"]), reverse=True)
        top_signals = sorted_list[:max_signals]

        for sig in top_signals:
            sig["top_comments"] = self.fetch_top_comments(sig["raw_permalink"])
            time.sleep(1.0)

        return top_signals

    def fetch_top_comments(self, raw_permalink: str, limit: int = 14) -> List[str]:
        clean_path = raw_permalink.rstrip('/')
        url = self._build_url(f"{clean_path}.json?sort=top&limit=25&raw_json=1")
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
            print(f"   [评论拉取异常]: {e}")
        return comments
