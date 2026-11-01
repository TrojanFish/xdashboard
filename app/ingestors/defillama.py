import hashlib
import re
from typing import List, Dict, Any
import requests
from app.config import settings
from app.database import get_processed_signal_ids


class DeFiLlamaIngestor:
    """
    DeFiLlama 官方开放 API 采集器 (100% 官方公开、零 API Key、海外 VPS 零拦截)
    汇聚全球顶尖链上协议的真实手续费收入 (Protocol Fees & Revenue) 与 TVL 资金动量
    为 AI 架构师 × 资本量化人设提供最干净、无 Meme 噪音的机构级基本面数据
    """
    FEES_API = "https://api.llama.fi/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyFees"
    PROTOCOLS_API = "https://api.llama.fi/protocols"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.USER_AGENT or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"
        })

    def _format_usd(self, val: float | int | None) -> str:
        if val is None or val == 0:
            return "N/A"
        val = float(val)
        if val >= 1_000_000_000:
            return f"${val / 1e9:.2f}B"
        if val >= 1_000_000:
            return f"${val / 1e6:.2f}M"
        if val >= 1_000:
            return f"${val / 1e3:.1f}K"
        return f"${val:,.0f}"

    def fetch_top_signals(self, max_signals: int = 3) -> List[Dict[str, Any]]:
        """
        采集头部真实协议现金流与 TVL 异动：
        1. 优先精选 24h 真实手续费 > $30k 的高现金流协议（过滤纯 CEX 与发币发钞方）
        2. 结合 7d 资金动量与年化收入折算，提炼具高信息密度的链上基本面情报
        """
        processed_ids = get_processed_signal_ids()
        signals = []

        try:
            resp = self.session.get(self.FEES_API, timeout=12)
            if resp.status_code != 200:
                print(f"   [DeFiLlama Fees API 响应异常]: HTTP {resp.status_code}")
                return []

            data = resp.json()
            protocols = data.get("protocols", [])

            # 过滤非链上应用（CEX、中心化发钞方）以及费用过低的微型项目
            excluded_cats = {"Stablecoin Issuer", "CEX", "Chain", "Bridge"}
            candidates = []
            for p in protocols:
                cat = p.get("category") or "DeFi"
                if cat in excluded_cats:
                    continue
                f24 = p.get("total24h") or 0
                if f24 >= 30_000:
                    candidates.append(p)

            # 按 24 小时真实手续费产生排序
            candidates.sort(key=lambda x: x.get("total24h") or 0, reverse=True)

            for p in candidates:
                if len(signals) >= max_signals:
                    break

                name = p.get("name", "")
                if not name:
                    continue

                slug = p.get("slug") or p.get("defillamaId") or re.sub(r"[^a-zA-Z0-9]", "_", name.lower())
                post_id = f"dl_{slug}"
                if post_id in processed_ids:
                    continue

                category = p.get("category") or "DeFi"
                f24 = p.get("total24h") or 0
                f30 = p.get("total30d") or 0
                change_1d = p.get("change_1d") or 0.0
                change_7d = p.get("change_7d") or 0.0
                chains = p.get("chains") or ["Multi-Chain"]
                chains_str = ", ".join(chains[:3]) if isinstance(chains, list) else str(chains)

                f24_str = self._format_usd(f24)
                f30_str = self._format_usd(f30)
                ann_runrate = self._format_usd(f24 * 365)

                symbol = p.get("symbol")
                flair_ticker = f"${symbol.upper()}" if symbol else category.upper()

                title = f"[{category}] {name}: 24h 手续费 {f24_str} (年化流水 {ann_runrate})"

                lines = [
                    f"Protocol: {name} ({flair_ticker})",
                    f"Category: {category}",
                    f"Ecosystem Chains: {chains_str}",
                    f"24h Protocol Fees: {f24_str} (1d: {change_1d:+.1f}%)",
                    f"30d Cumulative Fees: {f30_str}",
                    f"Annualized Cash Flow Run-Rate: {ann_runrate}",
                    "",
                    "### ON-CHAIN LIQUIDITY & UNIT ECONOMICS TEARDOWN:",
                    f"Analyze {name}'s capital efficiency, real yield sustainability, and institutional fee capture moat.",
                    "Evaluate P/S multiples vs traditional SaaS, user take-rate defensibility, and systemic smart contract risks.",
                ]

                signals.append({
                    "post_id": post_id,
                    "subreddit": "defillama",
                    "category": "CRYPTO_ALPHA",
                    "title": title,
                    "selftext": "\n".join(lines),
                    "permalink": f"https://defillama.com/protocol/{slug}",
                    "flair": flair_ticker,
                    "score": min(int(f24 / 5000), 200),
                    "num_comments": 0,
                    "velocity": round(abs(change_1d) / 24.0 + abs(change_7d) / 7.0, 2),
                    "controversy": 0.30,
                    "top_comments": [
                        f"🦙 DeFiLlama Verified Protocol Cash Flow",
                        f"24h Fees: {f24_str} | 30d: {f30_str}",
                        f"Chains: {chains_str}",
                        f"Official Terminal: https://defillama.com/protocol/{slug}"
                    ]
                })

        except Exception as e:
            print(f"   [DeFiLlama 采集异常]: {e}")

        return signals[:max_signals]
