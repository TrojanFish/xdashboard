import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PORT: int = int(os.getenv("PORT", "28828"))
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    STUDIO_PASSWORD: str = os.getenv("STUDIO_PASSWORD", "admin123")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
    X_HANDLE: str = os.getenv("X_HANDLE", "@YourXHandle")
    DB_PATH: str = os.getenv("DB_PATH", "/workspace/data/studio.db" if os.path.exists("/workspace") else "data/studio.db")
    SCAN_INTERVAL_MINUTES: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))

    # AI 模型配置 (适配 2026 最新官方模型)
    TRIAGE_MODEL: str = os.getenv("TRIAGE_MODEL", "gemini-2.5-flash")
    SYNTHESIS_MODEL: str = os.getenv("SYNTHESIS_MODEL", "gemini-3.1-pro-preview")

    # VPS 防 403 配置（支持住宅代理或浏览器已登录 Cookie）
    REDDIT_PROXY_URL: str = os.getenv("REDDIT_PROXY_URL", "")
    REDDIT_COOKIE: str = os.getenv("REDDIT_COOKIE", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Telegram Bot 与广播频道配置
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_ADMIN_CHAT_ID: str = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    TELEGRAM_NOTIFY_ON_CAPTURE: bool = os.getenv("TELEGRAM_NOTIFY_ON_CAPTURE", "1").lower() in ("1", "true", "yes")
    TELEGRAM_BROADCAST_ON_PUBLISH: bool = os.getenv("TELEGRAM_BROADCAST_ON_PUBLISH", "1").lower() in ("1", "true", "yes")
    TELEGRAM_PROXY_URL: str = os.getenv("TELEGRAM_PROXY_URL", "").strip()

settings = Settings()

if settings.STUDIO_PASSWORD in ("admin123", "change_me_to_strong_password", ""):
    print("[安全提示] 检测到 STUDIO_PASSWORD 使用了默认弱口令，请在生产环境部署时于 .env 中配置高强度密码以防未授权访问。")

