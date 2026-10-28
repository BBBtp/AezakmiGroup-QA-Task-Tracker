from __future__ import annotations

import asyncio
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from bot.config import load_settings
from bot.db.models import (
    DoqaReportJob,
    DoqaReportJobStatus,
    QadbSyncJob,
    QadbSyncJobStatus,
)
from bot.db.session import init_db
from bot.services.doqa_report import DoqaReportResult
from bot.services.qadb_sync import QadbSyncQueue, SnapshotIntegrityError


class QadbSyncPersistenceTests(unittest.TestCase):
    def test_sync_job_is_unique_per_report_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_factory = init_db(f"sqlite:///{Path(directory) / 'queue.db'}")
            with session_factory() as session:
                report_job = DoqaReportJob(
                    chat_id=1,
                    command_message_id=10,
                    reaction_message_id=10,
                    target_message_id=5,
                    external_id=671,
                )
                session.add(report_job)
                session.commit()
                session.refresh(report_job)

                session.add(self._sync_job(report_job.id, "/tmp/first.zip"))
                session.commit()
                session.add(self._sync_job(report_job.id, "/tmp/second.zip"))
                with self.assertRaises(IntegrityError):
                    session.commit()

    def test_qadb_outbox_settings_have_durable_defaults(self) -> None:
        environment = {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch("bot.config.load_dotenv"), patch.dict("os.environ", environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.qadb_outbox_dir, Path("task_tracker_data/qadb_outbox"))
        self.assertEqual(settings.qadb_sync_retry_delays_seconds, (15, 60, 300, 900, 3600))

    def test_qadb_retry_delays_are_configurable_and_positive(self) -> None:
        environment = {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///test.db",
            "QADB_OUTBOX_DIR": "/var/lib/task-tracker/qadb",
            "QADB_SYNC_RETRY_DELAYS_SECONDS": "1, 5, 30",
        }
        with patch("bot.config.load_dotenv"), patch.dict("os.environ", environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.qadb_outbox_dir, Path("/var/lib/task-tracker/qadb"))
        self.assertEqual(settings.qadb_sync_retry_delays_seconds, (1, 5, 30))

    @staticmethod
    def _sync_job(report_job_id: int, archive_path: str) -> QadbSyncJob:
        return QadbSyncJob(
            report_job_id=report_job_id,
            project_ref="671",
            run_id=441,
            title="ID 671",
            run_url="https://doqa.example/runs/441",
            test_count=2,
            bug_count=1,
            parsed_bug_count=1,
            archive_path=archive_path,
            content_hash="a" * 64,
        )


class RecordingIngestor:
    def __init__(self, outcomes: dict[bytes, list[Exception | None]] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[bytes, str, int]] = []

    def ingest(self, archive_path: Path, project_ref: str, run_id: int) -> dict:
        data = archive_path.read_bytes()
        self.calls.append((data, project_ref, run_id))
        outcomes = self.outcomes.get(data, [None])
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if outcome is not None:
            raise outcome
        return {"report_id": f"{project_ref}-{run_id}"}


class BlockingIngestor(RecordingIngestor):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def ingest(self, archive_path: Path, project_ref: str, run_id: int) -> dict:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release ingestion")
        return super().ingest(archive_path, project_ref, run_id)


class QadbSyncAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.outbox = self.root / "outbox"
        self.session_factory = init_db(f"sqlite:///{self.root / 'queue.db'}")

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    def add_report_job(self, command_message_id: int, *, external_id: int = 671) -> int:
        with self.session_factory() as session:
            job = DoqaReportJob(
                chat_id=1,
                command_message_id=command_message_id,
                reaction_message_id=command_message_id,
                target_message_id=5,
                external_id=external_id,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id

    def result(self, archive_path: Path, *, run_id: int = 441) -> DoqaReportResult:
        return DoqaReportResult(
            external_id=671,
            run_id=run_id,
            title="ID 671",
            archive_path=archive_path,
            run_url=f"https://doqa.example/runs/{run_id}",
            test_count=2,
            bug_count=1,
            parsed_bug_count=1,
            parser_run=SimpleNamespace(),  # type: ignore[arg-type]
        )

    async def wait_for_status(
        self,
        job_id: int,
        status: QadbSyncJobStatus,
    ) -> QadbSyncJob:
        for _ in range(200):
            with self.session_factory() as session:
                job = session.get(QadbSyncJob, job_id)
                if job is not None and job.status == status:
                    return job
            await asyncio.sleep(0.01)
        self.fail(f"QADB sync job {job_id} did not reach {status}")


class QadbSnapshotTests(QadbSyncAsyncTestCase):
    async def test_stage_is_immutable_and_idempotent_for_report_job(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"first-version")
        report_job_id = self.add_report_job(10)
        queue = QadbSyncQueue(
            self.session_factory,
            RecordingIngestor(),  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )

        stored = await queue.stage(report_job_id, self.result(source))
        source.write_bytes(b"changed-after-stage")
        repeated = await queue.stage(report_job_id, self.result(source))

        self.assertEqual(stored.archive_path, repeated.archive_path)
        self.assertEqual(stored.archive_path.read_bytes(), b"first-version")
        self.assertEqual(stored.content_hash, hashlib.sha256(b"first-version").hexdigest())
        with self.session_factory() as session:
            count = session.scalar(select(func.count()).select_from(QadbSyncJob))
        self.assertEqual(count, 1)

    async def test_load_rejects_missing_or_modified_snapshot(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"exact-version")
        report_job_id = self.add_report_job(11)
        queue = QadbSyncQueue(
            self.session_factory,
            RecordingIngestor(),  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))

        stored.archive_path.write_bytes(b"corrupted")
        with self.assertRaises(SnapshotIntegrityError):
            await queue.load(report_job_id)

        stored.archive_path.unlink()
        with self.assertRaises(SnapshotIntegrityError):
            await queue.load(report_job_id)

    async def test_snapshot_is_deleted_only_after_both_consumers_complete(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"exact-version")
        report_job_id = self.add_report_job(12)
        queue = QadbSyncQueue(
            self.session_factory,
            RecordingIngestor(),  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        with self.session_factory() as session:
            job = session.scalar(
                select(QadbSyncJob).where(QadbSyncJob.report_job_id == report_job_id)
            )
            job.status = QadbSyncJobStatus.COMPLETED
            session.commit()

        await queue.report_completed(report_job_id)
        self.assertTrue(stored.archive_path.exists())

        with self.session_factory() as session:
            report_job = session.get(DoqaReportJob, report_job_id)
            report_job.status = DoqaReportJobStatus.COMPLETED
            session.commit()
        await queue.report_completed(report_job_id)
        self.assertFalse(stored.archive_path.exists())


class QadbSyncWorkerTests(QadbSyncAsyncTestCase):
    async def test_completed_snapshot_is_cleaned_when_worker_starts(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"already-delivered")
        report_job_id = self.add_report_job(19)
        queue = QadbSyncQueue(
            self.session_factory,
            RecordingIngestor(),  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        with self.session_factory() as session:
            report_job = session.get(DoqaReportJob, report_job_id)
            report_job.status = DoqaReportJobStatus.COMPLETED
            sync_job = session.get(QadbSyncJob, stored.id)
            sync_job.status = QadbSyncJobStatus.COMPLETED
            session.commit()

        await queue.start()
        try:
            for _ in range(100):
                if not stored.archive_path.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(stored.archive_path.exists())
        finally:
            await queue.close()

    async def test_transient_failure_retries_same_snapshot_until_success(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"retry-me")
        report_job_id = self.add_report_job(20)
        ingestor = RecordingIngestor({b"retry-me": [TimeoutError("down"), None]})
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        await queue.start()
        try:
            completed = await self.wait_for_status(stored.id, QadbSyncJobStatus.COMPLETED)
            self.assertEqual(completed.attempts, 2)
            self.assertEqual([call[0] for call in ingestor.calls], [b"retry-me", b"retry-me"])
        finally:
            await queue.close()

    async def test_processing_job_is_recovered_on_start(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"recover-me")
        report_job_id = self.add_report_job(21)
        ingestor = RecordingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        with self.session_factory() as session:
            job = session.get(QadbSyncJob, stored.id)
            job.status = QadbSyncJobStatus.PROCESSING
            session.commit()

        await queue.start()
        try:
            completed = await self.wait_for_status(stored.id, QadbSyncJobStatus.COMPLETED)
            self.assertEqual(completed.attempts, 1)
            self.assertEqual(len(ingestor.calls), 1)
        finally:
            await queue.close()

    async def test_fifo_is_per_run_and_unrelated_run_progresses_during_backoff(self) -> None:
        old = self.root / "old.zip"
        new = self.root / "new.zip"
        other = self.root / "other.zip"
        old.write_bytes(b"old")
        new.write_bytes(b"new")
        other.write_bytes(b"other")
        old_report_job = self.add_report_job(30)
        new_report_job = self.add_report_job(31)
        other_report_job = self.add_report_job(32)
        ingestor = RecordingIngestor({b"old": [TimeoutError("down"), None]})
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0.1,),
        )
        old_stored = await queue.stage(old_report_job, self.result(old, run_id=441))
        new_stored = await queue.stage(new_report_job, self.result(new, run_id=441))
        other_stored = await queue.stage(other_report_job, self.result(other, run_id=442))

        await queue.start()
        try:
            await self.wait_for_status(old_stored.id, QadbSyncJobStatus.COMPLETED)
            await self.wait_for_status(new_stored.id, QadbSyncJobStatus.COMPLETED)
            await self.wait_for_status(other_stored.id, QadbSyncJobStatus.COMPLETED)
            self.assertEqual(
                [call[0] for call in ingestor.calls],
                [b"old", b"other", b"old", b"new"],
            )
        finally:
            await queue.close()

    async def test_newer_snapshot_waits_for_older_unstaged_report_job(self) -> None:
        old = self.root / "old.zip"
        new = self.root / "new.zip"
        old.write_bytes(b"old")
        new.write_bytes(b"new")
        old_report_job = self.add_report_job(33)
        new_report_job = self.add_report_job(34)
        ingestor = RecordingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        new_stored = await queue.stage(new_report_job, self.result(new, run_id=441))

        await queue.start()
        try:
            await asyncio.sleep(0.05)
            self.assertFalse(ingestor.calls)

            old_stored = await queue.stage(old_report_job, self.result(old, run_id=441))
            await self.wait_for_status(old_stored.id, QadbSyncJobStatus.COMPLETED)
            await self.wait_for_status(new_stored.id, QadbSyncJobStatus.COMPLETED)
            self.assertEqual([call[0] for call in ingestor.calls], [b"old", b"new"])
        finally:
            await queue.close()

    async def test_newer_snapshot_continues_when_older_unstaged_job_fails(self) -> None:
        new = self.root / "new.zip"
        new.write_bytes(b"new")
        old_report_job = self.add_report_job(341)
        new_report_job = self.add_report_job(342)
        ingestor = RecordingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        new_stored = await queue.stage(new_report_job, self.result(new, run_id=441))

        await queue.start()
        try:
            await asyncio.sleep(0.05)
            self.assertFalse(ingestor.calls)

            with self.session_factory() as session:
                old_job = session.get(DoqaReportJob, old_report_job)
                old_job.status = DoqaReportJobStatus.FAILED
                session.commit()

            await self.wait_for_status(new_stored.id, QadbSyncJobStatus.COMPLETED)
            self.assertEqual([call[0] for call in ingestor.calls], [b"new"])
        finally:
            await queue.close()

    async def test_cleanup_error_does_not_stop_other_sync_jobs(self) -> None:
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        first_report_job = self.add_report_job(35)
        second_report_job = self.add_report_job(36)
        ingestor = RecordingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        first_stored = await queue.stage(first_report_job, self.result(first, run_id=441))
        second_stored = await queue.stage(second_report_job, self.result(second, run_id=442))
        with self.session_factory() as session:
            for report_job_id in (first_report_job, second_report_job):
                report_job = session.get(DoqaReportJob, report_job_id)
                report_job.status = DoqaReportJobStatus.COMPLETED
            session.commit()

        with patch.object(Path, "unlink", side_effect=[OSError("disk failure"), None]):
            await queue.start()
            try:
                await self.wait_for_status(first_stored.id, QadbSyncJobStatus.COMPLETED)
                await self.wait_for_status(second_stored.id, QadbSyncJobStatus.COMPLETED)
                self.assertEqual([call[0] for call in ingestor.calls], [b"first", b"second"])
                self.assertIsNotNone(queue._worker)
                self.assertFalse(queue._worker.done())
            finally:
                await queue.close()

    async def test_close_waits_for_inflight_ingestion(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"blocking")
        report_job_id = self.add_report_job(37)
        ingestor = BlockingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        await queue.start()
        self.assertTrue(await asyncio.to_thread(ingestor.started.wait, 1))

        close_task = asyncio.create_task(queue.close())
        await asyncio.sleep(0.05)
        self.assertFalse(close_task.done())
        ingestor.release.set()
        await close_task

        with self.session_factory() as session:
            completed = session.get(QadbSyncJob, stored.id)
            self.assertEqual(completed.status, QadbSyncJobStatus.COMPLETED)

    async def test_corrupted_snapshot_fails_without_calling_ingestor(self) -> None:
        source = self.root / "source.zip"
        source.write_bytes(b"exact")
        report_job_id = self.add_report_job(40)
        ingestor = RecordingIngestor()
        queue = QadbSyncQueue(
            self.session_factory,
            ingestor,  # type: ignore[arg-type]
            self.outbox,
            retry_delays_seconds=(0,),
        )
        stored = await queue.stage(report_job_id, self.result(source))
        stored.archive_path.write_bytes(b"corrupt")

        await queue.start()
        try:
            failed = await self.wait_for_status(stored.id, QadbSyncJobStatus.FAILED)
            self.assertIn("SHA-256", failed.last_error or "")
            self.assertFalse(ingestor.calls)
        finally:
            await queue.close()


if __name__ == "__main__":
    unittest.main()
