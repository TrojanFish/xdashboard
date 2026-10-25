import logging
from typing import Dict, Any, Optional
from app.config import settings
from app.database import get_conn, get_raw_signal
from app.bot.client import TelegramClient
from app.bot.formatter import (
    format_signal_card,
    build_signal_inline_keyboard,
    format_channel_post
)

logger = logging.getLogger("telegram_bot")


def get_tg_client() -> TelegramClient:
    return TelegramClient()


def notify_admin_new_signal(draft_data: Dict[str, Any], raw_sig: Dict[str, Any]) -> bool:
    """当后台巡航捕获新高价值信号时，推送到 Admin 个人私聊"""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ADMIN_CHAT_ID and settings.TELEGRAM_NOTIFY_ON_CAPTURE):
        return False

    client = get_tg_client()
    try:
        text = format_signal_card(draft_data, raw_sig)
        post_id = raw_sig.get("post_id", "")
        long_post = draft_data.get("long_form_body") or draft_data.get("long_post", "")
        status = draft_data.get("status", "pending")
        keyboard = build_signal_inline_keyboard(post_id, long_post, status=status)

        res = client.send_message(
            chat_id=settings.TELEGRAM_ADMIN_CHAT_ID,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return bool(res and res.get("ok"))
    except Exception as e:
        logger.error(f"[Telegram] 推送情报卡片失败: {e}")
        return False


def broadcast_published_draft(post_id: str) -> bool:
    """当草稿标记为已发布时，自动广播至公开/VIP 频道"""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHANNEL_ID and settings.TELEGRAM_BROADCAST_ON_PUBLISH):
        return False

    conn = get_conn()
    draft_row = conn.execute("SELECT * FROM drafts WHERE post_id = ?", (post_id,)).fetchone()
    conn.close()

    if not draft_row:
        return False

    raw_sig = get_raw_signal(post_id)
    if not raw_sig:
        return False

    draft_dict = dict(draft_row)
    client = get_tg_client()
    try:
        channel_text = format_channel_post(draft_dict, raw_sig)
        res = client.send_message(
            chat_id=settings.TELEGRAM_CHANNEL_ID,
            text=channel_text,
            disable_web_page_preview=False
        )
        return bool(res and res.get("ok"))
    except Exception as e:
        logger.error(f"[Telegram] 频道广播失败: {e}")
        return False
