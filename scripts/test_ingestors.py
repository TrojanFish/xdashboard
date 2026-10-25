#!/usr/bin/env python3
"""
全网 6 大情报采集引擎连通性与数据获取测试脚本
用于在 VPS / Docker 容器内直接执行，排查网络与数据链路
"""

import sys
import os

# 避免 Windows 终端 GBK 编码输出 emoji 崩溃
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ingestors.github import GitHubTrendingIngestor
from app.ingestors.hackernews import HackerNewsIngestor
from app.ingestors.huggingface import HuggingFaceIngestor
from app.ingestors.commodities import CommoditiesEnergyIngestor
from app.ingestors.macro import MacroStocksIngestor
from app.ingestors.crypto import CryptoTrendingIngestor


def run_all_tests():
    print("=" * 60)
    print("🛰️ [Alpha Radar] 正在测试全网 6 大情报采集引擎连通性...")
    print("=" * 60)

    engines = [
        ("⭐ GitHub 开源趋势", GitHubTrendingIngestor(), "fetch_trending_signals"),
        ("🟠 Hacker News 深度讨论", HackerNewsIngestor(), "fetch_top_signals"),
        ("🤖 Hugging Face 模型/论文", HuggingFaceIngestor(), "fetch_trending_signals"),
        ("🛢️ OilPrice 原油/黄金/能源", CommoditiesEnergyIngestor(), "fetch_top_signals"),
        ("📈 MarketWatch 美股/宏观", MacroStocksIngestor(), "fetch_top_signals"),
        ("🪙 CoinGecko 加密资本趋势", CryptoTrendingIngestor(), "fetch_top_signals"),
    ]

    total_signals = 0

    for name, engine, method_name in engines:
        print(f"\n🔍 [测试中] {name}...")
        try:
            fn = getattr(engine, method_name)
            signals = fn(max_signals=2)
            if signals:
                print(f"   ✅ 成功捕获 {len(signals)} 条情报：")
                for s in signals:
                    print(f"      • [{s['category']}] {s['title'][:70]}")
                total_signals += len(signals)
            else:
                print("   ⚠️ 接口连通正常，但本次未返回新数据（可能数据已入库或被阈值过滤）")
        except Exception as e:
            print(f"   ❌ 采集失败，错误详情: {e}")

    print("\n" + "=" * 60)
    print(f"✨ 测试完成！共计成功获取 {total_signals} 条新鲜一手商业情报。")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
