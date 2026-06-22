from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bot.db.models import Task, TaskStatus
from bot.db.session import init_db
from bot.handlers.messages import TASK_CREATE_RE, app_name_from_directive, parse_period, resolve_directive_task
from bot.services.parser.resolver import MessageParser
from bot.services.parser.schemas import Intent
from bot.services.report_service import ReportService
from bot.services.task_service import TaskService


class TaskDirectiveTests(unittest.TestCase):
    def test_shared_month_period_uses_both_days(self) -> None:
        period = parse_period("дай статус задач с 15 по 17 июня 2026")

        self.assertIsNotNone(period)
        date_from, date_to = period
        self.assertEqual(date_from, datetime(2026, 6, 14, 21, tzinfo=timezone.utc))
        self.assertEqual(date_to, datetime(2026, 6, 17, 20, 59, 59, 999999, tzinfo=timezone.utc))

    def test_app_name_removes_task_id(self) -> None:
        self.assertEqual(app_name_from_directive("idApp 320 QA Tracker", "idApp 320"), "QA Tracker")

    def test_short_task_with_mentions_crosses_create_threshold(self) -> None:
        parsed = MessageParser().parse("@diiaanag @glebc0re @bbbbbbtp idApp 316 T3: AI Avatar", is_reply=False)

        self.assertEqual(parsed.classification.intent, Intent.NEW_TASK)
        self.assertGreaterEqual(parsed.classification.confidence, 0.6)
        self.assertEqual(parsed.resolved_task_id.canonical_task_key, "idapp_316")

    def test_manual_create_command_matches_only_task_wording(self) -> None:
        self.assertIsNotNone(TASK_CREATE_RE.match("создай задачу"))
        self.assertIsNotNone(TASK_CREATE_RE.match("отследи задачу"))
        self.assertIsNone(TASK_CREATE_RE.match("добавь приложение idapp_316 AI Avatar"))

    def test_new_task_context_wins_over_update_phrase_outside_reply(self) -> None:
        parsed = MessageParser().parse("@diiaanag idApp 317 залил билд на тесты", is_reply=False)

        self.assertEqual(parsed.classification.intent, Intent.NEW_TASK)

    def test_rich_report_builds_escaped_tables(self) -> None:
        task = Task(
            task_key="idapp_320",
            task_number=320,
            task_family="idapp",
            app_name="QA <Tracker>",
            title="idapp_320 - QA <Tracker>",
            raw_text="test",
            status=TaskStatus.ASSIGNED,
            source_chat_id=1,
            source_message_id=1,
            is_archived=False,
        )

        html = ReportService.format_status_report_rich_html(
            [task],
            datetime(2026, 6, 14, 21, tzinfo=timezone.utc),
            datetime(2026, 6, 17, 20, 59, 59, tzinfo=timezone.utc),
        )

        self.assertIn("<table bordered striped>", html)
        self.assertIn("QA &lt;Tracker&gt;", html)
        self.assertNotIn("QA <Tracker>", html)

    def test_delete_archives_then_deletes_permanently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'test.db'}"
            session_factory = init_db(database_url)
            service = TaskService()

            with session_factory() as session:
                task = Task(
                    task_key="idapp_320",
                    task_number=320,
                    task_family="idapp",
                    app_name="QA Tracker",
                    title="idapp_320 - QA Tracker",
                    raw_text="test",
                    status=TaskStatus.ASSIGNED,
                    source_chat_id=1,
                    source_message_id=1,
                    is_archived=False,
                )
                session.add(task)
                session.commit()

                archived = service.manual_archive_or_delete_task(session, task=task)
                session.commit()
                self.assertEqual(archived.action, "archived")
                self.assertTrue(task.is_archived)

                archived_task = service.find_task_by_key(session, "idapp_320", include_archived=True)
                deleted = service.manual_archive_or_delete_task(session, task=archived_task)
                session.commit()
                self.assertEqual(deleted.action, "deleted")
                self.assertIsNone(service.find_task_by_key(session, "idapp_320", include_archived=True))

    def test_manual_assign_task_sets_assignee(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'test.db'}"
            session_factory = init_db(database_url)
            service = TaskService()

            with session_factory() as session:
                task = Task(
                    task_key="idapp_316",
                    task_number=316,
                    task_family="idapp",
                    app_name="AI Avatar",
                    title="idapp_316 - AI Avatar",
                    raw_text="test",
                    status=TaskStatus.ASSIGNED,
                    source_chat_id=1,
                    source_message_id=10,
                    is_archived=False,
                )
                session.add(task)
                session.commit()

                result = service.manual_assign_task(
                    session,
                    task=task,
                    assignee_telegram_id=123,
                    assignee_username="bbbbbbtp",
                    message_text="взять",
                )
                session.commit()

                self.assertEqual(result.action, "assigned")
                self.assertIsNotNone(task.assignee_user_id)
                self.assertEqual(task.assignee.display_name, "Богдан")

    def test_manual_create_bypasses_classifier_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'test.db'}"
            session_factory = init_db(database_url)
            service = TaskService()
            parsed = MessageParser().parse("idApp 999", is_reply=False)

            with session_factory() as session:
                result = service.create_task_from_message(
                    session,
                    parse_result=parsed,
                    chat_id=1,
                    message_id=10,
                    sender_telegram_id=123,
                    sender_username="bbbbbbtp",
                )
                session.commit()

                self.assertEqual(result.action, "created")
                self.assertEqual(result.task.task_key, "idapp_999")

    def test_resolve_task_falls_back_to_id_when_reply_misses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'test.db'}"
            session_factory = init_db(database_url)
            service = TaskService()

            with session_factory() as session:
                task = Task(
                    task_key="idapp_316",
                    task_number=316,
                    task_family="idapp",
                    app_name=None,
                    title="idapp_316",
                    raw_text="test",
                    status=TaskStatus.ASSIGNED,
                    source_chat_id=1,
                    source_message_id=10,
                    is_archived=False,
                )
                session.add(task)
                session.commit()

                resolved = resolve_directive_task(
                    session,
                    service,
                    chat_id=1,
                    reply_message_id=999,
                    task_key="idapp_316",
                )

                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.task_key, "idapp_316")


if __name__ == "__main__":
    unittest.main()
