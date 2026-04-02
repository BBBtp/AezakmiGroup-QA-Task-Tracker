from __future__ import annotations

from bot.db.models import Task


def format_task_list(tasks: list[Task], title: str) -> str:
    if not tasks:
        return f"{title}\nПусто"

    lines = [title]
    for task in tasks:
        assignee = "unassigned"
        if task.assignee:
            assignee = task.assignee.display_name or (
                f"@{task.assignee.username}" if task.assignee.username else f"user #{task.assignee.telegram_user_id}"
            )
        app_name = task.app_name or task.title
        lines.append(f"- {task.task_key} | {task.status.value} | {assignee} | {app_name}")
    return "\n".join(lines)
