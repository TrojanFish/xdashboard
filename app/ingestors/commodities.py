import hashlib
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import get_processed_signal_ids


class CommoditiesEnergyIngestor:
    """能源大宗、原油与黄金一手情报采集器 (基于全球权威 OilPrice & Commodities 官方 RSS，海外 VPS 零拦截)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/xml, text/xml, */*"
        })

    def fetch_top_signals(self, max_signals: int = 3) -> List[Dict[str, Any]]:
        processed_ids = get_processed_signal_ids()
        signals = []

        rss_urls = [
            ("https://oilprice.com/rss/main", "Oil & Energy"),
            ("https://oilprice.com/rss/category/commodities", "Metals & Commodities")
        ]

        for url, channel_name in rss_urls:
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code != 200:
                    continue

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

                    # 唯一 ID
                    h = hashlib.md5(link.encode()).hexdigest()[:10]
                    post_id = f"cmd_{h}"
                    if post_id in processed_ids:
                        continue

                    # 判断所属资产类型
                    title_lower = title.lower()
                    flair = "CRUDE_OIL"
                    if any(w in title_lower for w in ["gold", "silver", "precious"]):
                        flair = "GOLD_METALS"
                    elif any(w in title_lower for w in ["uranium", "nuclear", "smr"]):
                        flair = "NUCLEAR_ENERGY"
                    elif any(w in title_lower for w in ["gas", "lng"]):
                        flair = "NATURAL_GAS"

                    signals.append({
                        "post_id": post_id,
                        "subreddit": "oilprice",
                        "category": "COMMODITIES_ENERGY",
                        "title": f"[{flair}] {title}",
                        "selftext": (
                            f"Channel: {channel_name}\n"
                            f"Published: {pub_date}\n"
                            f"Source URL: {link}\n\n"
                            f"Macro & Supply-Demand Briefing:\n{desc}\n\n"
                            f"Evaluate impact on inflation/CPI expectations, Federal Reserve discount rates, and tech datacenter power economics."
                        ),
                        "permalink": link,
                        "flair": flair,
                        "score": 85,
                        "num_comments": 0,
                        "velocity": 1.2,
                        "controversy": 0.35,
                        "top_comments": [
                            f"🛢️ Official Energy & Commodities Intelligence ({channel_name})",
                            f"Primary Asset: {flair}",
                            f"Source URL: {link}"
                        ]
                    })
                    if len(signals) >= max_signals:
                        break
            except Exception as e:
                print(f"   [Commodities/OilPrice 采集异常] {url}: {e}")

            if len(signals) >= max_signals:
                break

        return signals[:max_signals]
