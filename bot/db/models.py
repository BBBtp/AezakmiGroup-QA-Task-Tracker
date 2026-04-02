from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus(str, Enum):
    ASSIGNED = "assigned"
    DONE = "done"
    PAUSED = "paused"


class TaskEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    DONE = "done"
    REPORT = "report"
    REVIEW = "review"
    QUESTION = "question"
    COMMENT = "comment"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    assigned_tasks: Mapped[list["Task"]] = relationship(back_populates="assignee")


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_key: Mapped[str] = mapped_column(String(128), index=True)
    task_number: Mapped[int] = mapped_column(Integer, index=True)
    task_family: Mapped[str] = mapped_column(String(64), index=True)
    app_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text)
    figma_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relevant_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    relevant_line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus),
        default=TaskStatus.ASSIGNED,
        index=True,
    )
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_message_id: Mapped[int] = mapped_column(index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignee: Mapped[User | None] = relationship(back_populates="assigned_tasks")
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskEvent.created_at",
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    event_type: Mapped[TaskEventType] = mapped_column(SqlEnum(TaskEventType), index=True)
    message_text: Mapped[str] = mapped_column(Text)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="events")
