import os

_BOT_GIVE_CHARACTER_ADMINS = (
    "242367586233352193",
    "112866272106012672",
    "289413979644755970",
    "704961055662538833",
    "348342650853785602",
    "476057912532533273",
    "435082104381112340",
)


class Config:
    # The adventure dungeon is closed for now; its pages redirect to Battles.
    DUNGEON_ENABLED = os.environ.get("DUNGEON_ENABLED", "0") == "1"
    KOFI_URL = os.environ.get("KOFI_URL", "https://ko-fi.com/eirblast")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # news cover uploads are the only file uploads
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
    DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
    DISCORD_REDIRECT_URI = os.environ.get(
        "DISCORD_REDIRECT_URI", "https://stfurequiem.com/auth/callback"
    )
    # Optional: lets the leaderboard show names of players who never logged in on the web
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
    DISCORD_ADMIN_IDS = frozenset(
        user_id.strip()
        for user_id in os.environ.get("DISCORD_ADMIN_IDS", "").split(",")
        if user_id.strip().isdigit()
    ) or frozenset(_BOT_GIVE_CHARACTER_ADMINS)

    # Stand art. The bot used https://storage.stfurequiem.com/Image/{id}.png
    IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "https://images.stfurequiem.com").rstrip("/")
    IMAGE_PATH = os.environ.get("IMAGE_PATH", "/Image/{id}.png")

    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30
