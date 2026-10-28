from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from bot.db.models import (
    DoqaReportJob,
    DoqaReportJobStatus,
    QadbSyncJob,
    QadbSyncJobStatus,
    Task,
    TaskEvent,
    TaskEventType,
)
from bot.db.session import init_db
from bot.services.doqa_report import DoqaReportEmptyError, DoqaReportResult
from bot.services.doqa_report.queue import DoqaReportQueue
from bot.services.qadb_sync import QadbSyncQueue
from bot.services.task_service import TaskService


class FakeBot:
    def __init__(self, document_outcomes: list[Exception | None] | None = None) -> None:
        self.reactions: list[tuple[int, int, str]] = []
        self.documents: list[dict] = []
        self.document_attempts: list[dict] = []
        self.messages: list[dict] = []
        self._message_id = 900
        self.document_outcomes = document_outcomes or [None]

    async def set_message_reaction(self, *, chat_id, message_id, reaction):
        self.reactions.append((chat_id, message_id, reaction[0].emoji))

    async def send_document(self, **kwargs):
        self.document_attempts.append(kwargs)
        index = min(len(self.document_attempts) - 1, len(self.document_outcomes) - 1)
        outcome = self.document_outcomes[index]
        if outcome is not None:
            raise outcome
        self.documents.append(kwargs)
        self._message_id += 1
        return SimpleNamespace(message_id=self._message_id)

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        self._message_id += 1
        return SimpleNamespace(message_id=self._message_id)


class FakeReportService:
    def __init__(self, archive_path: Path, outcomes: list[Exception | None]) -> None:
        self.archive_path = archive_path
        self.outcomes = outcomes
        self.calls = 0
        self.cleaned = 0

    async def create_report(self, external_id: int) -> DoqaReportResult:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if outcome is not None:
            raise outcome
        return DoqaReportResult(
            external_id=external_id,
            run_id=441,
            title=f"ID {external_id}",
            archive_path=self.archive_path,
            run_url="https://doqa.example/runs/441",
            test_count=2,
            bug_count=1,
            parsed_bug_count=1,
            parser_run=None,  # type: ignore[arg-type]
        )

    def cleanup(self, result: DoqaReportResult) -> None:
        self.cleaned += 1


class AlwaysFailIngestor:
    def __init__(self) -> None:
        self.calls = 0

    def ingest(self, archive_path: Path, project_ref: str, run_id: int):
        self.calls += 1
        raise TimeoutError("QADB is down")


class DoqaReportQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.archive = root / "report.zip"
        self.archive.write_bytes(b"PK\x03\x04")
        self.session_factory = init_db(f"sqlite:///{root / 'queue.db'}")
        self.bot = FakeBot()

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_success_is_persisted_and_duplicate_command_is_not_requeued(self) -> None:
        service = FakeReportService(self.archive, [None])
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
        )
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=10,
                target_message_id=5,
                external_id=671,
            )
            await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            await queue.enqueue(
                chat_id=1,
                command_message_id=10,
                target_message_id=5,
                external_id=671,
            )

            with self.session_factory() as session:
                count = session.scalar(select(func.count()).select_from(DoqaReportJob))
            self.assertEqual(count, 1)
            self.assertEqual(service.calls, 1)
            self.assertEqual(len(self.bot.documents), 1)
            self.assertIn((1, 10, "👌"), self.bot.reactions)
        finally:
            await queue.close()

    async def test_sent_zip_is_added_to_task_history_and_can_receive_replies(self) -> None:
        with self.session_factory() as session:
            task = Task(
                task_key="ID 671",
                task_number=671,
                task_family="ID",
                title="ID 671",
                raw_text="Задача ID 671",
                source_chat_id=1,
                source_message_id=5,
            )
            session.add(task)
            session.commit()
            task_id = task.id

        service = FakeReportService(self.archive, [None])
        task_service = TaskService()
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
            task_service=task_service,
        )
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=10,
                target_message_id=5,
                external_id=671,
            )
            completed = await self._wait_for_status(DoqaReportJobStatus.COMPLETED)

            with self.session_factory() as session:
                event = session.scalar(
                    select(TaskEvent).where(
                        TaskEvent.source_chat_id == 1,
                        TaskEvent.source_message_id == completed.sent_message_id,
                    )
                )
                resolved = task_service.find_task_by_message_reference(
                    session,
                    chat_id=1,
                    message_id=completed.sent_message_id,
                )

            self.assertIsNotNone(event)
            self.assertEqual(event.event_type, TaskEventType.REPORT)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.id, task_id)
        finally:
            await queue.close()

    async def test_transient_error_is_retried_automatically(self) -> None:
        service = FakeReportService(self.archive, [TimeoutError("temporary"), None])
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
        )
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=11,
                target_message_id=5,
                external_id=671,
            )
            job = await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            self.assertEqual(job.attempts, 2)
            self.assertEqual(service.calls, 2)
            self.assertFalse(self.bot.messages)
        finally:
            await queue.close()

    async def test_failed_job_can_be_retried_from_error_message(self) -> None:
        service = FakeReportService(
            self.archive,
            [DoqaReportEmptyError("Нет открытых багов"), None],
        )
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
        )
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=12,
                target_message_id=5,
                external_id=671,
            )
            failed = await self._wait_for_status(DoqaReportJobStatus.FAILED)
            self.assertIsNotNone(failed.error_message_id)
            job_id = queue.find_failed_job_for_error(1, failed.error_message_id)
            self.assertEqual(job_id, failed.id)

            retried = await queue.retry(failed.id, reaction_message_id=13)
            self.assertTrue(retried)
            completed = await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            self.assertEqual(completed.attempts, 1)
            self.assertEqual(service.calls, 2)
            self.assertIn((1, 13, "🫡"), self.bot.reactions)
        finally:
            await queue.close()

    async def test_processing_job_is_recovered_on_start(self) -> None:
        with self.session_factory() as session:
            session.add(
                DoqaReportJob(
                    chat_id=1,
                    command_message_id=14,
                    reaction_message_id=14,
                    target_message_id=5,
                    external_id=671,
                    status=DoqaReportJobStatus.PROCESSING,
                    attempts=1,
                    max_attempts=2,
                )
            )
            session.commit()

        service = FakeReportService(self.archive, [None])
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
        )
        await queue.start()
        try:
            completed = await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            self.assertEqual(completed.attempts, 2)
            self.assertEqual(service.calls, 1)
        finally:
            await queue.close()

    async def test_qadb_failure_does_not_block_zip_delivery(self) -> None:
        service = FakeReportService(self.archive, [None])
        ingestor = AlwaysFailIngestor()
        sync_queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            Path(self.tempdir.name) / "outbox",
            retry_delays_seconds=(1000,),
        )
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
            qadb_sync_queue=sync_queue,
        )
        await sync_queue.start()
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=15,
                target_message_id=5,
                external_id=671,
            )
            await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            sync_job = await self._wait_for_sync_status(QadbSyncJobStatus.RETRYING)

            self.assertEqual(len(self.bot.documents), 1)
            self.assertFalse(self.bot.messages)
            self.assertEqual(service.calls, 1)
            self.assertEqual(sync_job.attempts, 1)
            self.assertEqual(ingestor.calls, 1)
        finally:
            await queue.close()
            await sync_queue.close()

    async def test_telegram_retry_reuses_staged_snapshot_without_regeneration(self) -> None:
        bot = FakeBot([TimeoutError("Telegram is down"), None])
        service = FakeReportService(self.archive, [None])
        sync_queue = QadbSyncQueue(
            self.session_factory,
            AlwaysFailIngestor(),  # type: ignore[arg-type]
            Path(self.tempdir.name) / "outbox",
            retry_delays_seconds=(1000,),
        )
        queue = DoqaReportQueue(
            bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
            qadb_sync_queue=sync_queue,
        )
        await queue.start()
        try:
            await queue.enqueue(
                chat_id=1,
                command_message_id=16,
                target_message_id=5,
                external_id=671,
            )
            await self._wait_for_status(DoqaReportJobStatus.COMPLETED)

            self.assertEqual(service.calls, 1)
            self.assertEqual(service.cleaned, 1)
            self.assertEqual(len(bot.document_attempts), 2)
            first_path = Path(bot.document_attempts[0]["document"].path)
            second_path = Path(bot.document_attempts[1]["document"].path)
            self.assertEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), b"PK\x03\x04")
        finally:
            await queue.close()

    async def test_recovered_report_job_uses_existing_snapshot(self) -> None:
        with self.session_factory() as session:
            report_job = DoqaReportJob(
                chat_id=1,
                command_message_id=17,
                reaction_message_id=17,
                target_message_id=5,
                external_id=671,
                status=DoqaReportJobStatus.PROCESSING,
                attempts=1,
                max_attempts=2,
            )
            session.add(report_job)
            session.commit()
            session.refresh(report_job)
            report_job_id = report_job.id

        sync_queue = QadbSyncQueue(
            self.session_factory,
            AlwaysFailIngestor(),  # type: ignore[arg-type]
            Path(self.tempdir.name) / "outbox",
            retry_delays_seconds=(1000,),
        )
        seed_service = FakeReportService(self.archive, [None])
        seed_result = await seed_service.create_report(671)
        await sync_queue.stage(report_job_id, seed_result)
        service = FakeReportService(self.archive, [AssertionError("must not regenerate")])
        queue = DoqaReportQueue(
            self.bot,  # type: ignore[arg-type]
            self.session_factory,
            service,  # type: ignore[arg-type]
            retry_delays_seconds=(0,),
            qadb_sync_queue=sync_queue,
        )

        await queue.start()
        try:
            await self._wait_for_status(DoqaReportJobStatus.COMPLETED)
            self.assertEqual(service.calls, 0)
            self.assertEqual(len(self.bot.documents), 1)
        finally:
            await queue.close()

    async def _wait_for_status(self, status: DoqaReportJobStatus) -> DoqaReportJob:
        for _ in range(100):
            with self.session_factory() as session:
                job = session.scalar(select(DoqaReportJob).order_by(DoqaReportJob.id.desc()))
                if job is not None and job.status == status:
                    return job
            await asyncio.sleep(0.02)
        self.fail(f"Job did not reach status {status}")

    async def _wait_for_sync_status(self, status: QadbSyncJobStatus) -> QadbSyncJob:
        for _ in range(100):
            with self.session_factory() as session:
                job = session.scalar(select(QadbSyncJob).order_by(QadbSyncJob.id.desc()))
                if job is not None and job.status == status:
                    return job
            await asyncio.sleep(0.02)
        self.fail(f"QADB sync job did not reach status {status}")
