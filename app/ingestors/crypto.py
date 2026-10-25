import re
import time
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

    def _fetch_coin_detail(self, coin_id: str) -> Dict[str, Any]:
        """调用 /coins/{id} 补全代币详情：描述、ATH、FDV、TVL、市值等分析语料"""
        try:
            url = (
                f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                "?localization=false&tickers=false&community_data=false&developer_data=false"
            )
            resp = self.session.get(url, timeout=8)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            market = data.get("market_data", {})

            # Strip HTML from description
            desc_raw = data.get("description", {}).get("en", "")
            desc_clean = re.sub(r"<[^>]+>", "", desc_raw).strip()[:600]

            def fmt(v):
                if v is None:
                    return "N/A"
                if v >= 1_000_000_000:
                    return f"${v / 1e9:.2f}B"
                if v >= 1_000_000:
                    return f"${v / 1e6:.1f}M"
                return f"${v:,.0f}"

            tvl_raw = market.get("total_value_locked")
            tvl_usd = tvl_raw.get("usd") if isinstance(tvl_raw, dict) else None

            return {
                "description": desc_clean,
                "ath_usd":     fmt(market.get("ath", {}).get("usd")),
                "fdv":         fmt(market.get("fully_diluted_valuation", {}).get("usd")),
                "mcap":        fmt(market.get("market_cap", {}).get("usd")),
                "tvl":         fmt(tvl_usd) if tvl_usd else "N/A",
                "vol_24h":     fmt(market.get("total_volume", {}).get("usd")),
                "circ_supply": f"{market.get('circulating_supply', 0):,.0f}" if market.get("circulating_supply") else "N/A",
                "total_supply": f"{market.get('total_supply', 0):,.0f}" if market.get("total_supply") else "N/A",
                "categories":  ", ".join(data.get("categories", [])[:3]),
            }
        except Exception as e:
            print(f"   [CoinGecko Detail 采集异常] {coin_id}: {e}")
            return {}

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
                    if len(signals) >= max_signals:
                        break

                    item = c.get("item", {})
                    coin_id = item.get("id", "")
                    symbol  = item.get("symbol", "").upper()
                    name    = item.get("name", "")
                    rank    = item.get("market_cap_rank") or 999
                    score   = item.get("score", 0)

                    if not coin_id or not symbol:
                        continue

                    post_id = f"cg_{coin_id}"
                    if post_id in processed_ids:
                        continue

                    data_details   = item.get("data", {})
                    price          = data_details.get("price", "N/A")
                    price_chg_24h  = data_details.get("price_change_percentage_24h", {}).get("usd", 0.0)

                    # Enrich with detailed coin data (respect free-tier rate limit)
                    detail = self._fetch_coin_detail(coin_id)
                    time.sleep(1.2)

                    lines = [
                        f"Asset: {name} (${symbol})",
                        f"Market Cap Rank: #{rank}",
                        f"Current Price: {price}",
                        f"24h Price Change: {price_chg_24h:+.2f}%",
                        f"CoinGecko Trending Rank: #{score + 1}",
                        "",
                    ]
                    if detail:
                        lines += [
                            f"Market Cap: {detail['mcap']}",
                            f"Fully Diluted Valuation (FDV): {detail['fdv']}",
                            f"24h Volume: {detail['vol_24h']}",
                            f"All-Time High: {detail['ath_usd']}",
                            f"TVL (DeFi): {detail['tvl']}",
                            f"Supply: {detail['circ_supply']} circulating / {detail['total_supply']} total",
                            f"Categories: {detail['categories']}",
                            "",
                            "Protocol Description:",
                            detail["description"] or "No description available.",
                            "",
                        ]
                    lines.append(
                        "Analysis: Evaluate protocol cash flow, real TVL liquidity backing, "
                        "token unlock schedule, FDV vs MCap dilution risk, and organic vs speculative demand."
                    )

                    top_comments = [
                        f"🪙 CoinGecko Global Trending Search #{score + 1}",
                        f"Symbol: ${symbol} | Rank #{rank}",
                        f"24h Momentum: {price_chg_24h:+.1f}%",
                    ]
                    if detail:
                        top_comments.append(
                            f"MCap: {detail['mcap']} | FDV: {detail['fdv']} | Vol: {detail['vol_24h']}"
                        )

                    signals.append({
                        "post_id":      post_id,
                        "subreddit":    "coingecko",
                        "category":     "CRYPTO_ALPHA",
                        "title":        f"[Trending ${symbol}] {name} (Rank #{rank}): {price_chg_24h:+.1f}% (24h)",
                        "selftext":     "\n".join(lines),
                        "permalink":    f"https://www.coingecko.com/en/coins/{coin_id}",
                        "flair":        f"${symbol}",
                        "score":        100 - score,
                        "num_comments": 0,
                        "velocity":     round(abs(price_chg_24h) / 24.0, 2),
                        "controversy":  0.45,
                        "top_comments": top_comments,
                    })

        except Exception as e:
            print(f"   [Crypto/CoinGecko 采集异常]: {e}")

        return signals[:max_signals]
