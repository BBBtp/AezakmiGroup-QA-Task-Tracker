from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from typing import ClassVar
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.methods import TelegramMethod
from aiogram.types import (
    Chat,
    ChatMemberUpdated,
    Message,
    MessageReactionUpdated,
    ReactionTypeEmoji,
    ReplyParameters,
)
from sqlalchemy.orm import sessionmaker

from bot.live_updates import LiveUpdateBroadcaster
from bot.db.models import TaskEventType, TaskStatus
from bot.services.parser.resolver import MessageParser
from bot.services.report_service import ReportService
from bot.services.task_service import TaskService

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DATE_TOKEN_RE = re.compile(r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b")
MONTHS_RU = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}
RU_DATE_TOKEN_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|"
    r"август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])"
    r"(?:\s+(?P<year>\d{4}))?(?:\s+г(?:ода?)?)?\b",
    re.IGNORECASE,
)
RU_SHARED_MONTH_RANGE_RE = re.compile(
    r"\bс\s+(?P<start_day>\d{1,2})\s+по\s+(?P<end_day>\d{1,2})\s+"
    r"(?P<month>январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|"
    r"август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])"
    r"(?:\s+(?P<year>\d{4}))?(?:\s+г(?:ода?)?)?\b",
    re.IGNORECASE,
)
APP_SET_RE = re.compile(r"^(?:добавь|добавить|укажи|указать|поставь|изменить|измени)?\s*приложение\s+(?P<body>.+)$", re.IGNORECASE)
APP_CLEAR_RE = re.compile(r"^(?:убери|удали|очисти|сними)\s+(?:название\s+)?приложени[ея]\b(?P<body>.*)$", re.IGNORECASE)
TASK_DELETE_RE = re.compile(r"^(?:удали|удалить|архивируй|в\s+архив)\s+(?:задачу|приложение)?\s*(?P<body>.*)$", re.IGNORECASE)
TASK_CREATE_RE = re.compile(
    r"^(?:создай|создать|добавь|добавить|отследи|отслеживай|начни\s+отслеживать)\s+задач[ау]\b(?P<body>.*)$",
    re.IGNORECASE,
)
TASK_ASSIGN_RE = re.compile(
    r"^(?:взять(?:\s+в\s+работу)?|возьми(?:\s+в\s+работу)?|отслеживать|начать\s+отслеживать|"
    r"назначь\s+меня|назначить\s+меня|назначь(?:\s+на\s+меня)?)(?:\s+(?P<body>.*))?$",
    re.IGNORECASE,
)


class SendRichMessage(TelegramMethod[Message]):
    __returning__: ClassVar[type[Message]] = Message
    __api_method__: ClassVar[str] = "sendRichMessage"

    chat_id: int | str
    rich_message: dict[str, object]
    reply_parameters: ReplyParameters | None = None

BOT_RULES_TEXT = """Правила QA task tracker

1. Новая задача
Отправьте отдельное сообщение с id задачи и ссылками.

Пример:
@diiaanag @glebc0re @bbbbbbtp
idApp 320
ТЗ: https://docs.google.com/...
ФИГМА: https://www.figma.com/...
прила на тесты

Исполнитель не назначается по тегу. Исполнитель назначается реакцией тестировщика на исходное сообщение задачи.

2. История задачи
Все отчеты, фиксы, вопросы, замечания и закрытие пишутся ответом на исходную задачу или ответом на сообщение из ее истории.

Одиночные сообщения вне reply-цепочки бот не привязывает к задаче и не меняет по ним статус.

3. Отчет
Отчетом считается архив .zip, .rar или .7z, отправленный ответом в историю задачи.

Google Docs больше не считается отчетом. Если написать "указал, что не исправлено", это будет замечание.

4. Фикс или обновление
Пишите ответом в историю задачи:
фиксы
перезалил
поправили
обновили

5. Закрытие задачи
Закрытие работает только коротким ответом в истории задачи:
все окей
готово
сделано
закрыто

6. Ручная смена статуса
Можно ответить на задачу или сообщение из ее истории:
@bot поставь статус в работе
@bot поставь статус завершено
@bot поставь статус пауза

Можно указать id без reply:
@bot статус idapp_320 в работе

7. Взять задачу в работу
Можно ответить на задачу:
@bot взять

Или указать id без reply:
@bot взять idapp_320

8. Принудительно создать задачу
Если бот не распознал исходное сообщение, ответьте на него:
@bot создай задачу

9. Сводка по чату
@bot дай статус задач с 6 июня по 30 июня

Сводка показывает только задачи текущего чата.

10. Название приложения
Можно указать приложение по id:
@bot приложение idapp_320 QA Tracker

Или ответить на сообщение задачи:
@bot приложение QA Tracker

11. Архив и удаление
@bot удалить приложение idapp_320

Первый вызов переносит задачу в архив. Повторный вызов для задачи в архиве удаляет ее навсегда.

12. Реакции бота
👍 — новая задача создана.
👀 — сообщение добавлено в историю задачи.
🙏 — принят отчет-архив.
✍️ — добавлены замечания.
⚡ — добавлен фикс или обновление.
🏆 — задача закрыта.
💯 — команда боту выполнена.

Если Telegram не принимает основную реакцию в чате, бот пробует запасную реакцию."""

