from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Chat, ChatMemberUpdated, Message, MessageReactionUpdated, ReactionTypeEmoji
from sqlalchemy.orm import sessionmaker

from bot.live_updates import LiveUpdateBroadcaster
from bot.services.parser.resolver import MessageParser
from bot.services.task_service import TaskService


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


def create_messages_router(
    session_factory: sessionmaker,
    parser: MessageParser,
    task_service: TaskService,
    broadcaster: LiveUpdateBroadcaster,
) -> Router:
    router = Router(name="messages")

    @router.message()
    async def text_message_handler(message: Message) -> None:
        if message.from_user is None:
            return
        payload = build_message_payload(message)
        if payload is None:
            return
        if (message.text or message.caption or "").startswith("/"):
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

        if result.task is not None and result.action in {"created", "updated", "done", "duplicate", "logged_reply"}:
            await broadcaster.publish({"type": "task_changed", "task_id": result.task.id})

        if result.action in {"created", "updated", "done", "duplicate"}:
            await message.reply(result.message)

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
