import hashlib
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import get_processed_signal_ids


class MacroStocksIngestor:
    """美股异动与华尔街宏观情报采集器 (基于道琼斯 / MarketWatch MarketPulse 官方开放源)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/xml, text/xml, */*"
        })

    def fetch_top_signals(self, max_signals: int = 3) -> List[Dict[str, Any]]:
        processed_ids = get_processed_signal_ids()
        signals = []

        url = "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")

                for it in items:
                    title_elem = it.find("title")
                    link_elem = it.find("link")
                    desc_elem = it.find("description")
                    pub_elem = it.find("pubDate")

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    raw_desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
                    desc = re.sub(r"<[^>]+>", "", raw_desc).strip()
                    pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                    if not title or not link:
                        continue

                    # 过滤个人琐事问答，聚焦核心市场与宏观异动
                    title_lower = title.lower()
                    if any(w in title_lower for w in ["father-in-law", "stepmother", "my wife", "my husband", "inheritance"]):
                        continue

                    h = hashlib.md5(link.encode()).hexdigest()[:10]
                    post_id = f"mw_{h}"
                    if post_id in processed_ids:
                        continue

                    flair = "MARKET_PULSE"
                    if any(w in title_lower for w in ["fed", "rate", "inflation", "cpi", "jobs", "yield"]):
                        flair = "MACRO_FED"
                    elif any(w in title_lower for w in ["earnings", "revenue", "profit", "guidance"]):
                        flair = "EARNINGS_ALPHA"
                    elif any(w in title_lower for w in ["tech", "ai", "nvidia", "apple", "microsoft", "tesla"]):
                        flair = "BIG_TECH"

                    signals.append({
                        "post_id": post_id,
                        "subreddit": "marketwatch",
                        "category": "MACRO_STOCKS",
                        "title": f"[{flair}] {title}",
                        "selftext": (
                            f"Wall Street Market Pulse (Dow Jones):\n"
                            f"Published: {pub_date}\n"
                            f"Source URL: {link}\n\n"
                            f"Report Briefing:\n{desc}\n\n"
                            f"Evaluate institutional positioning, 13F implications, options skew, and asymmetry."
                        ),
                        "permalink": link,
                        "flair": flair,
                        "score": 90,
                        "num_comments": 0,
                        "velocity": 1.5,
                        "controversy": 0.40,
                        "top_comments": [
                            f"📈 Dow Jones MarketWatch MarketPulse",
                            f"Category: {flair}",
                            f"Source URL: {link}"
                        ]
                    })
                    if len(signals) >= max_signals:
                        break
        except Exception as e:
            print(f"   [MacroStocks/MarketWatch 采集异常]: {e}")

        return signals[:max_signals]
