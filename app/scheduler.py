import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import settings
from app.database import save_signal_and_draft, save_raw_signal_only, get_setting
from app.ingestors.reddit import RedditIngestor
from app.ingestors.github import GitHubTrendingIngestor
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
    auto_synthesize = (get_setting("auto_synthesize", "1") == "1")

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
        print("🛰️ [Alpha Radar] 开始执行全网情报扫描（优先 GitHub Trending + Reddit）...")
        github_ingestor = GitHubTrendingIngestor()
        reddit_ingestor = RedditIngestor()

        all_signals = []

        # 1. 优先抓取 GitHub Trending 热门开源爆款（速度快、无封禁风险）
        try:
            gh_signals = github_ingestor.fetch_trending_signals(max_signals=3)
            all_signals.extend(gh_signals)
            print(f"   [GitHub Trending] 筛选出 {len(gh_signals)} 个爆款开源项目。")
        except Exception as e:
            print(f"   ❌ GitHub 采集失败: {e}")

        # 2. 抓取 Reddit 高潜力贴（遇连续403自动熔断跳过）
        _scan_state["message"] = f"已捕获 {len(all_signals)} 个 GitHub 项目，正在扫描 Reddit 社区..."
        try:
            reddit_signals = reddit_ingestor.fetch_qualified_signals(max_signals=3)
            all_signals.extend(reddit_signals)
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
    print(f"⏱️ 后台定时巡航已启动：每 {settings.SCAN_INTERVAL_MINUTES} 分钟自动抓取一次（GitHub Trending + Reddit）。")
    return scheduler
