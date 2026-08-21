from __future__ import annotations

import re

from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from bot.services.doqa_report import DoqaReportQueue


RUN_ID_RE = re.compile(
    r"^\s*/(?:zip|doqa_report)(?:@\w+)?\s+(\d+)\s*$",
    re.IGNORECASE,
)
RUN_REFERENCE_RE = re.compile(
    r"(?:/runs?/|\bпрогон\s*#?\s*)(\d+)\b",
    re.IGNORECASE,
)
RETRY_RE = re.compile(r"^\s*повтори[.!]?\s*$", re.IGNORECASE)


class DoqaRetryFilter(BaseFilter):
    def __init__(self, queue: DoqaReportQueue) -> None:
        self.queue = queue

    async def __call__(self, message: Message) -> bool | dict[str, int]:
        if not RETRY_RE.match(message.text or "") or message.reply_to_message is None:
            return False
        job_id = self.queue.find_failed_job_for_error(
            message.chat.id,
            message.reply_to_message.message_id,
        )
        return {"doqa_job_id": job_id} if job_id is not None else False


def parse_doqa_run_id(value: str | None) -> int | None:
    if not value:
        return None
    match = RUN_ID_RE.match(value)
    return int(match.group(1)) if match else None


def parse_doqa_run_id_from_reference(value: str | None) -> int | None:
    if not value:
        return None
    match = RUN_REFERENCE_RE.search(value)
    return int(match.group(1)) if match else None


def replied_message_content(message: Message) -> str:
    replied = message.reply_to_message
    if replied is None:
        return ""

    parts = [replied.text or "", replied.caption or ""]
    for entity in (*(replied.entities or ()), *(replied.caption_entities or ())):
        if entity.url:
            parts.append(entity.url)
    return "\n".join(parts)


def create_doqa_reports_router(
    queue: DoqaReportQueue,
    *,
    allowed_usernames: tuple[str, ...] = (),
) -> Router:
    router = Router(name="doqa_reports")
    allowed = {username.casefold().lstrip("@") for username in allowed_usernames}

    @router.message(Command("zip", "doqa_report"))
    async def doqa_report_handler(message: Message) -> None:
        username = (message.from_user.username or "").casefold() if message.from_user else ""
        if allowed and username not in allowed:
            await message.answer("У вас нет доступа к отчётам DoQA.")
            return

        if message.reply_to_message is None:
            await message.answer(
                "Ответьте командой /zip 385 на сообщение разработчика."
            )
            return

        run_id = parse_doqa_run_id(message.text or message.caption)
        if run_id is None:
            run_id = parse_doqa_run_id_from_reference(replied_message_content(message))
        if run_id is None:
            await message.answer(
                "Не нашёл номер прогона. Используйте /zip 385 или ответьте /zip "
                "на сообщение со ссылкой DoQA."
            )
            return

        await queue.enqueue(
            chat_id=message.chat.id,
            command_message_id=message.message_id,
            target_message_id=message.reply_to_message.message_id,
            external_id=run_id,
        )

    @router.message(DoqaRetryFilter(queue))
    async def doqa_retry_handler(message: Message, doqa_job_id: int) -> None:
        username = (message.from_user.username or "").casefold() if message.from_user else ""
        if allowed and username not in allowed:
            await message.answer("У вас нет доступа к отчётам DoQA.")
            return
        await queue.retry(doqa_job_id, reaction_message_id=message.message_id)

    return router
