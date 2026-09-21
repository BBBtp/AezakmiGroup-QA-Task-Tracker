from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path
import re
from urllib.parse import urlparse

from dotenv import load_dotenv


DEFAULT_DOQA_SPACE_IDS = (2, 4, 6)


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
    doqa_parser_output_dir: Path = Path("task_tracker_data/doqa_runs")
    doqa_parser_max_input_mb: int = 40
    doqa_parser_max_pages: int = 250
    doqa_parser_concurrency: int = 1
    doqa_parser_allowed_usernames: tuple[str, ...] = ()
    doqa_base_url: str | None = None
    doqa_api_token: str | None = None
    doqa_report_url_template: str | None = None
    doqa_space_id: int | None = None
    doqa_space_ids: tuple[int, ...] = DEFAULT_DOQA_SPACE_IDS
    doqa_api_timeout_seconds: int = 60
    doqa_report_retry_delays_seconds: tuple[int, ...] = (15, 60, 180)
    doqa_pdf_font_path: Path | None = None
    qadb_url: str | None = None
    qadb_service_key: str | None = None
    qadb_report_timezone: str = "+03:00"
    qadb_timeout_seconds: int = 60


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
    doqa_parser_output_dir = Path(
        getenv("DOQA_PARSER_OUTPUT_DIR", "task_tracker_data/doqa_runs").strip()
        or "task_tracker_data/doqa_runs"
    )
    doqa_parser_max_input_mb = max(1, int(getenv("DOQA_PARSER_MAX_INPUT_MB", "40")))
    doqa_parser_max_pages = max(1, int(getenv("DOQA_PARSER_MAX_PAGES", "250")))
    doqa_parser_concurrency = max(1, int(getenv("DOQA_PARSER_CONCURRENCY", "1")))
    configured_parser_users = tuple(
        username.strip().lower().lstrip("@")
        for username in getenv("DOQA_PARSER_ALLOWED_USERNAMES", "").split(",")
        if username.strip()
    )
    doqa_parser_allowed_usernames = configured_parser_users or miniapp_allowed_usernames
    doqa_base_url = getenv("DOQA_BASE_URL", "").strip().rstrip("/") or None
    doqa_api_token = getenv("DOQA_API_TOKEN", "").strip() or None
    doqa_report_url_template = getenv("DOQA_REPORT_URL_TEMPLATE", "").strip() or None
    configured_space_id = getenv("DOQA_SPACE_ID", "").strip()
    doqa_space_id = int(configured_space_id) if configured_space_id else None
    configured_space_ids = getenv(
        "DOQA_SPACE_IDS",
        ",".join(str(space_id) for space_id in DEFAULT_DOQA_SPACE_IDS),
    )
    doqa_space_ids = tuple(
        dict.fromkeys(
            int(value.strip())
            for value in configured_space_ids.split(",")
            if value.strip()
        )
    )
    doqa_api_timeout_seconds = max(5, int(getenv("DOQA_API_TIMEOUT_SECONDS", "60")))
    doqa_report_retry_delays_seconds = tuple(
        max(1, int(value.strip()))
        for value in getenv("DOQA_REPORT_RETRY_DELAYS_SECONDS", "15,60,180").split(",")
        if value.strip()
    ) or (15, 60, 180)
    configured_font_path = getenv("DOQA_PDF_FONT_PATH", "").strip()
    doqa_pdf_font_path = Path(configured_font_path) if configured_font_path else None
    qadb_url = getenv("QADB_URL", "").strip().rstrip("/") or None
    qadb_service_key = getenv("QADB_SERVICE_KEY", "").strip() or None
    qadb_report_timezone = getenv("QADB_REPORT_TZ", "+03:00").strip() or "+03:00"
    qadb_timeout_seconds = max(5, int(getenv("QADB_TIMEOUT_SECONDS", "60")))
    doqa_values = (doqa_base_url, doqa_api_token, doqa_report_url_template)
    if any(doqa_values) and not all(doqa_values):
        raise ValueError(
            "DOQA_BASE_URL, DOQA_API_TOKEN and DOQA_REPORT_URL_TEMPLATE must be configured together"
        )
    if doqa_base_url:
        parsed_base_url = urlparse(doqa_base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("DOQA_BASE_URL must be an absolute HTTP(S) URL")
    if doqa_report_url_template:
        parsed_report_url = urlparse(doqa_report_url_template)
        if "{run_id}" not in doqa_report_url_template:
            raise ValueError("DOQA_REPORT_URL_TEMPLATE must contain {run_id}")
        if parsed_report_url.scheme not in {"http", "https"} or not parsed_report_url.netloc:
            raise ValueError("DOQA_REPORT_URL_TEMPLATE must be an absolute HTTP(S) URL")
        if doqa_space_id is None:
            space_match = re.search(r"/detail/\d+/(\d+)/runs/", doqa_report_url_template)
            if space_match:
                doqa_space_id = int(space_match.group(1))
    if doqa_base_url and doqa_space_id is None:
        raise ValueError(
            "DOQA_SPACE_ID is required when it cannot be inferred from DOQA_REPORT_URL_TEMPLATE"
        )
    if any(space_id <= 0 for space_id in doqa_space_ids):
        raise ValueError("DOQA_SPACE_IDS must contain positive integers")
    if doqa_base_url and not doqa_space_ids:
        doqa_space_ids = (doqa_space_id,) if doqa_space_id is not None else ()
    if bool(qadb_url) != bool(qadb_service_key):
        raise ValueError("QADB_URL and QADB_SERVICE_KEY must be configured together")
    if qadb_url:
        parsed_qadb_url = urlparse(qadb_url)
        if parsed_qadb_url.scheme not in {"http", "https"} or not parsed_qadb_url.netloc:
            raise ValueError("QADB_URL must be an absolute HTTP(S) URL")

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
        doqa_parser_output_dir=doqa_parser_output_dir,
        doqa_parser_max_input_mb=doqa_parser_max_input_mb,
        doqa_parser_max_pages=doqa_parser_max_pages,
        doqa_parser_concurrency=doqa_parser_concurrency,
        doqa_parser_allowed_usernames=doqa_parser_allowed_usernames,
        doqa_base_url=doqa_base_url,
        doqa_api_token=doqa_api_token,
        doqa_report_url_template=doqa_report_url_template,
        doqa_space_id=doqa_space_id,
        doqa_space_ids=doqa_space_ids,
        doqa_api_timeout_seconds=doqa_api_timeout_seconds,
        doqa_report_retry_delays_seconds=doqa_report_retry_delays_seconds,
        doqa_pdf_font_path=doqa_pdf_font_path,
        qadb_url=qadb_url,
        qadb_service_key=qadb_service_key,
        qadb_report_timezone=qadb_report_timezone,
        qadb_timeout_seconds=qadb_timeout_seconds,
    )
