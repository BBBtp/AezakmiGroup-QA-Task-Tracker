from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy.orm import sessionmaker

from bot.live_updates import LiveUpdateBroadcaster
from bot.services.report_service import ReportService
from bot.services.task_service import TaskService
from bot.utils.formatters import format_task_list


def create_commands_router(
    session_factory: sessionmaker,
    task_service: TaskService,
    report_service: ReportService,
    report_default_days: int,
    web_base_url: str,
    broadcaster: LiveUpdateBroadcaster,
) -> Router:
    router = Router(name="commands")

    @router.message(Command("my"))
    async def my_tasks_handler(message: Message) -> None:
        if message.from_user is None:
            return

        with session_factory() as session:
            user = task_service.get_or_create_user(
                session,
                telegram_user_id=message.from_user.id,
                username=message.from_user.username,
            )
            tasks = task_service.list_open_tasks(session, assignee_user_id=user.id)
            await message.answer(format_task_list(tasks, "Мои активные задачи:"))

    @router.message(Command("open"))
    async def open_tasks_handler(message: Message) -> None:
        with session_factory() as session:
            tasks = task_service.list_open_tasks(session)
            await message.answer(format_task_list(tasks, "Все активные задачи:"))

    @router.message(Command("report"))
    async def report_handler(message: Message) -> None:
        parts = (message.text or "").split()
        days = report_default_days
        if len(parts) > 1:
            try:
                days = max(1, int(parts[1]))
            except ValueError:
                await message.answer("Использование: /report 14")
                return

        with session_factory() as session:
            tasks = report_service.completed_tasks_for_last_days(session, days)
            await message.answer(report_service.format_report(tasks, days))

    @router.message(Command("done"))
    async def done_handler(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Использование: /done image_170")
            return

        with session_factory() as session:
            result = task_service.manual_done(session, parts[1].strip().lower())
            session.commit()
            if result.task is not None:
                await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
            await message.answer(result.message)

    @router.message(Command("app"))
    async def app_handler(message: Message) -> None:
        if web_base_url.startswith("https://"):
            button = InlineKeyboardButton(
                text="Открыть задачи",
                web_app=WebAppInfo(url=web_base_url),
            )
        else:
            button = InlineKeyboardButton(
                text="Открыть задачи",
                url=web_base_url,
            )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
        await message.answer(
            f"Мини-апп со всеми задачами: {web_base_url}",
            reply_markup=keyboard,
        )

    return router
