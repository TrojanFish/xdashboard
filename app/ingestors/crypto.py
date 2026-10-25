from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import get_processed_signal_ids


class CryptoTrendingIngestor:
    """加密资本与链上流动性一手情报采集器 (基于 CoinGecko 官方开放 Trending API，海外 VPS 零拦截)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"
        })

    def fetch_top_signals(self, max_signals: int = 2) -> List[Dict[str, Any]]:
        processed_ids = get_processed_signal_ids()
        signals = []

        url = "https://api.coingecko.com/api/v3/search/trending"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                coins = data.get("coins", [])

                for c in coins:
                    item = c.get("item", {})
                    coin_id = item.get("id", "")
                    symbol = item.get("symbol", "").upper()
                    name = item.get("name", "")
                    rank = item.get("market_cap_rank") or 999
                    score = item.get("score", 0)

                    if not coin_id or not symbol:
                        continue

                    post_id = f"cg_{coin_id}"
                    if post_id in processed_ids:
                        continue

                    data_details = item.get("data", {})
                    price = data_details.get("price", "N/A")
                    price_change_24h = data_details.get("price_change_percentage_24h", {}).get("usd", 0.0)

                    signals.append({
                        "post_id": post_id,
                        "subreddit": "coingecko",
                        "category": "CRYPTO_ALPHA",
                        "title": f"[Trending ${symbol}] {name} (Rank #{rank}): {price_change_24h:+.1f}% (24h)",
                        "selftext": (
                            f"Asset: {name} (${symbol})\n"
                            f"Market Cap Rank: #{rank}\n"
                            f"Current Price: {price}\n"
                            f"24h Price Change: {price_change_24h:+.2f}%\n"
                            f"CoinGecko Trending Rank: #{score + 1}\n\n"
                            f"Overview & Tokenomics: Trending on CoinGecko search volume. "
                            f"Evaluate protocol cash flow, real TVL liquidity backing, token unlock schedule, and speculative vs organic demand."
                        ),
                        "permalink": f"https://www.coingecko.com/en/coins/{coin_id}",
                        "flair": f"${symbol}",
                        "score": 100 - score,
                        "num_comments": 0,
                        "velocity": round(abs(price_change_24h) / 24.0, 2),
                        "controversy": 0.45,
                        "top_comments": [
                            f"🪙 CoinGecko Global Trending Search #{score + 1}",
                            f"Symbol: ${symbol} | Rank #{rank}",
                            f"24h Price Momentum: {price_change_24h:+.1f}%"
                        ]
                    })
                    if len(signals) >= max_signals:
                        break
        except Exception as e:
            print(f"   [Crypto/CoinGecko 采集异常]: {e}")

        return signals[:max_signals]