REACTION_NEW_TASK = ("👍", "🎉")
REACTION_HISTORY = ("👀", "👍")
REACTION_REPORT = ("🙏", "👀")
REACTION_REVIEW = ("✍️", "👀")
REACTION_UPDATE = ("⚡", "👀")
REACTION_DONE = ("🏆", "🎉")
REACTION_COMMAND = ("💯", "👍")


def resolve_chat_title(chat: Chat) -> str | None:
    title = getattr(chat, "title", None)
    if title:
        return title
    first_name = getattr(chat, "first_name", None)
    last_name = getattr(chat, "last_name", None)
    if first_name or last_name:
        return " ".join(part for part in [first_name, last_name] if part)
    username = getattr(chat, "username", None)
    return username


def build_message_payload(message: Message) -> str | None:
    parts: list[str] = []

    if message.document:
        if message.document.file_name:
            parts.append(f"Документ: {message.document.file_name}")
            parts.append(message.document.file_name)
        else:
            parts.append("Документ")
    if message.photo:
        photo_count = len(message.photo)
        parts.append(f"Фото: {photo_count} вложение" if photo_count == 1 else f"Фото: {photo_count} вложения")
    if message.video:
        parts.append("Видео")
    if message.animation:
        parts.append("GIF")
    if message.sticker:
        sticker_label = f"Стикер {message.sticker.emoji}".strip() if message.sticker.emoji else "Стикер"
        parts.append(sticker_label)
    if message.video_note:
        parts.append("Видео-сообщение")
    if message.voice:
        parts.append("Голосовое сообщение")

    if message.text:
        parts.append(message.text)
    elif message.caption:
        parts.append(message.caption)

    payload = "\n".join(part.strip() for part in parts if part and part.strip())
    return payload or None


