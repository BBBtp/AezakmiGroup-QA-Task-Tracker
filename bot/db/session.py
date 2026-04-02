from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from bot.db.models import Base


def _ensure_sqlite_columns(engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    required_columns = {
        "users": {
            "display_name": "ALTER TABLE users ADD COLUMN display_name VARCHAR(128)",
        },
        "tasks": {
            "app_name": "ALTER TABLE tasks ADD COLUMN app_name VARCHAR(255)",
            "figma_url": "ALTER TABLE tasks ADD COLUMN figma_url TEXT",
            "github_url": "ALTER TABLE tasks ADD COLUMN github_url TEXT",
            "archive_url": "ALTER TABLE tasks ADD COLUMN archive_url TEXT",
            "branch_name": "ALTER TABLE tasks ADD COLUMN branch_name VARCHAR(255)",
            "relevant_file_path": "ALTER TABLE tasks ADD COLUMN relevant_file_path VARCHAR(512)",
            "relevant_line_number": "ALTER TABLE tasks ADD COLUMN relevant_line_number INTEGER",
            "is_archived": "ALTER TABLE tasks ADD COLUMN is_archived BOOLEAN DEFAULT 0",
            "archived_at": "ALTER TABLE tasks ADD COLUMN archived_at DATETIME",
        },
        "task_events": {
            "source_chat_id": "ALTER TABLE task_events ADD COLUMN source_chat_id INTEGER",
            "source_message_id": "ALTER TABLE task_events ADD COLUMN source_message_id INTEGER",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in required_columns.items():
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    connection.execute(text(ddl))


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
