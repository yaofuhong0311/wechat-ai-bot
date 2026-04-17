import os


class Settings:
    # wkteam API
    WKTEAM_API_URL: str = os.getenv("WKTEAM_API_URL", "")
    WKTEAM_TOKEN: str = os.getenv("WKTEAM_TOKEN", "")
    WKTEAM_WID: str = os.getenv("WKTEAM_WID", "")
    BOT_WCID: str = os.getenv("BOT_WCID", "")

    # Claude Agent SDK (passed as env to CLI subprocess)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL", "")

    # Security: webhook path secret, only wkteam knows the full URL
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "xf7k9m2q")

    # Whitelist: comma-separated chatroom IDs, empty = all
    ALLOWED_GROUPS: str = os.getenv("ALLOWED_GROUPS", "")

    # Service
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
