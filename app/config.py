import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PORT: int = int(os.getenv("PORT", "28828"))
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    STUDIO_PASSWORD: str = os.getenv("STUDIO_PASSWORD", "admin123")
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

settings = Settings()
