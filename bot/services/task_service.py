from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, joinedload, selectinload

from bot.db.models import Chat, Task, TaskEvent, TaskEventType, TaskStatus, User
from bot.services.parser.schemas import Intent, ParseResult

ASSIGNEE_ALIASES = {
    "glebcore": "Глеб",
    "glebc0re": "Глеб",
    "bbbbbbtp": "Богдан",
}


@dataclass(slots=True)
class TaskActionResult:
    action: str
    task: Task | None = None
    message: str = ""


class TaskService:
    @staticmethod
    def _active_task_clause():
        return Task.is_archived.is_(False)

    def get_or_create_chat(
        self,
        session: Session,
        *,
        telegram_chat_id: int,
        title: str | None,
        username: str | None,
    ) -> Chat:
        chat = session.scalar(select(Chat).where(Chat.telegram_chat_id == telegram_chat_id))
        normalized_username = username.lower() if username else None
        if chat:
            if title and chat.title != title:
                chat.title = title
            if normalized_username and chat.username != normalized_username:
                chat.username = normalized_username
            session.flush()
            return chat

        chat = Chat(
            telegram_chat_id=telegram_chat_id,
            title=title,
            username=normalized_username,
        )
        session.add(chat)
        session.flush()
        return chat

    def get_or_create_user(
        self,
        session: Session,
        *,
        telegram_user_id: int,
        username: str | None,
    ) -> User:
        user = session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        normalized_username = username.lower() if username else None
        display_name = self.resolve_display_name(normalized_username)
        if user:
            if user.username != normalized_username:
                user.username = normalized_username
            if user.display_name != display_name:
                user.display_name = display_name
            session.flush()
            return user

        user = User(
            telegram_user_id=telegram_user_id,
            username=normalized_username,
            display_name=display_name,
        )
        session.add(user)
        session.flush()
        return user

    def find_user_by_username(self, session: Session, username: str | None) -> User | None:
        if not username:
            return None
        normalized_username = username.lstrip("@").lower()
        user = session.scalar(select(User).where(User.username == normalized_username))
        if user and user.display_name != self.resolve_display_name(normalized_username):
            user.display_name = self.resolve_display_name(normalized_username)
            session.flush()
        return user

    def find_task_by_key(self, session: Session, task_key: str, *, include_archived: bool = False) -> Task | None:
        stmt = select(Task).where(Task.task_key == task_key)
        if not include_archived:
            stmt = stmt.where(self._active_task_clause())
        return session.scalar(stmt)

    def find_task_by_message(self, session: Session, chat_id: int, message_id: int) -> Task | None:
        return session.scalar(
            select(Task).where(
                Task.source_chat_id == chat_id,
                Task.source_message_id == message_id,
                self._active_task_clause(),
            )
        )

    def find_task_by_event_message(self, session: Session, chat_id: int, message_id: int) -> Task | None:
        stmt = (
            select(Task)
            .join(TaskEvent, TaskEvent.task_id == Task.id)
            .where(
                TaskEvent.source_chat_id == chat_id,
                TaskEvent.source_message_id == message_id,
                self._active_task_clause(),
            )
            .limit(1)
        )
        return session.scalar(stmt)

    def find_task_by_message_reference(self, session: Session, chat_id: int, message_id: int) -> Task | None:
        task = self.find_task_by_message(session, chat_id, message_id)
        if task is not None:
            return task
        return self.find_task_by_event_message(session, chat_id, message_id)

    def get_last_active_task(self, session: Session, chat_id: int) -> Task | None:
        stmt: Select[tuple[Task]] = (
            select(Task)
            .where(Task.source_chat_id == chat_id, Task.status == TaskStatus.ASSIGNED, self._active_task_clause())
            .order_by(desc(Task.created_at))
            .limit(1)
        )
        return session.scalar(stmt)

    def resolve_task_for_message(
        self,
        session: Session,
        *,
        parse_result: ParseResult,
        chat_id: int,
        reply_to_message_id: int | None,
    ) -> Task | None:
        if reply_to_message_id is not None:
            task = self.find_task_by_message_reference(session, chat_id, reply_to_message_id)
            if task:
                return task

        if parse_result.resolved_task_id:
            task = self.find_task_by_key(session, parse_result.resolved_task_id.canonical_task_key)
            if task:
                return task

        return self.get_last_active_task(session, chat_id)

    def create_task_from_message(
        self,
        session: Session,
        *,
        parse_result: ParseResult,
        chat_id: int,
        message_id: int,
        sender_telegram_id: int,
        sender_username: str | None,
    ) -> TaskActionResult:
        if not parse_result.resolved_task_id:
            return TaskActionResult(action="ignored", message="Не удалось определить идентификатор задачи")

        task_key = parse_result.resolved_task_id.canonical_task_key
        existing_task = self.find_task_by_key(session, task_key, include_archived=True)
        if existing_task:
            if existing_task.is_archived:
                return TaskActionResult(
                    action="ignored",
                    task=existing_task,
                    message=f"Задача {existing_task.task_key} находится в архиве и не отслеживается",
                )
            self.populate_task_metadata(existing_task, parse_result)
            self.add_event(
                session,
                task=existing_task,
                event_type=TaskEventType.UPDATED,
                message_text=parse_result.text,
                source_chat_id=chat_id,
                source_message_id=message_id,
            )
            return TaskActionResult(
                action="duplicate",
                task=existing_task,
                message=self.format_task_message(
                    prefix=f"Задача {existing_task.task_key} уже существует, сообщение добавлено как обновление",
                    app_name=existing_task.app_name,
                ),
            )

        app_name = self.resolve_app_name(parse_result)
        title = self.compose_title(task_key, app_name) if app_name else self.build_fallback_title(parse_result.text)
        task = Task(
            task_key=task_key,
            task_number=parse_result.resolved_task_id.task_number,
            task_family=parse_result.resolved_task_id.task_family,
            app_name=app_name,
            title=title,
            raw_text=parse_result.text,
            figma_url=parse_result.entities.first_url_by_kind("figma"),
            github_url=parse_result.entities.first_url_by_kind("github"),
            archive_url=self.resolve_archive_url(parse_result),
            branch_name=parse_result.entities.branch_names[0] if parse_result.entities.branch_names else None,
            relevant_file_path=parse_result.entities.file_paths[0] if parse_result.entities.file_paths else None,
            relevant_line_number=parse_result.entities.line_numbers[0] if parse_result.entities.line_numbers else None,
            status=TaskStatus.ASSIGNED,
            assignee_user_id=None,
            source_chat_id=chat_id,
            source_message_id=message_id,
        )
        session.add(task)
        session.flush()

        self.add_event(
            session,
            task=task,
            event_type=TaskEventType.CREATED,
            message_text=parse_result.text,
            source_chat_id=chat_id,
            source_message_id=message_id,
        )
        return TaskActionResult(
            action="created",
            task=task,
            message=self.format_task_message(
                prefix=f"Задача {task.task_key} сохранена",
                app_name=task.app_name,
            ),
        )

    def add_update(
        self,
        session: Session,
        *,
        task: Task | None,
        message_text: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
    ) -> TaskActionResult:
        if task is None:
            return TaskActionResult(action="ignored", message="Не удалось понять, к какой задаче относится обновление")

        self.populate_task_metadata(task, task_parse_result(message_text))
        self.add_event(
            session,
            task=task,
            event_type=TaskEventType.UPDATED,
            message_text=message_text,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
        return TaskActionResult(
            action="updated",
            task=task,
            message=self.format_task_message(
                prefix=f"Обновление добавлено к {task.task_key}",
                app_name=task.app_name,
            ),
        )

    def mark_done(
        self,
        session: Session,
        *,
        task: Task | None,
        message_text: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
    ) -> TaskActionResult:
        if task is None:
            return TaskActionResult(action="ignored", message="Не удалось определить задачу для закрытия")

        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(timezone.utc)
        self.add_event(
            session,
            task=task,
            event_type=TaskEventType.DONE,
            message_text=message_text,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
        return TaskActionResult(
            action="done",
            task=task,
            message=self.format_task_message(
                prefix=f"Задача {task.task_key} закрыта",
                app_name=task.app_name,
            ),
        )

    def handle_parse_result(
        self,
        session: Session,
        *,
        parse_result: ParseResult,
        chat_id: int,
        message_id: int,
        sender_telegram_id: int,
        sender_username: str | None,
        reply_to_message_id: int | None,
    ) -> TaskActionResult:
        intent = parse_result.classification.intent
        confidence = parse_result.classification.confidence
        replied_task = None
        if reply_to_message_id is not None:
            replied_task = self.find_task_by_message_reference(session, chat_id, reply_to_message_id)

        if replied_task is not None:
            if intent == Intent.TASK_DONE:
                return self.mark_done(
                    session,
                    task=replied_task,
                    message_text=parse_result.text,
                    source_chat_id=chat_id,
                    source_message_id=message_id,
                )
            return self.add_reply_event(
                session,
                task=replied_task,
                message_text=parse_result.text,
                source_chat_id=chat_id,
                source_message_id=message_id,
            )

        if intent == Intent.NEW_TASK:
            if confidence < 0.6:
                return TaskActionResult(action="ignored", message="Сообщение похоже на задачу, но уверенность ниже порога")
            return self.create_task_from_message(
                session,
                parse_result=parse_result,
                chat_id=chat_id,
                message_id=message_id,
                sender_telegram_id=sender_telegram_id,
                sender_username=sender_username,
            )

        if intent == Intent.TASK_UPDATE:
            task = self.resolve_task_for_message(
                session,
                parse_result=parse_result,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
            )
            return self.add_update(
                session,
                task=task,
                message_text=parse_result.text,
                source_chat_id=chat_id,
                source_message_id=message_id,
            )

        if intent == Intent.TASK_DONE:
            task = self.resolve_task_for_message(
                session,
                parse_result=parse_result,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
            )
            return self.mark_done(
                session,
                task=task,
                message_text=parse_result.text,
                source_chat_id=chat_id,
                source_message_id=message_id,
            )

        return TaskActionResult(action="ignored", message="Сообщение не классифицировано как задача")

    def list_open_tasks(self, session: Session, *, assignee_user_id: int | None = None) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.ASSIGNED, self._active_task_clause())
            .order_by(desc(Task.created_at))
        )
        if assignee_user_id is not None:
            stmt = stmt.where(Task.assignee_user_id == assignee_user_id)
        return list(session.scalars(stmt))

    def backfill_existing_tasks(self, session: Session) -> int:
        tasks = list(
            session.scalars(select(Task).options(joinedload(Task.assignee), selectinload(Task.events)))
        )
        updated = 0
        for task in tasks:
            before = (
                task.app_name,
                task.figma_url,
                task.github_url,
                task.archive_url,
                task.branch_name,
                task.relevant_file_path,
                task.relevant_line_number,
                task.title,
                task.assignee_user_id,
            )
            self.populate_task_metadata(task, task_parse_result(task.raw_text))
            self.clear_legacy_assignee_if_needed(task)
            if before != (
                task.app_name,
                task.figma_url,
                task.github_url,
                task.archive_url,
                task.branch_name,
                task.relevant_file_path,
                task.relevant_line_number,
                task.title,
                task.assignee_user_id,
            ):
                updated += 1
        if updated:
            session.flush()
        return updated

    def manual_done(self, session: Session, task_key: str) -> TaskActionResult:
        task = self.find_task_by_key(session, task_key.lower())
        return self.mark_done(session, task=task, message_text=f"Manual close via /done {task_key}")

    def archive_task(self, session: Session, task_id: int) -> TaskActionResult:
        task = session.scalar(select(Task).where(Task.id == task_id))
        if task is None:
            return TaskActionResult(action="ignored", message="Задача не найдена")
        if task.is_archived:
            return TaskActionResult(action="ignored", task=task, message="Задача уже в архиве")

        task.is_archived = True
        task.archived_at = datetime.now(timezone.utc)
        session.flush()
        return TaskActionResult(action="archived", task=task, message=f"Задача {task.task_key} перемещена в архив")

    def restore_task(self, session: Session, task_id: int) -> TaskActionResult:
        task = session.scalar(select(Task).where(Task.id == task_id))
        if task is None:
            return TaskActionResult(action="ignored", message="Задача не найдена")
        if not task.is_archived:
            return TaskActionResult(action="ignored", task=task, message="Задача уже активна")

        task.is_archived = False
        task.archived_at = None
        session.flush()
        return TaskActionResult(action="restored", task=task, message=f"Задача {task.task_key} возвращена из архива")

    def delete_task_permanently(self, session: Session, task_id: int) -> TaskActionResult:
        task = session.scalar(select(Task).where(Task.id == task_id))
        if task is None:
            return TaskActionResult(action="ignored", message="Задача не найдена")

        task_key = task.task_key
        session.delete(task)
        session.flush()
        return TaskActionResult(action="deleted", message=f"Задача {task_key} удалена навсегда")

    def add_reply_event(
        self,
        session: Session,
        *,
        task: Task,
        message_text: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
    ) -> TaskActionResult:
        parse_result = task_parse_result(message_text)
        self.populate_task_metadata(task, parse_result)
        event_type = self.classify_reply_event_type(message_text)
        self.add_event(
            session,
            task=task,
            event_type=event_type,
            message_text=message_text,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
        return TaskActionResult(action="logged_reply", task=task, message=f"Ответ сохранён для {task.task_key}")

    def populate_task_metadata(self, task: Task, parse_result: ParseResult) -> None:
        if not task.app_name:
            task.app_name = self.resolve_app_name(parse_result)
        if not task.figma_url:
            task.figma_url = parse_result.entities.first_url_by_kind("figma")
        if not task.github_url:
            task.github_url = parse_result.entities.first_url_by_kind("github")
        if not task.archive_url:
            task.archive_url = self.resolve_archive_url(parse_result)
        if not task.branch_name and parse_result.entities.branch_names:
            task.branch_name = parse_result.entities.branch_names[0]
        if not task.relevant_file_path and parse_result.entities.file_paths:
            task.relevant_file_path = parse_result.entities.file_paths[0]
        if not task.relevant_line_number and parse_result.entities.line_numbers:
            task.relevant_line_number = parse_result.entities.line_numbers[0]
        if task.app_name:
            task.title = self.compose_title(task.task_key, task.app_name)

    def assign_task_by_reaction(
        self,
        session: Session,
        *,
        chat_id: int,
        message_id: int,
        reactor_telegram_id: int,
        reactor_username: str | None,
        reaction_label: str,
    ) -> TaskActionResult:
        if not self.is_known_tester(reactor_username):
            return TaskActionResult(action="ignored", message="Реакция не от тестировщика")

        task = self.find_task_by_message(session, chat_id, message_id)
        if task is None:
            return TaskActionResult(action="ignored", message="Для реакции не найдена связанная задача")

        user = self.get_or_create_user(
            session,
            telegram_user_id=reactor_telegram_id,
            username=reactor_username,
        )
        if task.assignee_user_id == user.id:
            return TaskActionResult(action="ignored", task=task, message="Исполнитель уже назначен")

        task.assignee_user_id = user.id
        self.add_event(
            session,
            task=task,
            event_type=TaskEventType.UPDATED,
            message_text=f"Исполнитель назначен реакцией {reaction_label} от {self.format_assignee(user)}",
        )
        return TaskActionResult(action="assigned", task=task, message=f"{task.task_key} -> {self.format_assignee(user)}")

    def unassign_task_by_reaction(
        self,
        session: Session,
        *,
        chat_id: int,
        message_id: int,
        reactor_telegram_id: int,
        reactor_username: str | None,
    ) -> TaskActionResult:
        if not self.is_known_tester(reactor_username):
            return TaskActionResult(action="ignored", message="Реакция не от тестировщика")

        task = self.find_task_by_message(session, chat_id, message_id)
        if task is None:
            return TaskActionResult(action="ignored", message="Для реакции не найдена связанная задача")

        user = session.scalar(select(User).where(User.telegram_user_id == reactor_telegram_id))
        if user is None:
            return TaskActionResult(action="ignored", task=task, message="Пользователь реакции не найден")

        if task.assignee_user_id != user.id:
            return TaskActionResult(action="ignored", task=task, message="Исполнитель уже назначен другому тестировщику")

        task.assignee_user_id = None
        self.add_event(
            session,
            task=task,
            event_type=TaskEventType.UPDATED,
            message_text=f"Исполнитель снят после удаления реакции от {self.format_assignee(user)}",
        )
        return TaskActionResult(action="unassigned", task=task, message=f"{task.task_key} -> без исполнителя")

    @staticmethod
    def add_event(
        session: Session,
        *,
        task: Task,
        event_type: TaskEventType,
        message_text: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
    ) -> None:
        session.add(
            TaskEvent(
                task_id=task.id,
                event_type=event_type,
                message_text=message_text,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
            )
        )
        session.flush()

    def build_fallback_title(self, text: str) -> str:
        compact = " ".join(text.split())
        return compact[:252] + "..." if len(compact) > 255 else compact

    @staticmethod
    def resolve_display_name(username: str | None) -> str | None:
        if not username:
            return None
        return ASSIGNEE_ALIASES.get(username.lower(), f"@{username.lower()}")

    @staticmethod
    def is_known_tester(username: str | None) -> bool:
        if not username:
            return False
        return username.lower() in ASSIGNEE_ALIASES

    def resolve_app_name(self, parse_result: ParseResult) -> str | None:
        if parse_result.entities.app_name_candidates:
            return parse_result.entities.app_name_candidates[0]
        return None

    @staticmethod
    def resolve_archive_url(parse_result: ParseResult) -> str | None:
        for url in parse_result.entities.urls:
            if url.url.lower().endswith((".zip", ".rar", ".7z", ".tar.gz")):
                return url.url
        return None

    @staticmethod
    def compose_title(task_key: str, app_name: str) -> str:
        return f"{task_key} | {app_name}"[:255]

    @staticmethod
    def format_task_message(*, prefix: str, app_name: str | None) -> str:
        if not app_name:
            return prefix
        return f"{prefix}\nПриложение: {app_name}"

    @staticmethod
    def format_assignee(assignee: User | None) -> str:
        if assignee is None:
            return "не указан"
        if assignee.display_name:
            return assignee.display_name
        if assignee.username:
            return f"@{assignee.username}"
        return f"user #{assignee.telegram_user_id}"

    def clear_legacy_assignee_if_needed(self, task: Task) -> None:
        if task.assignee is None:
            return
        has_reaction_assignment = any(
            "Исполнитель назначен реакцией" in event.message_text for event in task.events
        )
        if has_reaction_assignment:
            return
        if task.assignee.display_name == "Арина":
            task.assignee_user_id = None

    @staticmethod
    def classify_reply_event_type(message_text: str) -> TaskEventType:
        lowered = message_text.lower()
        if any(token in lowered for token in ("отчет", "отчёт", "вот отчет", "вот отчёт", "ссылка на отчет", "ссылка на отчёт")):
            return TaskEventType.REPORT
        if any(token in lowered for token in ("не исправлено", "новые пункты", "новый баг", "новые баги", "добавил новые пункты", "указал")):
            return TaskEventType.REVIEW
        if "?" in message_text or any(
            token in lowered for token in ("можешь", "можете", "почему", "как", "посмотри", "глянь", "уточни")
        ):
            return TaskEventType.QUESTION
        if any(
            token in lowered
            for token in (
                "обновили",
                "поправили",
                "перезалил",
                "перезалили",
                "исправил",
                "исправили",
                "фикс",
                "fix",
                "fixed",
                "залил фикс",
                "[photo",
                "[video",
                "[animation",
            )
        ):
            return TaskEventType.UPDATED
        return TaskEventType.COMMENT


def task_parse_entities(text: str):
    from bot.services.parser.extractors import extract_entities

    return extract_entities(text)


def task_parse_result(text: str) -> ParseResult:
    from bot.services.parser.classifier import ClassificationResult, Intent

    return ParseResult(
        text=text,
        entities=task_parse_entities(text),
        resolved_task_id=None,
        classification=ClassificationResult(intent=Intent.UNKNOWN, confidence=0.0),
    )
