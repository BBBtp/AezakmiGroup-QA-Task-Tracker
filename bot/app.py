from __future__ import annotations

import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

from bot.config import load_settings
from bot.db.session import init_db
from bot.handlers.commands import create_commands_router
from bot.handlers.doqa_documents import create_doqa_documents_router
from bot.handlers.doqa_reports import create_doqa_reports_router
from bot.handlers.messages import create_messages_router
from bot.integrations.doqa import DoqaClient
from bot.live_updates import LiveUpdateBroadcaster
from bot.services.doqa_pdf.service import DoqaPdfService
from bot.services.doqa_report import DoqaReportQueue, DoqaReportService
from bot.services.parser.resolver import MessageParser
from bot.services.report_service import ReportService
from bot.services.task_service import TaskService
from bot.web import create_web_app


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    session_factory = init_db(settings.database_url)

    bot_session = AiohttpSession(proxy=settings.telegram_proxy_url)
    if not settings.telegram_proxy_url:
        # Telegram advertises IPv4 and IPv6, but some local/VPN routes accept an
        # IPv6 socket and then break long-polling TLS connections. IPv4 is
        # universally available for the Bot API and is more stable here.
        bot_session._connector_init["family"] = socket.AF_INET
    if settings.telegram_proxy_url:
        logging.info("Telegram proxy is enabled")

    bot = Bot(
        token=settings.bot_token,
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    bot_info = await bot.me()
    dispatcher = Dispatcher()

    parser = MessageParser()
    task_service = TaskService()
    report_service = ReportService()
    broadcaster = LiveUpdateBroadcaster()
    doqa_pdf_service = DoqaPdfService(
        settings.doqa_parser_output_dir,
        max_input_bytes=settings.doqa_parser_max_input_mb * 1024 * 1024,
        max_pages=settings.doqa_parser_max_pages,
        concurrency=settings.doqa_parser_concurrency,
    )
    doqa_report_queue: DoqaReportQueue | None = None
    with session_factory() as session:
        updated_tasks = task_service.backfill_existing_tasks(session)
        session.commit()
    logging.info("Backfilled existing tasks: %s", updated_tasks)

    dispatcher.include_router(
        create_commands_router(
            session_factory=session_factory,
            task_service=task_service,
            report_service=report_service,
            report_default_days=settings.report_default_days,
            web_base_url=settings.web_base_url,
            broadcaster=broadcaster,
        )
    )
    dispatcher.include_router(
        create_doqa_documents_router(
            doqa_pdf_service,
            allowed_usernames=settings.doqa_parser_allowed_usernames,
        )
    )
    if settings.doqa_base_url and settings.doqa_api_token and settings.doqa_report_url_template:
        doqa_client = DoqaClient(
            settings.doqa_base_url,
            settings.doqa_api_token,
            space_id=settings.doqa_space_id,
            timeout_seconds=settings.doqa_api_timeout_seconds,
        )
        doqa_report_service = DoqaReportService(
            doqa_client,
            doqa_pdf_service,
            settings.doqa_report_url_template,
            font_path=settings.doqa_pdf_font_path,
            concurrency=settings.doqa_parser_concurrency,
        )
        doqa_report_queue = DoqaReportQueue(
            bot,
            session_factory,
            doqa_report_service,
            retry_delays_seconds=settings.doqa_report_retry_delays_seconds,
        )
        dispatcher.include_router(
            create_doqa_reports_router(
                doqa_report_queue,
                allowed_usernames=settings.doqa_parser_allowed_usernames,
            )
        )
        logging.info("DoQA report command is enabled")
    else:
        logging.info("DoQA report command is disabled: API settings are not configured")
    dispatcher.include_router(
        create_messages_router(
            session_factory=session_factory,
            parser=parser,
            task_service=task_service,
            report_service=report_service,
            broadcaster=broadcaster,
            bot_username=bot_info.username,
        )
    )

    web_app = create_web_app(session_factory, broadcaster, settings)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.web_host, port=settings.web_port)
    await site.start()
    logging.info("Task dashboard started at %s", settings.web_base_url)

    if settings.web_base_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Задачи",
                web_app=WebAppInfo(url=settings.web_base_url),
            )
        )
        logging.info("Telegram menu button configured for mini app")
    else:
        logging.info("WEB_BASE_URL is not HTTPS, mini app menu button was not configured")

    if doqa_report_queue is not None:
        await doqa_report_queue.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        if doqa_report_queue is not None:
            await doqa_report_queue.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