async def set_processing_reaction(bot: Bot, message: Message, emojis: tuple[str, ...]) -> None:
    for emoji in emojis:
        try:
            await bot.set_message_reaction(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return
        except Exception as error:
            logging.warning(
                "Failed to set bot reaction %s for chat=%s message=%s: %s",
                emoji,
                message.chat.id,
                message.message_id,
                error,
            )


def is_bot_mentioned(text: str, bot_username: str | None) -> bool:
    if not bot_username:
        return False
    return f"@{bot_username.lower()}" in text.lower()


def strip_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text.strip()
    return re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()


def parse_date_token(token: str) -> date | None:
    normalized = token.replace("/", ".")
    now = datetime.now(MOSCOW_TZ)
    formats = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d.%m")
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        year = parsed.year if "%Y" in fmt or "%y" in fmt else now.year
        return date(year, parsed.month, parsed.day)
    return None


def parse_ru_date_matches(text: str) -> list[date]:
    now = datetime.now(MOSCOW_TZ)
    dates: list[date] = []
    for match in RU_DATE_TOKEN_RE.finditer(text):
        month = MONTHS_RU.get(match.group("month").lower())
        if month is None:
            continue
        year = int(match.group("year")) if match.group("year") else now.year
        try:
            dates.append(date(year, month, int(match.group("day"))))
        except ValueError:
            continue
    return dates


def parse_period(text: str) -> tuple[datetime, datetime] | None:
    shared_month_range = RU_SHARED_MONTH_RANGE_RE.search(text)
    if shared_month_range:
        month = MONTHS_RU.get(shared_month_range.group("month").lower())
        year = int(shared_month_range.group("year")) if shared_month_range.group("year") else datetime.now(MOSCOW_TZ).year
        try:
            dates = [
                date(year, month, int(shared_month_range.group("start_day"))),
                date(year, month, int(shared_month_range.group("end_day"))),
            ]
        except (TypeError, ValueError):
            return None
    else:
        dates = parse_ru_date_matches(text)
        dates.extend(parsed for token in DATE_TOKEN_RE.findall(text) if (parsed := parse_date_token(token)))
    if not dates:
        return None

    start_day = dates[0]
    end_day = dates[1] if len(dates) > 1 else dates[0]
    if end_day < start_day:
        start_day, end_day = end_day, start_day

    start_local = datetime.combine(start_day, time.min, tzinfo=MOSCOW_TZ)
    end_local = datetime.combine(end_day, time.max, tzinfo=MOSCOW_TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def infer_manual_status(text: str) -> TaskStatus | None:
    lowered = text.lower()
    if any(token in lowered for token in ("заверш", "готово", "выполнено", "закрыть", "закрой", "закрыто")):
        return TaskStatus.DONE
    if any(token in lowered for token in ("в работе", "верни в работу", "открой", "открыть")):
        return TaskStatus.ASSIGNED
    if any(token in lowered for token in ("пауза", "на паузу", "paused")):
        return TaskStatus.PAUSED
    return None


async def reply_with_status_report(
    bot: Bot,
    message: Message,
    report_service: ReportService,
    tasks: list,
    date_from: datetime,
    date_to: datetime,
) -> None:
    rich_html = report_service.format_status_report_rich_html(tasks, date_from, date_to)
    try:
        await bot(
            SendRichMessage(
                chat_id=message.chat.id,
                rich_message={"html": rich_html},
                reply_parameters=ReplyParameters(message_id=message.message_id),
            )
        )
    except Exception as error:
        logging.warning("Rich status report failed, falling back to plain text: %s", error)
        await message.reply(report_service.format_status_report(tasks, date_from, date_to), parse_mode=None)


def app_name_from_directive(body: str, task_id_source: str | None) -> str:
    app_name = body
    if task_id_source:
        app_name = re.sub(re.escape(task_id_source), "", app_name, count=1, flags=re.IGNORECASE)
    app_name = re.sub(r"^(?:для|у|к)\s+", "", app_name.strip(), flags=re.IGNORECASE)
    return app_name.strip(" :-")


def resolve_directive_task(
    session,
    task_service: TaskService,
    *,
    chat_id: int,
    reply_message_id: int | None,
    task_key: str | None,
    include_archived: bool = False,
):
    if reply_message_id is not None:
        task = task_service.find_task_by_message_reference(
            session,
            chat_id=chat_id,
            message_id=reply_message_id,
            include_archived=include_archived,
        )
        if task is not None:
            return task
    if task_key:
        return task_service.find_task_by_key(session, task_key, include_archived=include_archived)
    return None


async def handle_bot_directive(
    *,
    bot: Bot,
    message: Message,
    payload: str,
    bot_username: str | None,
    parser: MessageParser,
    task_service: TaskService,
    report_service: ReportService,
    session_factory: sessionmaker,
    broadcaster: LiveUpdateBroadcaster,
) -> bool:
    if not is_bot_mentioned(payload, bot_username):
        return False

    directive_text = strip_bot_mention(payload, bot_username)
    lowered = directive_text.lower()

    if "правил" in lowered or "как отвечать" in lowered:
        await message.reply(BOT_RULES_TEXT)
        return True

    if "статус" in lowered and ("задач" in lowered or "период" in lowered):
        period = parse_period(directive_text)
        if period is None:
            await message.reply("Формат периода: @bot дай статус задач с 01.06 по 10.06")
            return True
        date_from, date_to = period
        with session_factory() as session:
            tasks = report_service.tasks_for_period(
                session,
                date_from,
                date_to,
                chat_id=message.chat.id,
            )
        logging.info(
            "STATUS report chat_id=%s date_from=%s date_to=%s tasks=%s",
            message.chat.id,
            date_from.isoformat(),
            date_to.isoformat(),
            len(tasks),
        )
        await reply_with_status_report(bot, message, report_service, tasks, date_from, date_to)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    parse_result = parser.parse(directive_text, is_reply=False)
    task_key = parse_result.resolved_task_id.canonical_task_key if parse_result.resolved_task_id else None
    reply_message_id = message.reply_to_message.message_id if message.reply_to_message else None
    actor_username = message.from_user.username if message.from_user else None

    create_match = TASK_CREATE_RE.match(directive_text)
    if create_match:
        source_message = message.reply_to_message
        source_payload = build_message_payload(source_message) if source_message is not None else create_match.group("body").strip()
        if not source_payload:
            await message.reply("Ответьте командой на сообщение задачи: @bot создай задачу")
            return True
        source_user = source_message.from_user if source_message is not None else message.from_user
        if source_user is None:
            await message.reply("Не удалось определить автора сообщения задачи")
            return True
        source_message_id = source_message.message_id if source_message is not None else message.message_id
        source_parse_result = parser.parse(source_payload, is_reply=False)
        with session_factory() as session:
            task_service.get_or_create_chat(
                session,
                telegram_chat_id=message.chat.id,
                title=resolve_chat_title(message.chat),
                username=message.chat.username,
            )
            task_service.get_or_create_user(
                session,
                telegram_user_id=source_user.id,
                username=source_user.username,
            )
            result = task_service.create_task_from_message(
                session,
                parse_result=source_parse_result,
                chat_id=message.chat.id,
                message_id=source_message_id,
                sender_telegram_id=source_user.id,
                sender_username=source_user.username,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await message.reply(result.message)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        logging.info(
            "TASK directive action=%s task_id=%s command=create",
            result.action,
            result.task.id if result.task is not None else None,
        )
        return True

    delete_match = TASK_DELETE_RE.match(directive_text)
    if delete_match:
        with session_factory() as session:
            task = resolve_directive_task(
                session,
                task_service,
                chat_id=message.chat.id,
                reply_message_id=reply_message_id,
                task_key=task_key,
                include_archived=True,
            )
            task_id = task.id if task is not None else None
            result = task_service.manual_archive_or_delete_task(session, task=task)
            session.commit()
        if task_id is not None:
            event_type = "task_deleted" if result.action == "deleted" else "task_changed"
            await broadcaster.publish({"type": event_type, "task_id": task_id})
        await message.reply(result.message)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        logging.info("TASK directive action=%s task_id=%s command=delete", result.action, task_id)
        return True

    clear_app_match = APP_CLEAR_RE.match(directive_text)
    if clear_app_match:
        with session_factory() as session:
            task = resolve_directive_task(
                session,
                task_service,
                chat_id=message.chat.id,
                reply_message_id=reply_message_id,
                task_key=task_key,
            )
            result = task_service.manual_set_app_name(
                session,
                task=task,
                app_name=None,
                actor_username=actor_username,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await message.reply(result.message)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    app_match = APP_SET_RE.match(directive_text)
    if app_match:
        task_id_source = parse_result.resolved_task_id.source_value if parse_result.resolved_task_id else None
        app_name = app_name_from_directive(app_match.group("body"), task_id_source)
        if not app_name:
            await message.reply("Укажите название: @bot приложение idapp_320 QA Tracker")
            return True
        with session_factory() as session:
            task = resolve_directive_task(
                session,
                task_service,
                chat_id=message.chat.id,
                reply_message_id=reply_message_id,
                task_key=task_key,
            )
            result = task_service.manual_set_app_name(
                session,
                task=task,
                app_name=app_name,
                actor_username=actor_username,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await message.reply(result.message)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    assign_match = TASK_ASSIGN_RE.match(directive_text)
    if assign_match:
        if message.from_user is None:
            await message.reply("Не удалось определить пользователя для назначения")
            return True
        with session_factory() as session:
            task = resolve_directive_task(
                session,
                task_service,
                chat_id=message.chat.id,
                reply_message_id=reply_message_id,
                task_key=task_key,
            )
            result = task_service.manual_assign_task(
                session,
                task=task,
                assignee_telegram_id=message.from_user.id,
                assignee_username=message.from_user.username,
                message_text=directive_text,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await message.reply(result.message)
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    status = infer_manual_status(directive_text)
    if status is not None and message.reply_to_message is not None:
        with session_factory() as session:
            task = task_service.find_task_by_message_reference(
                session,
                chat_id=message.chat.id,
                message_id=message.reply_to_message.message_id,
            )
            result = task_service.manual_set_task_status(
                session,
                task=task,
                status=status,
                actor_username=actor_username,
                message_text=directive_text,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    if status is not None and parse_result.resolved_task_id is not None:
        with session_factory() as session:
            result = task_service.manual_set_status(
                session,
                task_key=parse_result.resolved_task_id.canonical_task_key,
                status=status,
                actor_username=actor_username,
                message_text=directive_text,
            )
            session.commit()
        if result.task is not None:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    await message.reply("Не понял команду. Напишите @bot правила, чтобы увидеть поддерживаемые форматы.")
    return True


def reaction_for_handled_message(action: str, payload: str) -> tuple[str, ...] | None:
    if action == "created":
        return REACTION_NEW_TASK
    if action == "done":
        return REACTION_DONE
    if action in {"updated", "duplicate"}:
        return REACTION_UPDATE
    if action != "logged_reply":
        return None

    event_type = TaskService.classify_reply_event_type(payload)
    if event_type == TaskEventType.REPORT:
        return REACTION_REPORT
    if event_type == TaskEventType.REVIEW:
        return REACTION_REVIEW
    if event_type == TaskEventType.UPDATED:
        return REACTION_UPDATE
    return REACTION_HISTORY


def create_messages_router(
    session_factory: sessionmaker,
    parser: MessageParser,
    task_service: TaskService,
    report_service: ReportService,
    broadcaster: LiveUpdateBroadcaster,
    bot_username: str | None,
) -> Router:
    router = Router(name="messages")

    @router.message()
    async def text_message_handler(message: Message, bot: Bot) -> None:
        if message.from_user is None:
            return
        payload = build_message_payload(message)
        if payload is None:
            return
        if (message.text or message.caption or "").startswith("/"):
            return

        if await handle_bot_directive(
            bot=bot,
            message=message,
            payload=payload,
            bot_username=bot_username,
            parser=parser,
            task_service=task_service,
            report_service=report_service,
            session_factory=session_factory,
            broadcaster=broadcaster,
        ):
            return

        parse_result = parser.parse(payload, is_reply=message.reply_to_message is not None)

        with session_factory() as session:
            task_service.get_or_create_chat(
                session,
                telegram_chat_id=message.chat.id,
                title=resolve_chat_title(message.chat),
                username=message.chat.username,
            )
            task_service.get_or_create_user(
                session,
                telegram_user_id=message.from_user.id,
                username=message.from_user.username,
            )
            result = task_service.handle_parse_result(
                session,
                parse_result=parse_result,
                chat_id=message.chat.id,
                message_id=message.message_id,
                sender_telegram_id=message.from_user.id,
                sender_username=message.from_user.username,
                reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
            )
            session.commit()

        logging.info(
            "TASK flow action=%s task_id=%s chat_id=%s message_id=%s intent=%s confidence=%.2f",
            result.action,
            result.task.id if result.task is not None else None,
            message.chat.id,
            message.message_id,
            parse_result.classification.intent.value,
            parse_result.classification.confidence,
        )

        if result.task is not None and result.action in {"created", "updated", "done", "duplicate", "logged_reply"}:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})

        reaction = reaction_for_handled_message(result.action, payload)
        if reaction is not None:
            await set_processing_reaction(bot, message, reaction)

    @router.message_reaction()
    async def message_reaction_handler(reaction_update: MessageReactionUpdated) -> None:
        if reaction_update.user is None:
            return

        added_emoji = [
            reaction.emoji
            for reaction in reaction_update.new_reaction
            if isinstance(reaction, ReactionTypeEmoji)
        ]

        with session_factory() as session:
            task_service.get_or_create_chat(
                session,
                telegram_chat_id=reaction_update.chat.id,
                title=resolve_chat_title(reaction_update.chat),
                username=reaction_update.chat.username,
            )
            if added_emoji:
                result = task_service.assign_task_by_reaction(
                    session,
                    chat_id=reaction_update.chat.id,
                    message_id=reaction_update.message_id,
                    reactor_telegram_id=reaction_update.user.id,
                    reactor_username=reaction_update.user.username,
                    reaction_label=" ".join(added_emoji),
                )
            else:
                result = task_service.unassign_task_by_reaction(
                    session,
                    chat_id=reaction_update.chat.id,
                    message_id=reaction_update.message_id,
                    reactor_telegram_id=reaction_update.user.id,
                    reactor_username=reaction_update.user.username,
                )
            if result.action in {"assigned", "unassigned"}:
                session.commit()
                if result.task is not None:
                    await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})

    @router.my_chat_member()
    async def chat_member_handler(event: ChatMemberUpdated) -> None:
        with session_factory() as session:
            task_service.get_or_create_chat(
                session,
                telegram_chat_id=event.chat.id,
                title=resolve_chat_title(event.chat),
                username=event.chat.username,
            )
            session.commit()
        await broadcaster.publish({"type": "chats_changed"})

    return router
