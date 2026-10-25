import logging
from typing import Optional, Dict, Any, List
import requests
from app.config import settings

logger = logging.getLogger("telegram_bot")


class TelegramClient:
    """轻量级 Telegram Bot API 客户端（基于原生 requests）"""

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self.session = requests.Session()
        proxy = settings.TELEGRAM_PROXY_URL or settings.REDDIT_PROXY_URL
        if proxy:
            self.session.proxies = {
                "http": proxy,
                "https": proxy,
            }

    @property
    def is_configured(self) -> bool:
        return bool(self.token and settings.TELEGRAM_ADMIN_CHAT_ID)

    def _post(self, method: str, data: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            return None
        url = f"{self.base_url}/{method}"
        try:
            resp = self.session.post(url, json=data if not files else None, data=data if files else None, files=files, timeout=timeout)
            res_json = resp.json()
            if not res_json.get("ok"):
                logger.warning(f"[Telegram API] {method} 响应错误: {res_json.get('description')}")
            return res_json
        except Exception as e:
            logger.error(f"[Telegram API] 请求异常 {method}: {e}")
            return None

    def get_me(self) -> Optional[Dict[str, Any]]:
        """获取机器人自身信息，用于连接连通性校验"""
        return self._post("getMe", timeout=10)

    def set_my_commands(self, commands: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """设置机器人的官方原生指令菜单 (点击输入框左侧的 [/] 或 Menu 即可弹出快捷菜单)"""
        return self._post("setMyCommands", data={"commands": commands})

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = True
    ) -> Optional[Dict[str, Any]]:
        """发送文本消息（自动防止超长）"""
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>...(内容过长已截断)...</i>"

        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", data=payload)

    def edit_message_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = True
    ) -> Optional[Dict[str, Any]]:
        """编辑已发送消息"""
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>...(内容过长已截断)...</i>"

        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("editMessageText", data=payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Optional[Dict[str, Any]]:
        """应答内联键盘点击回调"""
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        return self._post("answerCallbackQuery", data=payload, timeout=8)

    def send_photo(
        self,
        chat_id: str | int,
        photo_bytes_or_url: bytes | str,
        caption: Optional[str] = None,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """发送图片"""
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1024]
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup

        if isinstance(photo_bytes_or_url, bytes):
            files = {"photo": ("card.png", photo_bytes_or_url, "image/png")}
            return self._post("sendPhoto", data=data, files=files, timeout=25)
        else:
            data["photo"] = photo_bytes_or_url
            return self._post("sendPhoto", data=data, timeout=20)

    def get_updates(self, offset: Optional[int] = None, timeout: int = 25) -> List[Dict[str, Any]]:
        """长轮询拉取最新消息 updates"""
        payload: Dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"]
        }
        if offset is not None:
            payload["offset"] = offset

        res = self._post("getUpdates", data=payload, timeout=timeout + 10)
        if res and res.get("ok"):
            return res.get("result", [])
        return []
