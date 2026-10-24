import re
import time
from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import is_signal_processed


class GitHubTrendingIngestor:
    """采集 GitHub Trending 每日热榜，并自动抓取 README 提炼工程亮点"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _fetch_readme(self, repo: str) -> str:
        """从 raw.githubusercontent.com 极速拉取 README 前 4000 字符"""
        for branch in ["main", "master"]:
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/README.md"
            try:
                resp = self.session.get(url, timeout=6)
                if resp.status_code == 200 and len(resp.text) > 50:
                    # 过滤纯 HTML 标签和大段图片链接，保留高价值正文
                    clean = re.sub(r'<picture>.*?</picture>', '', resp.text, flags=re.DOTALL)
                    clean = re.sub(r'<[^>]+>', ' ', clean)
                    clean = re.sub(r'!\[.*?\]\(.*?\)', '', clean)
                    return clean[:3500].strip()
            except Exception:
                continue
        return ""

    def fetch_trending_signals(self, languages: List[str] = None, max_signals: int = 5) -> List[Dict[str, Any]]:
        """抓取今日 Trending 项目（支持全局热榜及指定编程语言热榜）"""
        if languages is None:
            languages = ["", "python", "rust", "typescript"]

        candidates = []
        seen_repos = set()

        for lang in languages:
            url = f"https://github.com/trending/{lang}?since=daily" if lang else "https://github.com/trending?since=daily"
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code != 200:
                    print(f"[GitHub 采集跳过] {url} HTTP {resp.status_code}")
                    continue

                articles = re.findall(r'<article class="Box-row"[^>]*>(.*?)</article>', resp.text, re.DOTALL)
                for art in articles:
                    # 提取仓库名 /owner/repo
                    m_repo = re.search(r'href="/([^/]+/[^/\s"]+)"', art)
                    if not m_repo:
                        continue
                    repo = m_repo.group(1).strip()
                    if repo in seen_repos:
                        continue

                    post_id = f"gh_{repo.replace('/', '_')}"
                    if is_signal_processed(post_id):
                        continue

                    # 提取简介
                    m_desc = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', art, re.DOTALL)
                    desc = re.sub(r'<[^>]+>', '', m_desc.group(1)).strip() if m_desc else ""

                    # 提取主要编程语言
                    m_lang = re.search(r'itemprop="programmingLanguage">(.*?)</span>', art)
                    prog_lang = m_lang.group(1).strip() if m_lang else (lang.capitalize() if lang else "OpenSource")

                    # 提取今日新增 Star
                    m_today = re.search(r'([\d,]+)\s+stars today', art)
                    stars_today_str = m_today.group(1).replace(',', '') if m_today else "0"
                    stars_today = int(stars_today_str) if stars_today_str.isdigit() else 0

                    # 过滤 Star 增速过低的平庸项目（每日至少 80+ stars）
                    if stars_today < 60:
                        continue

                    seen_repos.add(repo)
                    candidates.append({
                        "post_id": post_id,
                        "repo": repo,
                        "desc": desc,
                        "prog_lang": prog_lang,
                        "stars_today": stars_today,
                        "permalink": f"https://github.com/{repo}",
                    })
                time.sleep(1.0)
            except Exception as e:
                print(f"[GitHub 采集异常] {url}: {e}")

        # 按今日新增 Star 排序，精选前 max_signals 个抓取 README
        candidates.sort(key=lambda x: x["stars_today"], reverse=True)
        selected = candidates[:max_signals]

        results = []
        for item in selected:
            repo = item["repo"]
            readme = self._fetch_readme(repo)
            time.sleep(0.5)

            results.append({
                "post_id": item["post_id"],
                "subreddit": f"github/{item['prog_lang'].lower()}",
                "category": "GITHUB_TRENDING",
                "title": f"[{item['prog_lang']}] {repo}: {item['desc']}",
                "selftext": f"Repository: https://github.com/{repo}\nLanguage: {item['prog_lang']}\nStars Today: +{item['stars_today']}\nDescription: {item['desc']}\n\n### README EXCERPT:\n{readme}",
                "permalink": item["permalink"],
                "flair": item["prog_lang"],
                "score": item["stars_today"],
                "num_comments": 0,
                "velocity": round(item["stars_today"] / 24.0, 2), # 每小时 Star 增速
                "controversy": 0.1,
                "top_comments": [
                    f"⭐ +{item['stars_today']} stars today on GitHub Trending",
                    f"Tech Stack: {item['prog_lang']}",
                    f"Official Repo: https://github.com/{repo}"
                ]
            })

        return results
