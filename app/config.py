import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
    DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
    DISCORD_REDIRECT_URI = os.environ.get(
        "DISCORD_REDIRECT_URI", "https://stfurequiem.com/auth/callback"
    )
    # Optional: lets the leaderboard show names of players who never logged in on the web
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

    # Stand art. The bot used https://storage.stfurequiem.com/Image/{id}.png
    IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "https://images.stfurequiem.com").rstrip("/")
    IMAGE_PATH = os.environ.get("IMAGE_PATH", "/Image/{id}.png")

    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30
