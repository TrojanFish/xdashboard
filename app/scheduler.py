import threading
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import settings
from app.database import save_signal_and_draft
from app.ingestors.reddit import RedditIngestor
from app.ingestors.github import GitHubTrendingIngestor
from app.engine.synthesizer import SynthesisEngine

_scan_lock = threading.Lock()


def execute_radar_cycle():
    if not settings.GEMINI_API_KEY:
        print("[Scheduler] 未检测到 GEMINI_API_KEY，跳过本次巡航。请在 .env 中配置 GEMINI_API_KEY。")
        return

    # 防重入锁：如果上一轮扫描未结束，直接跳过，避免重复消耗 Token 和死锁
    if not _scan_lock.acquire(blocking=False):
        print("⚠️ [Alpha Radar] 上一轮扫描与二创流水线正在运行中，跳过本次重叠触发。")
        return

    try:
        print("🛰️ [Alpha Radar] 开始执行定时全网情报扫描（Reddit + GitHub Trending）...")
        reddit_ingestor = RedditIngestor()
        github_ingestor = GitHubTrendingIngestor()
        engine = SynthesisEngine()

        all_signals = []

        # 1. 抓取 Reddit 高潜力贴
        try:
            reddit_signals = reddit_ingestor.fetch_qualified_signals(max_signals=4)
            all_signals.extend(reddit_signals)
            print(f"   [Reddit] 筛选出 {len(reddit_signals)} 条高斜率信号。")
        except Exception as e:
            print(f"   ❌ Reddit 采集失败: {e}")

        # 2. 抓取 GitHub Trending 热门项目
        try:
            gh_signals = github_ingestor.fetch_trending_signals(max_signals=3)
            all_signals.extend(gh_signals)
            print(f"   [GitHub Trending] 筛选出 {len(gh_signals)} 个爆款开源项目。")
        except Exception as e:
            print(f"   ❌ GitHub 采集失败: {e}")

        print(f"🛰️ [Alpha Radar] 本轮共有 {len(all_signals)} 条候选信号进入 AI 认知加工流水线...")

        for sig in all_signals:
            try:
                print(f"   ⚙️ 正在深度二创: [{sig['subreddit']}] {sig['title'][:55]}...")
                draft_data = engine.synthesize(sig)
                save_signal_and_draft(sig, draft_data)
                status_tag = "✅ 入库待发" if draft_data["is_worth_posting"] else f"⏭️ 拦截 ({draft_data['skip_reason']})"
                print(f"   -> {status_tag}")
            except Exception as e:
                print(f"   ❌ 加工失败 [{sig['post_id']}]: {e}")
    finally:
        _scan_lock.release()


def start_background_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        execute_radar_cycle,
        "interval",
        minutes=settings.SCAN_INTERVAL_MINUTES,
        id="alpha_radar_unified",
        replace_existing=True,
    )
    scheduler.start()
    print(f"⏱️ 后台定时巡航已启动：每 {settings.SCAN_INTERVAL_MINUTES} 分钟自动抓取一次（Reddit + GitHub Trending）。")
    return scheduler
