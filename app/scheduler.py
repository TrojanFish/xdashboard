from apscheduler.schedulers.background import BackgroundScheduler
from app.config import settings
from app.database import save_signal_and_draft
from app.ingestors.reddit import RedditIngestor
from app.engine.synthesizer import SynthesisEngine


def execute_radar_cycle():
    if not settings.GEMINI_API_KEY:
        print("[Scheduler] 未检测到 GEMINI_API_KEY，跳过本次巡航。")
        return

    print("🛰️ [Alpha Radar] 开始执行定时情报扫描与二创合成...")
    ingestor = RedditIngestor()
    engine = SynthesisEngine()

    signals = ingestor.fetch_qualified_signals(max_signals=5)
    print(f"🛰️ [Alpha Radar] 筛选出 {len(signals)} 条高斜率/高争议原始信号。")

    for sig in signals:
        try:
            print(f"   ⚙️ 正在加工: [r/{sig['subreddit']}] {sig['title'][:55]}...")
            draft_data = engine.synthesize(sig)
            save_signal_and_draft(sig, draft_data)
            status_tag = "✅ 入库待发" if draft_data["is_worth_posting"] else f"⏭️ 拦截 ({draft_data['skip_reason']})"
            print(f"   -> {status_tag}")
        except Exception as e:
            print(f"   ❌ 加工失败 [{sig['post_id']}]: {e}")


def start_background_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        execute_radar_cycle,
        "interval",
        minutes=settings.SCAN_INTERVAL_MINUTES,
        id="reddit_alpha_radar",
        replace_existing=True,
    )
    scheduler.start()
    print(f"⏱️ 后台定时巡航已启动：每 {settings.SCAN_INTERVAL_MINUTES} 分钟自动抓取一次。")
    return scheduler
