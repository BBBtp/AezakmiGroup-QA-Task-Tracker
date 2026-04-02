from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

from bot.config import load_settings
from bot.db.session import init_db
from bot.handlers.commands import create_commands_router
from bot.handlers.messages import create_messages_router
from bot.live_updates import LiveUpdateBroadcaster
from bot.services.parser.resolver import MessageParser
from bot.services.report_service import ReportService
from bot.services.task_service import TaskService
from bot.web import create_web_app


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    session_factory = init_db(settings.database_url)

    bot_session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    if settings.telegram_proxy_url:
        logging.info("Telegram proxy is enabled")

    bot = Bot(
        token=settings.bot_token,
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()

    parser = MessageParser()
    task_service = TaskService()
    report_service = ReportService()
    broadcaster = LiveUpdateBroadcaster()
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
        create_messages_router(
            session_factory=session_factory,
            parser=parser,
            task_service=task_service,
            broadcaster=broadcaster,
        )
    )

    web_app = create_web_app(session_factory, broadcaster)
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

    try:
        await dispatcher.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
