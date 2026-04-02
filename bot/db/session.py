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


def _ensure_postgres_task_key_non_unique(engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        constraint_names = connection.execute(
            text(
                """
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = con.connamespace
                WHERE rel.relname = 'tasks'
                  AND nsp.nspname = current_schema()
                  AND con.contype = 'u'
                  AND pg_get_constraintdef(con.oid) ILIKE '%(task_key)%'
                """
            )
        ).scalars().all()

        for constraint_name in constraint_names:
            connection.execute(text(f'ALTER TABLE tasks DROP CONSTRAINT "{constraint_name}"'))


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, echo=False, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)
    _ensure_postgres_task_key_non_unique(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
