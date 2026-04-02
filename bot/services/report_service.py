from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from bot.db.models import Task, TaskStatus


class ReportService:
    def completed_tasks_for_last_days(self, session: Session, days: int) -> list[Task]:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.DONE, Task.completed_at.is_not(None), Task.completed_at >= threshold)
            .order_by(desc(Task.completed_at))
        )
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
