import json
import logging
import re
import threading
import time
from typing import Dict, Any, Optional
import requests

from app.config import settings
from app.database import (
    get_conn, get_raw_signal, save_signal_and_draft,
    get_setting, set_setting
)
from app.bot.client import TelegramClient
from app.bot.formatter import (
    format_signal_card,
    build_signal_inline_keyboard,
    format_status_message,
    format_help_message,
    escape
)
from app.bot.manager import broadcast_published_draft

logger = logging.getLogger("telegram_bot")


class BotPoller:
    """Telegram Bot 长轮询后台服务与指令交互分发器"""

    def __init__(self):
        self.client = TelegramClient()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_update_id = 0

    def start(self):
        if not self.client.is_configured:
            print("ℹ️ [Telegram Bot] 未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_ADMIN_CHAT_ID，跳过启动 Telegram 守护轮询。")
            return
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, name="TelegramBotPoller", daemon=True)
        self.thread.start()
        print(f"🤖 [Telegram Bot] 智能守护轮询已启动，已绑定 Admin ID: {settings.TELEGRAM_ADMIN_CHAT_ID}")

    def stop(self):
        self.running = False

    def _is_admin(self, user_id: int | str) -> bool:
        """严格白名单鉴权，只有预设的 Admin 能够操控机器人"""
        return str(user_id) == str(settings.TELEGRAM_ADMIN_CHAT_ID)

    def _run_loop(self):
        # 启动时先测试连通性
        me = self.client.get_me()
        if me and me.get("ok"):
            bot_username = me.get("result", {}).get("username", "UnknownBot")
            print(f"🤖 [Telegram Bot] 验证连接成功: @{bot_username}")
        else:
            print("⚠️ [Telegram Bot] 连通性测试未返回成功，可能网络受限或 Token 有误，将继续尝试长轮询...")

        backoff = 1
        while self.running:
            try:
                updates = self.client.get_updates(offset=self.last_update_id + 1, timeout=20)
                backoff = 1  # 成功拉取，重置退避延迟

                for update in updates:
                    update_id = update.get("update_id", 0)
                    if update_id > self.last_update_id:
                        self.last_update_id = update_id

                    if "message" in update:
                        self._handle_message(update["message"])
                    elif "callback_query" in update:
                        self._handle_callback_query(update["callback_query"])

            except Exception as e:
                logger.warning(f"[Telegram Poller] 轮询异常 (将在 {backoff}s 后重试): {e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 20)

    def _handle_message(self, msg: Dict[str, Any]):
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        from_user = msg.get("from", {})
        user_id = from_user.get("id")
        text = (msg.get("text") or "").strip()

        if not self._is_admin(user_id):
            logger.warning(f"[Telegram Bot] 拦截到未授权访问: UserID={user_id}, Text={text[:30]}")
            return

        if not text:
            return

        # 1. 基础系统指令路由
        if text.startswith("/"):
            cmd = text.split()[0].lower().split("@")[0]
            if cmd == "/start":
                self._cmd_start(chat_id)
            elif cmd == "/scan":
                self._cmd_scan(chat_id)
            elif cmd == "/status":
                self._cmd_status(chat_id)
            elif cmd == "/auto":
                self._cmd_toggle_auto(chat_id)
            elif cmd == "/help":
                self.client.send_message(chat_id, format_help_message())
            else:
                self.client.send_message(chat_id, "未知指令，输入 /help 查看支持的操作。")
            return

        # 2. 移动端 URL 智能投喂二创 (Drop-in Curation)
        urls = re.findall(r'https?://[^\s]+', text)
        if urls:
            self._handle_url_curation(chat_id, urls[0])
        else:
            self.client.send_message(
                chat_id,
                "💡 发送 URL（如 GitHub 项目链接或技术文章），AI 将自动解析并提炼二创；或输入 /help 查看指令。"
            )

    def _cmd_start(self, chat_id: int | str):
        welcome = f"""👋 <b>你好！Personal Alpha Studio 移动指挥中枢已就绪。</b>
━━━━━━━━━━━━━━━━━━━━
您已成功连接本专属机器人。
所有扫描捕获的高信噪比情报将实时推送到此处，支持一键长推提取、发帖唤起与快捷归档。

输入 /help 查看所有控制指令，或输入 /scan 立即触发全网扫描。"""
        self.client.send_message(chat_id, welcome)

    def _cmd_scan(self, chat_id: int | str):
        from app.scheduler import execute_radar_cycle, get_scan_state
        state = get_scan_state()
        if state.get("running"):
            self.client.send_message(chat_id, "⚠️ 当前已有扫描流水线正在运行中，请等待其执行完毕...")
            return

        self.client.send_message(chat_id, "🚀 <b>已远程触发全网扫描！</b>\n正在探测 GitHub Trending + Hacker News + Reddit，捕获优质线索后将自动推送到此处...")
        # 后台异步启动扫描
        threading.Thread(target=execute_radar_cycle, name="RemoteScanTask", daemon=True).start()

    def _cmd_status(self, chat_id: int | str):
        from app.scheduler import get_scan_state
        conn = get_conn()
        total_raw = conn.execute("SELECT COUNT(*) FROM raw_signals").fetchone()[0]
        pending_drafts = conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'pending'").fetchone()[0]
        published_drafts = conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'published'").fetchone()[0]
        archived_drafts = conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'archived'").fetchone()[0]
        conn.close()

        auto_synth = get_setting("auto_synthesize", "1") == "1"
        auto_scan = get_setting("auto_scan_enabled", "1") == "1"
        scan_state = get_scan_state()

        stats = {
            "scan_interval": settings.SCAN_INTERVAL_MINUTES,
            "auto_scan_text": "已开启" if auto_scan else "已暂停",
            "auto_synth_text": "🤖 全自动二创" if auto_synth else "⏳ 仅抓取 (省 Token)",
            "synthesis_model": settings.SYNTHESIS_MODEL,
            "total_raw": total_raw,
            "pending_drafts": pending_drafts,
            "published_drafts": published_drafts,
            "archived_drafts": archived_drafts,
            "last_scan": scan_state.get("last_completed_at") or scan_state.get("message")
        }
        self.client.send_message(chat_id, format_status_message(stats))

    def _cmd_toggle_auto(self, chat_id: int | str):
        current = get_setting("auto_synthesize", "1") == "1"
        new_val = "0" if current else "1"
        set_setting("auto_synthesize", new_val)
        mode_text = "🤖 全自动 AI 二创模式" if new_val == "1" else "⏳ 节省 Token 模式 (仅抓取原始情报)"
        self.client.send_message(chat_id, f"✅ 已切换系统模式为: <b>{mode_text}</b>")

    def _handle_url_curation(self, chat_id: int | str, url: str):
        """解析外链并调用 AI 生成双格式草稿与卡片"""
        self.client.send_message(chat_id, f"📥 <b>正在解析外部情报</b>:\n<code>{escape(url)}</code>\n请稍候 10~25 秒...")

        # 启动独立线程加工，不阻塞长轮询接收其他消息
        threading.Thread(target=self._async_curate_url, args=(chat_id, url), daemon=True).start()

    def _async_curate_url(self, chat_id: int | str, url: str):
        try:
            # 1. 判断是否为 GitHub 链接
            m_gh = re.search(r'github\.com/([^/]+/[^/#?]+)', url)
            if m_gh:
                repo = m_gh.group(1).rstrip(".git")
                from app.ingestors.github import GitHubTrendingIngestor
                readme = GitHubTrendingIngestor()._fetch_readme(repo)

                sig = {
                    "post_id": f"gh_custom_{repo.replace('/', '_')}",
                    "subreddit": "github/custom",
                    "category": "GITHUB_TRENDING",
                    "title": f"[Custom] {repo}",
                    "selftext": f"Repository: https://github.com/{repo}\nREADME:\n{readme}",
                    "permalink": url,
                    "flair": "Custom Repo",
                    "score": 100,
                    "num_comments": 0,
                    "velocity": 5.0,
                    "controversy": 0.1,
                    "top_comments": [f"Custom ingested from Telegram: {url}"]
                }
            else:
                # 通用网页爬取
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = requests.get(url, headers=headers, timeout=12)
                html_text = resp.text
                clean_title = re.search(r'<title[^>]*>(.*?)</title>', html_text, re.IGNORECASE)
                title = clean_title.group(1).strip() if clean_title else "External Article"
                clean_body = re.sub(r'<[^>]+>', ' ', html_text)
                clean_body = re.sub(r'\s+', ' ', clean_body).strip()[:3500]

                clean_id = re.sub(r'[^a-zA-Z0-9]', '_', url[-30:])
                sig = {
                    "post_id": f"web_{clean_id}",
                    "subreddit": "web/article",
                    "category": "AI_DEV",
                    "title": title[:100],
                    "selftext": clean_body,
                    "permalink": url,
                    "flair": "External",
                    "score": 50,
                    "num_comments": 0,
                    "velocity": 1.0,
                    "controversy": 0.2,
                    "top_comments": [f"Source URL: {url}"]
                }

            # 2. 调用 AI 深度提炼
            from app.engine.synthesizer import SynthesisEngine
            from app.engine.synthesizer import SynthesisEngine
            engine = SynthesisEngine()
            draft_data = engine.synthesize(sig)
            save_signal_and_draft(sig, draft_data)

            # 3. 回送卡片与操作按钮
            card_text = format_signal_card(draft_data, sig)
            long_post = draft_data.get("long_form_body") or draft_data.get("long_post", "")
            keyboard = build_signal_inline_keyboard(sig["post_id"], long_post=long_post, status="pending")
            self.client.send_message(chat_id, card_text, reply_markup=keyboard)

        except Exception as e:
            logger.error(f"[URL Curation] 解析失败: {e}")
            self.client.send_message(chat_id, f"❌ <b>情报加工失败</b>: {escape(str(e))}")

    def _handle_callback_query(self, cb: Dict[str, Any]):
        cb_id = cb.get("id")
        from_user = cb.get("from", {})
        user_id = from_user.get("id")
        data = cb.get("data") or ""
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        if not self._is_admin(user_id):
            self.client.answer_callback_query(cb_id, text="无权限操作", show_alert=True)
            return

        if ":" not in data:
            self.client.answer_callback_query(cb_id)
            return

        action, post_id = data.split(":", 1)

        if action == "noop":
            self.client.answer_callback_query(cb_id, text="当前草稿已处于该状态")
            return

        conn = get_conn()

        if action == "copy":
            row = conn.execute("SELECT long_post, short_post FROM drafts WHERE post_id = ?", (post_id,)).fetchone()
            conn.close()
            if row:
                content = row["long_post"] or row["short_post"] or "暂无长推内容"
                self.client.send_message(chat_id, f"📋 <b>完整长推文案 (可直接长按复制)</b>:\n\n{escape(content)}")
                self.client.answer_callback_query(cb_id, text="已发送长推文案至聊天界面")
            else:
                self.client.answer_callback_query(cb_id, text="未找到草稿数据", show_alert=True)

        elif action == "pub":
            conn.execute("UPDATE drafts SET status = 'published' WHERE post_id = ?", (post_id,))
            conn.commit()
            conn.close()

            # 触发公开频道广播
            broadcast_ok = broadcast_published_draft(post_id)

            # 更新当前消息按钮
            new_kb = build_signal_inline_keyboard(post_id, status="published")
            self.client.edit_message_text(chat_id, message_id, msg.get("text", ""), reply_markup=new_kb)

            notice = "✅ 已标记为发布！" + (" (已同步广播至 Telegram 频道)" if broadcast_ok else "")
            self.client.answer_callback_query(cb_id, text=notice)

        elif action == "arch":
            conn.execute("UPDATE drafts SET status = 'archived' WHERE post_id = ?", (post_id,))
            conn.commit()
            conn.close()

            new_kb = build_signal_inline_keyboard(post_id, status="archived")
            self.client.edit_message_text(chat_id, message_id, msg.get("text", ""), reply_markup=new_kb)
            self.client.answer_callback_query(cb_id, text="🗑️ 已归档跳过")

        elif action == "synth":
            conn.close()
            self.client.answer_callback_query(cb_id, text="⚙️ 正在重新调用 AI 深度重塑...")
            threading.Thread(target=self._async_resynthesize, args=(chat_id, message_id, post_id), daemon=True).start()

        else:
            conn.close()
            self.client.answer_callback_query(cb_id)

    def _async_resynthesize(self, chat_id: int | str, message_id: int, post_id: str):
        try:
            raw_sig = get_raw_signal(post_id)
            if not raw_sig:
                self.client.send_message(chat_id, "未找到对应的原始情报，无法二创。")
                return

            from app.engine.synthesizer import SynthesisEngine
            engine = SynthesisEngine()
            draft_data = engine.synthesize(raw_sig)
            save_signal_and_draft(raw_sig, draft_data)

            # 更新原消息为最新卡片内容
            updated_text = format_signal_card(draft_data, raw_sig)
            long_post = draft_data.get("long_form_body") or draft_data.get("long_post", "")
            keyboard = build_signal_inline_keyboard(post_id, long_post=long_post, status="pending")

            self.client.edit_message_text(chat_id, message_id, updated_text, reply_markup=keyboard)
            self.client.send_message(chat_id, f"✨ <b>[{raw_sig.get('title', '')[:30]}]</b> 二创重塑完成！")
        except Exception as e:
            logger.error(f"[Re-synthesize] 异常: {e}")
            self.client.send_message(chat_id, f"❌ AI 二创重塑失败: {escape(str(e))}")


# 全局单例
_poller_instance: Optional[BotPoller] = None


def start_telegram_bot_poller() -> Optional[BotPoller]:
    """供 FastAPI 启动时调用的入口函数"""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = BotPoller()
    _poller_instance.start()
    return _poller_instance
