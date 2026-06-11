from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.types import Chat, ChatMemberUpdated, Message, MessageReactionUpdated, ReactionTypeEmoji
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

7. Сводка по чату
@bot дай статус задач с 6 июня по 30 июня

Сводка показывает только задачи текущего чата.

8. Реакции бота
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
            await message.reply(report_service.format_status_report(tasks, date_from, date_to))
        await set_processing_reaction(bot, message, REACTION_COMMAND)
        return True

    status = infer_manual_status(directive_text)
    parse_result = parser.parse(directive_text, is_reply=False)
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
                actor_username=message.from_user.username if message.from_user else None,
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
                actor_username=message.from_user.username if message.from_user else None,
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
