from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Document, FSInputFile, Message

from bot.services.doqa_pdf.service import DoqaPdfService, DoqaRun


DOQA_CAPTION_RE = re.compile(r"^\s*(?:#doqa|/parse(?:@\w+)?)\s*$", re.IGNORECASE)


def is_doqa_parse_caption(value: str | None) -> bool:
    return bool(value and DOQA_CAPTION_RE.match(value))


def create_doqa_documents_router(
    service: DoqaPdfService,
    *,
    allowed_usernames: tuple[str, ...] = (),
) -> Router:
    router = Router(name="doqa_documents")
    allowed = {username.casefold().lstrip("@") for username in allowed_usernames}

    @router.message(Command("parse"))
    async def parse_command_handler(message: Message, bot: Bot) -> None:
        source_message = message if message.document else message.reply_to_message
        document = source_message.document if source_message else None
        if document is None:
            await message.answer(
                "Прикрепите PDF к команде /parse или ответьте командой /parse на сообщение с PDF."
            )
            return
        await _handle_pdf(message, bot, document, service, allowed)

    @router.message(
        F.document.mime_type == "application/pdf",
        F.caption.regexp(DOQA_CAPTION_RE),
    )
    async def caption_pdf_handler(message: Message, bot: Bot) -> None:
        if message.document is not None:
            await _handle_pdf(message, bot, message.document, service, allowed)

    return router


async def _handle_pdf(
    message: Message,
    bot: Bot,
    document: Document,
    service: DoqaPdfService,
    allowed: set[str],
) -> None:
    username = (message.from_user.username or "").casefold() if message.from_user else ""
    if allowed and username not in allowed:
        await message.answer("У вас нет доступа к DoQA-парсеру.")
        return

    if not (document.file_name or "").lower().endswith(".pdf"):
        await message.answer("Для парсинга нужен файл с расширением .pdf.")
        return
    if document.file_size and document.file_size > service.max_input_bytes:
        limit_mb = service.max_input_bytes // (1024 * 1024)
        await message.answer(f"PDF слишком большой. Максимальный размер: {limit_mb} МБ.")
        return

    run: DoqaRun | None = None
    status_message = await message.answer("PDF принят. Начинаю обработку…")
    try:
        run = service.prepare_run(document.file_name)
        await bot.download(document, destination=run.input_pdf)
        result = await service.process(run)
        count = len(result.report.bugs)
        await status_message.edit_text(f"Готово. Найдено багов: {count}.")
        await message.answer_document(
            FSInputFile(result.docx_path),
            caption=f"DoQA: найдено багов — {count}",
        )
        await message.answer_document(
            FSInputFile(result.archive_path),
            caption="Полный результат парсинга",
        )
    except ValueError as exc:
        await status_message.edit_text(f"Не удалось обработать PDF: {exc}")
    except Exception:
        logging.exception("DoQA PDF parsing failed")
        await status_message.edit_text(
            "Не удалось обработать PDF из-за внутренней ошибки. Подробности записаны в журнал."
        )
    finally:
        if run is not None:
            await asyncio.to_thread(service.cleanup, run)
