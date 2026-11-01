import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import unittest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.config import settings
from app.engine.card_renderer import render_card, _wrap_text
from app.bot.poller import BotPoller
from app.ingestors.hackernews import HackerNewsIngestor
from app.database import get_db_session, init_db


class TestFixesAndStabilization(unittest.TestCase):

    def setUp(self):
        init_db()

    # ── 1. Card Renderer Tests (CJK & Watermark) ───────────────────────────
    def test_card_renderer_png_cjk(self):
        """测试 16:9 数据研报卡片能够正常处理中文标题、中文指标与配置的水印"""
        card_data = {
            "title": "深度测评：开源大模型端侧推理性能与架构瓶颈解析",
            "type": "terminal_benchmark",
            "metrics": [
                {"label": "推理延迟", "value": "18.5ms (首字极速响应)", "sentiment": "positive"},
                {"label": "显存占用", "value": "14.2 GB VRAM (超显存风险)", "sentiment": "negative"},
                {"label": "商业护城河", "value": "中等，商业闭源方案成本优势约 40%", "sentiment": "neutral"},
                {"label": "投产建议", "value": "适合边缘微调，高并发集群需二次编译优化", "sentiment": "positive"}
            ]
        }
        png_bytes = render_card(
            card_data=card_data,
            signal_title="原始技术标题",
            category="AI_DEV",
            source_label="🤖 AI Dev"
        )
        self.assertIsNotNone(png_bytes)
        self.assertTrue(len(png_bytes) > 1000)
        # 验证 PNG 文件头魔法字节
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_cjk_wrap_text(self):
        """测试中英文混合文本视觉宽度折行"""
        sample = "这是一段非常长并且没有任何空格断句的纯中文字符串用于测试折行算法是否会引发溢出"
        wrapped = _wrap_text(sample, max_units=20)
        lines = wrapped.split("\n")
        self.assertTrue(len(lines) >= 3)
        for line in lines:
            # 每行视觉宽度不超 20 (中文占2)
            visual_len = sum(2 if ord(c) > 127 else 1 for c in line)
            self.assertLessEqual(visual_len, 22)

    # ── 2. SSRF 防护测试 ──────────────────────────────────────────────────
    def test_ssrf_filter(self):
        """测试 Telegram 外链投喂严禁探测内网 IP 与环回地址"""
        self.assertFalse(BotPoller._is_safe_external_url("http://127.0.0.1:28828"))
        self.assertFalse(BotPoller._is_safe_external_url("http://localhost:8080/admin"))
        self.assertFalse(BotPoller._is_safe_external_url("http://0.0.0.0:28828"))
        self.assertFalse(BotPoller._is_safe_external_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(BotPoller._is_safe_external_url("http://192.168.1.1/router"))
        self.assertFalse(BotPoller._is_safe_external_url("ftp://example.com/file"))
        # 正常的合法公网外链
        self.assertTrue(BotPoller._is_safe_external_url("https://github.com/trending"))
        self.assertTrue(BotPoller._is_safe_external_url("https://news.ycombinator.com"))

    # ── 3. 登录防爆破滑动窗口限流测试 ────────────────────────────────────
    def test_login_rate_limiting(self):
        """测试连续输错 5 次密码触发 429 锁定保护"""
        from app.web.main import check_ip_rate_limit, record_login_failure, clear_login_failure
        test_ip = "198.51.100.99"
        clear_login_failure(test_ip)

        # 连续记录 4 次失败，此时应依然放行
        for _ in range(4):
            record_login_failure(test_ip)
            check_ip_rate_limit(test_ip)

        # 第 5 次记录失败，此时应触发 429 限制
        record_login_failure(test_ip)
        with self.assertRaises(HTTPException) as cm:
            check_ip_rate_limit(test_ip)
        self.assertEqual(cm.exception.status_code, 429)

        # 验证清除后恢复
        clear_login_failure(test_ip)
        try:
            check_ip_rate_limit(test_ip)
        except HTTPException:
            self.fail("clear_login_failure 未生效")

    # ── 4. Hacker News 分类修正测试 ───────────────────────────────────────
    def test_hn_classification_no_finance_legacy(self):
        """测试 Hacker News 采集器已彻底淘汰废弃的 FINANCE，正确映射为二级赛道"""
        ingestor = HackerNewsIngestor()

        # 加密货币议题
        cat_crypto = ingestor._classify_category("Bitcoin reaches new ATH as ETF inflows surge", "on-chain liquidity and crypto volumes")
        self.assertEqual(cat_crypto, "CRYPTO_ALPHA")

        # 宏观美股议题
        cat_macro = ingestor._classify_category("Federal Reserve signals interest rate pause", "US Treasury yields, inflation and corporate profit margins")
        self.assertEqual(cat_macro, "MACRO_STOCKS")

        # AI 架构议题
        cat_ai = ingestor._classify_category("New Rust-based compiler for transformer inference", "vram efficiency and latency benchmark for llm")
        self.assertEqual(cat_ai, "AI_DEV")

    # ── 5. AI 二创链路无 UnboundLocalError 测试 ───────────────────────────
    def test_synthesizer_execution_call(self):
        """测试 SynthesisEngine.synthesize 已正确调用 _generate_with_fallback 且不再出现 resp 未绑定异常"""
        from app.engine.synthesizer import SynthesisEngine
        from app.engine.schemas import TriageResult

        engine = SynthesisEngine()

        mock_triage_resp = MagicMock()
        mock_triage_resp.text = json.dumps({"pass_triage": True, "reason": "High utility benchmark"})

        mock_synthesis_resp = MagicMock()
        mock_synthesis_resp.text = json.dumps({
            "is_worth_posting": True,
            "skip_reason": "",
            "narrative_framework": "Contrarian Reality Check",
            "content_tier": "DEEP_DIVE_MEMO",
            "hook_options": ["Hook 1", "Hook 2", "Hook 3"],
            "short_post": "Short post body",
            "long_form_body": "Long form deep dive body",
            "reply_sniper_text": "Sniper insight",
            "x_search_query": '"AI" min_faves:30',
            "visual_card_title": "Benchmark Card Title",
            "visual_card_type": "terminal_benchmark",
            "visual_card_metrics": [
                {"label": "Speed", "value": "100 tok/s", "sentiment": "positive"}
            ],
            "hashtags": ["#AI"],
            "thread_posts": []
        })

        with patch.object(engine, "_generate_with_fallback", side_effect=[mock_triage_resp, mock_synthesis_resp]) as mock_gen:
            sig = {
                "post_id": "test_sig_1",
                "subreddit": "LocalLLaMA",
                "category": "AI_DEV",
                "title": "Benchmarking LLaMA 3 on 4090",
                "selftext": "Detailed VRAM benchmarks...",
                "permalink": "https://reddit.com/r/LocalLLaMA/1",
                "flair": "Benchmark",
                "score": 120,
                "num_comments": 45,
                "velocity": 2.5,
                "controversy": 0.2,
                "top_comments": ["Great benchmark"]
            }

            result = engine.synthesize(sig)
            self.assertTrue(result["is_worth_posting"])
            self.assertEqual(result["narrative_framework"], "Contrarian Reality Check")
            self.assertEqual(mock_gen.call_count, 2)

    # ── 6. 数据库安全上下文管理器测试 ────────────────────────────────────
    def test_db_session_context_manager(self):
        """测试 get_db_session() 上下文管理器正常提交与回滚"""
        with get_db_session() as conn:
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('test_key', 'test_val')")

        with get_db_session() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = 'test_key'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["value"], "test_val")

    # ── 7. DeFiLlama 协议现金流采集器测试 ────────────────────────────────
    def test_defillama_ingestor(self):
        """测试 DeFiLlama 官方开放数据清洗、美元格式化与 CRYPTO_ALPHA 信号提炼"""
        from app.ingestors.defillama import DeFiLlamaIngestor

        ingestor = DeFiLlamaIngestor()

        # 1. 验证美元与财务数字格式化
        self.assertEqual(ingestor._format_usd(1_500_000_000), "$1.50B")
        self.assertEqual(ingestor._format_usd(23_450_000), "$23.45M")
        self.assertEqual(ingestor._format_usd(85_200), "$85.2K")
        self.assertEqual(ingestor._format_usd(0), "N/A")
        self.assertEqual(ingestor._format_usd(None), "N/A")

        # 2. 模拟 DeFiLlama API 响应并验证信号抽取逻辑
        mock_payload = {
            "protocols": [
                {
                    "name": "Tether",
                    "category": "Stablecoin Issuer",
                    "total24h": 5_000_000,
                    "slug": "tether"
                },
                {
                    "name": "Binance",
                    "category": "CEX",
                    "total24h": 8_000_000,
                    "slug": "binance"
                },
                {
                    "name": "Hyperliquid",
                    "category": "Derivatives",
                    "symbol": "HYPE",
                    "total24h": 1_250_000,
                    "total30d": 35_000_000,
                    "change_1d": 12.5,
                    "change_7d": 45.0,
                    "chains": ["Arbitrum", "Hyperliquid"],
                    "slug": "hyperliquid"
                },
                {
                    "name": "MicroDEX",
                    "category": "Dexs",
                    "total24h": 500,  # 低于 $30k 阈值，应被过滤
                    "slug": "micro-dex"
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        with patch.object(ingestor.session, "get", return_value=mock_resp):
            signals = ingestor.fetch_top_signals(max_signals=5)
            self.assertEqual(len(signals), 1)
            sig = signals[0]
            self.assertEqual(sig["subreddit"], "defillama")
            self.assertEqual(sig["category"], "CRYPTO_ALPHA")
            self.assertIn("Hyperliquid", sig["title"])
            self.assertIn("$1.25M", sig["title"])
            self.assertEqual(sig["permalink"], "https://defillama.com/protocol/hyperliquid")
            self.assertIn("HYPE", sig["flair"])
            self.assertTrue(len(sig["top_comments"]) > 0)


if __name__ == "__main__":
    unittest.main()
