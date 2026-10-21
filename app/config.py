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

    # VPS 防 403 配置
    REDDIT_PROXY_URL: str = os.getenv("REDDIT_PROXY_URL", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    USER_AGENT: str = "linux:alpha.studio.personal:v1.0 (by /u/alpha_curator)"

settings = Settings()
