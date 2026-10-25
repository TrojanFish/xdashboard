import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import settings
from app.database import save_signal_and_draft, save_raw_signal_only, get_setting
from app.ingestors.reddit import RedditIngestor
from app.ingestors.github import GitHubTrendingIngestor
from app.ingestors.hackernews import HackerNewsIngestor
from app.ingestors.huggingface import HuggingFaceIngestor
from app.ingestors.commodities import CommoditiesEnergyIngestor
from app.ingestors.macro import MacroStocksIngestor
from app.ingestors.crypto import CryptoTrendingIngestor
from app.engine.synthesizer import SynthesisEngine

_scan_lock = threading.Lock()

_scan_state = {
    "running": False,
    "status": "idle",
    "message": "系统就绪",
    "signals_found": 0,
    "processed": 0,
    "total": 0,
    "added_count": 0,
    "last_completed_at": None,
    "error": None,
}


def get_scan_state() -> dict:
    """获取当前后台扫描任务的实时执行状态与进度"""
    return dict(_scan_state)


def execute_radar_cycle():
    auto_synthesize = (get_setting("auto_synthesize", "0") == "1")

    # 如果开启了自动二创，则必须校验 Gemini Key；如果处于手动省 Token 模式，仅需抓取
    if auto_synthesize:
        has_valid_key = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your_gemini_api_key_here")
        if not has_valid_key:
            msg = "未配置有效的 GEMINI_API_KEY，且已开启「自动 AI 二创」。请在 .env 中填入 Google Gemini API Key，或在控制台切换为「仅抓取原始情报 (省 Token)」模式。"
            print(f"[Scheduler] {msg}")
            _scan_state["running"] = False
            _scan_state["status"] = "error"
            _scan_state["message"] = msg
            return

    # 防重入锁：如果上一轮扫描未结束，直接跳过
    if not _scan_lock.acquire(blocking=False):
        print("⚠️ [Alpha Radar] 上一轮扫描流水线正在运行中，跳过本次重叠触发。")
        return

    _scan_state["running"] = True
    _scan_state["status"] = "scraping"
    _scan_state["message"] = "正在抓取 GitHub Trending 热门开源项目..."
    _scan_state["processed"] = 0
    _scan_state["total"] = 0
    _scan_state["added_count"] = 0
    _scan_state["error"] = None

    try:
        print("🛰️ [Alpha Radar] 开始执行全网商业情报扫描（GitHub + Hacker News + Hugging Face + 能源大宗 + 美股宏观 + 加密资本）...")
        github_ingestor = GitHubTrendingIngestor()
        hn_ingestor = HackerNewsIngestor()
        hf_ingestor = HuggingFaceIngestor()
        cmd_ingestor = CommoditiesEnergyIngestor()
        macro_ingestor = MacroStocksIngestor()
        crypto_ingestor = CryptoTrendingIngestor()
        reddit_ingestor = RedditIngestor()

        all_signals = []

        # 1. GitHub Trending 热门开源爆款
        try:
            gh_signals = github_ingestor.fetch_trending_signals(max_signals=2)
            all_signals.extend(gh_signals)
            print(f"   [GitHub Trending] 筛选出 {len(gh_signals)} 个爆款开源项目。")
        except Exception as e:
            print(f"   ❌ GitHub 采集失败: {e}")

        # 2. Hacker News 硅谷顶级架构师/AI/资本深度议题 (官方 REST API)
        _scan_state["message"] = f"正在扫描 Hacker News 硅谷前沿讨论..."
        try:
            hn_signals = hn_ingestor.fetch_top_signals(max_signals=2)
            all_signals.extend(hn_signals)
            print(f"   [Hacker News] 筛选出 {len(hn_signals)} 条深度议题。")
        except Exception as e:
            print(f"   ❌ Hacker News 采集失败: {e}")

        # 3. Hugging Face Trending 模型权重与前沿学术论文 (AI_DEV 官方源)
        _scan_state["message"] = f"正在扫描 Hugging Face 爆款开源模型与前沿论文..."
        try:
            hf_signals = hf_ingestor.fetch_trending_signals(max_signals=2)
            all_signals.extend(hf_signals)
            print(f"   [Hugging Face] 筛选出 {len(hf_signals)} 个前沿开源模型/论文。")
        except Exception as e:
            print(f"   ❌ Hugging Face 采集失败: {e}")

        # 4. OilPrice 原油/天然气/核电与黄金大宗商品 (COMMODITIES_ENERGY 官方源)
        _scan_state["message"] = f"正在扫描 OilPrice & 大宗能源原油与黄金一手情报..."
        try:
            cmd_signals = cmd_ingestor.fetch_top_signals(max_signals=2)
            all_signals.extend(cmd_signals)
            print(f"   [能源大宗/石油黄金] 筛选出 {len(cmd_signals)} 条核心宏观大宗动态。")
        except Exception as e:
            print(f"   ❌ 能源大宗 采集失败: {e}")

        # 5. MarketWatch / 道琼斯美股与宏观异动 (MACRO_STOCKS 官方源)
        _scan_state["message"] = f"正在扫描华尔街美股异动与道琼斯宏观脉搏..."
        try:
            macro_signals = macro_ingestor.fetch_top_signals(max_signals=2)
            all_signals.extend(macro_signals)
            print(f"   [美股宏观] 筛选出 {len(macro_signals)} 条华尔街异动与美联储信号。")
        except Exception as e:
            print(f"   ❌ 美股宏观 采集失败: {e}")

        # 6. CoinGecko 链上流动性与趋势热榜 (CRYPTO_ALPHA 官方源)
        _scan_state["message"] = f"正在扫描 CoinGecko 全球加密资本趋势..."
        try:
            crypto_signals = crypto_ingestor.fetch_top_signals(max_signals=2)
            all_signals.extend(crypto_signals)
            print(f"   [加密资本] 筛选出 {len(crypto_signals)} 条趋势信号。")
        except Exception as e:
            print(f"   ❌ 加密资本 采集失败: {e}")

        # 7. Reddit 社区热贴 (遇 403 自动平滑跳过，保证流水线不中断)
        _scan_state["message"] = f"正在巡检 Reddit 社区深度讨论..."
        try:
            reddit_signals = reddit_ingestor.fetch_qualified_signals(max_signals=2)
            all_signals.extend(reddit_signals)
            if reddit_signals:
                print(f"   [Reddit] 筛选出 {len(reddit_signals)} 条高斜率信号。")
        except Exception as e:
            print(f"   ❌ Reddit 采集失败: {e}")

        _scan_state["signals_found"] = len(all_signals)
        _scan_state["total"] = len(all_signals)

        if not all_signals:
            msg = "本轮全网巡航完成，未发现新满足阈值的信号（或今日内容已全部入库）。"
            print(f"🛰️ [Alpha Radar] {msg}")
            _scan_state["running"] = False
            _scan_state["status"] = "idle"
            _scan_state["message"] = msg
            _scan_state["last_completed_at"] = datetime.now().strftime("%H:%M:%S")
            return

        added_count = 0

        # 分支 A：开启自动二创 (全自动全流水线)
        if auto_synthesize:
            print(f"🛰️ [Alpha Radar] [全自动模式] 本轮共有 {len(all_signals)} 条候选信号进入 AI 深度二创流水线...")
            _scan_state["status"] = "synthesizing"
            engine = SynthesisEngine()

            for idx, sig in enumerate(all_signals):
                try:
                    _scan_state["processed"] = idx + 1
                    short_title = sig['title'][:28]
                    _scan_state["message"] = f"AI 深度二创加工中 ({idx + 1}/{len(all_signals)}): [{sig['subreddit']}] {short_title}..."
                    print(f"   ⚙️ 正在深度二创 ({idx + 1}/{len(all_signals)}): [{sig['subreddit']}] {sig['title'][:55]}...")
                    
                    draft_data = engine.synthesize(sig)
                    save_signal_and_draft(sig, draft_data)
                    
                    if draft_data.get("is_worth_posting"):
                        added_count += 1
                        status_tag = "✅ 入库待发"
                        # 触发 Telegram 实时推流
                        try:
                            from app.bot.manager import notify_admin_new_signal
                            notify_admin_new_signal(draft_data, sig)
                        except Exception as e_tg:
                            print(f"      [Telegram 推送异常]: {e_tg}")
                    else:
                        status_tag = f"⏭️ 初筛拦截 ({draft_data.get('skip_reason', '')})"
                    print(f"   -> {status_tag}")
                except Exception as e:
                    print(f"   ❌ 加工失败 [{sig['post_id']}]: {e}")

            _scan_state["added_count"] = added_count
            _scan_state["running"] = False
            _scan_state["status"] = "done"
            _scan_state["message"] = f"全网扫描与合成完成！成功入库 {added_count} 条新草稿。"
            _scan_state["last_completed_at"] = datetime.now().strftime("%H:%M:%S")
            print(f"✨ [Alpha Radar] 本轮加工完毕，新增 {added_count} 条草稿入库。")

        # 分支 B：关闭自动二创 (手动精选 / 节省 Token 模式)
        else:
            print(f"🛰️ [Alpha Radar] [手动精选模式] 存入 {len(all_signals)} 条原始情报，不消耗 AI Token，等待手动触发二创...")
            _scan_state["status"] = "saving"

            for idx, sig in enumerate(all_signals):
                try:
                    _scan_state["processed"] = idx + 1
                    short_title = sig['title'][:28]
                    _scan_state["message"] = f"原始情报入库中 ({idx + 1}/{len(all_signals)}): [{sig['subreddit']}] {short_title}..."
                    save_raw_signal_only(sig)
                    added_count += 1
                    print(f"   📥 原始情报入库 (待手动二创): [{sig['subreddit']}] {sig['title'][:55]}...")
                    # 触发 Telegram 原始线索卡片推流（方便手机端一键点击 [AI 重塑]）
                    try:
                        from app.bot.manager import notify_admin_new_signal
                        raw_preview_draft = {
                            "status": "raw_unprocessed",
                            "narrative_framework": "Pending AI Synthesis",
                            "content_tier": "DEEP_DIVE_MEMO",
                            "short_post": "已抓取新原始情报，可在下方直接点击 [🤖 AI 重塑] 触发深度加工。",
                            "hook_options": [],
                        }
                        notify_admin_new_signal(raw_preview_draft, sig)
                    except Exception as e_tg:
                        print(f"      [Telegram 推送异常]: {e_tg}")
                except Exception as e:
                    print(f"   ❌ 入库失败 [{sig['post_id']}]: {e}")

            _scan_state["added_count"] = added_count
            _scan_state["running"] = False
            _scan_state["status"] = "done"
            _scan_state["message"] = f"情报采集完成！已存入 {added_count} 条原始线索，可在工作台按需点击 [立即二创] 深度加工。"
            _scan_state["last_completed_at"] = datetime.now().strftime("%H:%M:%S")
            print(f"✨ [Alpha Radar] 原始情报入库完毕，新增 {added_count} 条待二创信号。")

    except Exception as e:
        _scan_state["running"] = False
        _scan_state["status"] = "error"
        _scan_state["error"] = str(e)
        _scan_state["message"] = f"扫描流程发生异常: {e}"
        print(f"❌ [Alpha Radar] 致命异常: {e}")
    finally:
        _scan_lock.release()


def _scheduled_radar_cycle():
    """后台定时器触发函数：先检查后台自动巡航开关是否开启"""
    if get_setting("auto_scan_enabled", "1") != "1":
        print("⏱️ [Scheduler] 定时巡航已关闭（当前处于手动触发模式），跳过本次自动扫描。")
        return
    execute_radar_cycle()


def start_background_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _scheduled_radar_cycle,
        "interval",
        minutes=settings.SCAN_INTERVAL_MINUTES,
        id="alpha_radar_unified",
        replace_existing=True,
    )
    scheduler.start()
    print(f"⏱️ 后台定时巡航已启动：每 {settings.SCAN_INTERVAL_MINUTES} 分钟自动抓取一次（GitHub Trending + Hacker News + Reddit）。")
    return scheduler
