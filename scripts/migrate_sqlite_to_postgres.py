from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session, sessionmaker, selectinload

from bot.db.models import Base, Chat, Task, TaskEvent, User


SOURCE_URL = "sqlite:///bot.db"
TARGET_URL = "postgresql+psycopg://task_tracker:task_tracker@127.0.0.1:5433/task_tracker"


def main() -> None:
    if not Path("bot.db").exists():
        raise FileNotFoundError("bot.db not found in project root")

    source_engine = create_engine(SOURCE_URL, future=True, connect_args={"check_same_thread": False})
    target_engine = create_engine(TARGET_URL, future=True)
    Base.metadata.create_all(target_engine)

    source_session_factory = sessionmaker(bind=source_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    target_session_factory = sessionmaker(bind=target_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with source_session_factory() as source, target_session_factory() as target:
        users = list(source.query(User).order_by(User.id))
        chats = list(source.query(Chat).order_by(Chat.id))
        tasks = list(
            source.query(Task)
            .options(selectinload(Task.events))
            .order_by(Task.id)
        )

        target.execute(delete(TaskEvent))
        target.execute(delete(Task))
        target.execute(delete(User))
        target.execute(delete(Chat))
        target.flush()

        for user in users:
          target.add(
              User(
                  id=user.id,
                  telegram_user_id=user.telegram_user_id,
                  username=user.username,
                  display_name=user.display_name,
              )
          )

        for chat in chats:
          target.add(
              Chat(
                  id=chat.id,
                  telegram_chat_id=chat.telegram_chat_id,
                  title=chat.title,
                  username=chat.username,
              )
          )

        for task in tasks:
            target.add(
                Task(
                    id=task.id,
                    task_key=task.task_key,
                    task_number=task.task_number,
                    task_family=task.task_family,
                    app_name=task.app_name,
                    title=task.title,
                    raw_text=task.raw_text,
                    figma_url=task.figma_url,
                    github_url=task.github_url,
                    archive_url=task.archive_url,
                    branch_name=task.branch_name,
                    relevant_file_path=task.relevant_file_path,
                    relevant_line_number=task.relevant_line_number,
                    status=task.status,
                    assignee_user_id=task.assignee_user_id,
                    source_chat_id=task.source_chat_id,
                    source_message_id=task.source_message_id,
                    is_archived=task.is_archived,
                    archived_at=task.archived_at,
                    created_at=task.created_at,
                    completed_at=task.completed_at,
                )
            )

        for task in tasks:
            for event in task.events:
                target.add(
                    TaskEvent(
                        id=event.id,
                        task_id=event.task_id,
                        event_type=event.event_type,
                        message_text=event.message_text,
                        source_chat_id=event.source_chat_id,
                        source_message_id=event.source_message_id,
                        created_at=event.created_at,
                    )
                )

        target.commit()

        reset_sequence(target, "users", "id")
        reset_sequence(target, "chats", "id")
        reset_sequence(target, "tasks", "id")
        reset_sequence(target, "task_events", "id")
        target.commit()

        print(f"users={len(users)}")
        print(f"chats={len(chats)}")
        print(f"tasks={len(tasks)}")
        print(f"task_events={sum(len(task.events) for task in tasks)}")


def reset_sequence(session: Session, table_name: str, column_name: str) -> None:
    session.execute(
        text(
            """
            SELECT setval(
              pg_get_serial_sequence(:table_name, :column_name),
              COALESCE((SELECT MAX(id) FROM """ + table_name + """), 1),
              true
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    )


if __name__ == "__main__":
    main()
