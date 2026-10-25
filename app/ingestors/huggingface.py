import time
from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import get_processed_signal_ids


class HuggingFaceIngestor:
    """Hugging Face 开源模型与前沿学术论文采集器 (官方开放 REST API，海外 VPS 零拦截)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"
        })

    def fetch_trending_signals(self, max_signals: int = 3) -> List[Dict[str, Any]]:
        processed_ids = get_processed_signal_ids()
        signals = []

        # 1. 抓取过去 7 天点赞激增的开源权重 (Trending Models)
        try:
            url = "https://huggingface.co/api/models?sort=likes7d&direction=-1&limit=15"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                models = resp.json()
                for m in models:
                    model_id = m.get("id", "")
                    if not model_id:
                        continue
                    post_id = f"hf_m_{model_id.replace('/', '_')}"
                    if post_id in processed_ids:
                        continue

                    likes = m.get("likes", 0)
                    pipeline = m.get("pipeline_tag") or "llm-weights"
                    tags = m.get("tags", [])[:5]

                    # 过滤低点赞的冷门模型
                    if likes < 40:
                        continue

                    signals.append({
                        "post_id": post_id,
                        "subreddit": "huggingface",
                        "category": "AI_DEV",
                        "title": f"[HF Trending] {model_id} ({pipeline}): +{likes} likes this week",
                        "selftext": (
                            f"Model Checkpoint: https://huggingface.co/{model_id}\n"
                            f"Architecture/Pipeline: {pipeline}\n"
                            f"Weekly Likes: {likes}\n"
                            f"Key Tags: {', '.join(tags)}\n"
                            f"Summary: New trending open-weight checkpoint on Hugging Face ecosystem. "
                            f"Evaluate parameter efficiency, inference compute economics, and VRAM requirements."
                        ),
                        "permalink": f"https://huggingface.co/{model_id}",
                        "flair": pipeline.upper(),
                        "score": likes,
                        "num_comments": 0,
                        "velocity": round(likes / 7.0, 2),
                        "controversy": 0.25,
                        "top_comments": [
                            f"🔥 +{likes} likes on Hugging Face Trending",
                            f"Pipeline: {pipeline}",
                            f"Direct Link: https://huggingface.co/{model_id}"
                        ]
                    })
                    if len(signals) >= max_signals:
                        break
        except Exception as e:
            print(f"   [HuggingFace Models 采集异常]: {e}")

        # 2. 如果模型不够，补充今日精选学术突破论文 (Daily Papers)
        if len(signals) < max_signals:
            try:
                url_papers = "https://huggingface.co/api/daily_papers"
                resp_p = self.session.get(url_papers, timeout=10)
                if resp_p.status_code == 200:
                    papers = resp_p.json()
                    for p_item in papers:
                        paper = p_item.get("paper", {})
                        p_id = paper.get("id") or str(int(time.time()))
                        post_id = f"hf_p_{p_id}"
                        if post_id in processed_ids:
                            continue

                        title = paper.get("title", "")
                        summary = paper.get("summary", "")
                        upvotes = paper.get("upvotes", 0)

                        signals.append({
                            "post_id": post_id,
                            "subreddit": "huggingface",
                            "category": "AI_DEV",
                            "title": f"[HF Paper] {title}",
                            "selftext": (
                                f"Academic Paper: https://huggingface.co/papers/{p_id}\n"
                                f"Upvotes: {upvotes}\n"
                                f"Abstract & Breakthrough:\n{summary[:1500]}"
                            ),
                            "permalink": f"https://huggingface.co/papers/{p_id}",
                            "flair": "RESEARCH_PAPER",
                            "score": upvotes or 25,
                            "num_comments": 0,
                            "velocity": round(float(upvotes or 10) / 2.0, 2),
                            "controversy": 0.2,
                            "top_comments": [
                                f"📄 Hugging Face Daily Curated Paper (+{upvotes} upvotes)",
                                f"Paper URL: https://huggingface.co/papers/{p_id}"
                            ]
                        })
                        if len(signals) >= max_signals:
                            break
            except Exception as e:
                print(f"   [HuggingFace Papers 采集异常]: {e}")

        return signals[:max_signals]
