from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from bot.db.models import DoqaReportJob, DoqaReportJobStatus
from bot.db.session import init_db
from bot.services.doqa_report import DoqaReportEmptyError, DoqaReportResult
from bot.services.doqa_report.queue import DoqaReportQueue


class FakeBot:
    def __init__(self) -> None:
        self.reactions: list[tuple[int, int, str]] = []
        self.documents: list[dict] = []
        self.messages: list[dict] = []
        self._message_id = 900

    async def set_message_reaction(self, *, chat_id, message_id, reaction):
        self.reactions.append((chat_id, message_id, reaction[0].emoji))

    async def send_document(self, **kwargs):
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

    async def _wait_for_status(self, status: DoqaReportJobStatus) -> DoqaReportJob:
        for _ in range(100):
            with self.session_factory() as session:
                job = session.scalar(select(DoqaReportJob).order_by(DoqaReportJob.id.desc()))
                if job is not None and job.status == status:
                    return job
            await asyncio.sleep(0.02)
        self.fail(f"Job did not reach status {status}")
