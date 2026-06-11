from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from bot.db.models import Task, TaskStatus

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
STATUS_LABELS = {
    TaskStatus.ASSIGNED: "в работе",
    TaskStatus.DONE: "завершено",
    TaskStatus.PAUSED: "пауза",
}
MONTHS_RU_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


class ReportService:
    def completed_tasks_for_last_days(self, session: Session, days: int) -> list[Task]:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.DONE, Task.completed_at.is_not(None), Task.completed_at >= threshold)
            .order_by(desc(Task.completed_at))
        )
        return list(session.scalars(stmt))

    def tasks_for_period(
        self,
        session: Session,
        date_from: datetime,
        date_to: datetime,
        *,
        chat_id: int | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .options(joinedload(Task.assignee))
            .where(
                Task.is_archived.is_(False),
                Task.created_at >= date_from,
                Task.created_at <= date_to,
            )
            .order_by(desc(Task.created_at))
        )
        if chat_id is not None:
            stmt = stmt.where(Task.source_chat_id == chat_id)
        return list(session.scalars(stmt))

    @staticmethod
    def format_report(tasks: list[Task], days: int) -> str:
        if not tasks:
            return f"За последние {days} дн. завершённых задач нет"

        lines = [f"Завершённые задачи за {days} дн.:"]
        for task in tasks:
            completed_at = task.completed_at.isoformat(timespec="minutes") if task.completed_at else "n/a"
            lines.append(f"- {task.task_key} | {task.title} | {completed_at}")
        return "\n".join(lines)

    @staticmethod
    def format_status_report(tasks: list[Task], date_from: datetime, date_to: datetime) -> str:
        period = format_period(date_from, date_to)
        if not tasks:
            return f"За период {period} задач нет"

        done = [task for task in tasks if task.status == TaskStatus.DONE]
        assigned = [task for task in tasks if task.status == TaskStatus.ASSIGNED]
        paused = [task for task in tasks if task.status == TaskStatus.PAUSED]

        lines = [
            f"Статус задач за период {period}",
            "",
            f"Всего: {len(tasks)}",
            f"В работе: {len(assigned)}",
            f"Завершено: {len(done)}",
            f"Пауза: {len(paused)}",
            "",
            "Задачи:",
        ]
        for task in tasks[:30]:
            assignee = task.assignee.display_name if task.assignee and task.assignee.display_name else "не назначен"
            app_name = task.app_name or task.title
            status = STATUS_LABELS.get(task.status, task.status.value)
            lines.append(f"- {task.task_key}: {status}, {assignee}, {app_name}")
        if len(tasks) > 30:
            lines.append(f"...и еще {len(tasks) - 30}")
        return "\n".join(lines)


def format_russian_date(value: datetime, *, include_year: bool) -> str:
    local_date = value.astimezone(MOSCOW_TZ).date()
    base = f"{local_date.day} {MONTHS_RU_GENITIVE[local_date.month]}"
    return f"{base} {local_date.year} года" if include_year else base


def format_period(date_from: datetime, date_to: datetime) -> str:
    start = date_from.astimezone(MOSCOW_TZ).date()
    end = date_to.astimezone(MOSCOW_TZ).date()
    include_start_year = start.year != end.year
    start_text = format_russian_date(date_from, include_year=include_start_year)
    end_text = format_russian_date(date_to, include_year=True)
    return f"с {start_text} по {end_text}"
