from __future__ import annotations

from dataclasses import dataclass
from os import getenv

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    database_url: str
    bot_timezone: str = "Europe/Moscow"
    report_default_days: int = 14
    telegram_proxy_url: str | None = None
    miniapp_allowed_usernames: tuple[str, ...] = ()
    miniapp_auth_max_age_seconds: int = 86400
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_base_url: str = "http://127.0.0.1:8080/miniapp"


def load_settings() -> Settings:
    load_dotenv()

    bot_token = getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN is not configured")

    database_url = getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    bot_timezone = getenv("BOT_TIMEZONE", "Europe/Moscow").strip()
    report_default_days = int(getenv("REPORT_DEFAULT_DAYS", "14"))
    telegram_proxy_url = getenv("TELEGRAM_PROXY_URL", "").strip() or None
    miniapp_allowed_usernames = tuple(
        username.strip().lower()
        for username in getenv("MINIAPP_ALLOWED_USERNAMES", "").split(",")
        if username.strip()
    )
    miniapp_auth_max_age_seconds = int(getenv("MINIAPP_AUTH_MAX_AGE_SECONDS", "86400"))
    web_host = getenv("WEB_HOST", "127.0.0.1").strip()
    web_port = int(getenv("WEB_PORT", "8080"))
    web_base_url = getenv("WEB_BASE_URL", f"http://{web_host}:{web_port}/miniapp").strip()

    return Settings(
        bot_token=bot_token,
        database_url=database_url,
        bot_timezone=bot_timezone,
        report_default_days=report_default_days,
        telegram_proxy_url=telegram_proxy_url,
        miniapp_allowed_usernames=miniapp_allowed_usernames,
        miniapp_auth_max_age_seconds=miniapp_auth_max_age_seconds,
        web_host=web_host,
        web_port=web_port,
        web_base_url=web_base_url,
    )
