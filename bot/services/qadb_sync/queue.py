from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bot.db.models import (
    DoqaReportJob,
    DoqaReportJobStatus,
    QadbSyncJob,
    QadbSyncJobStatus,
)
from bot.integrations.qadb import QadbReportIngestor


SCHEDULABLE_STATUSES = (
    QadbSyncJobStatus.QUEUED,
    QadbSyncJobStatus.RETRYING,
)
NON_TERMINAL_STATUSES = (*SCHEDULABLE_STATUSES, QadbSyncJobStatus.PROCESSING)


class GeneratedDoqaReport(Protocol):
    external_id: int
    run_id: int
    title: str
    archive_path: Path
    run_url: str
    test_count: int
    bug_count: int
    parsed_bug_count: int


class SnapshotIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredDoqaReport:
    id: int
    report_job_id: int
    external_id: int
    project_ref: str
    run_id: int
    title: str
    archive_path: Path
    run_url: str
    test_count: int
    bug_count: int
    parsed_bug_count: int
    content_hash: str


class QadbSyncQueue:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ingestor: QadbReportIngestor,
        outbox_dir: Path,
        *,
        retry_delays_seconds: tuple[float, ...] = (15, 60, 300, 900, 3600),
    ) -> None:
        self.session_factory = session_factory
        self.ingestor = ingestor
        self.outbox_dir = outbox_dir
        self.retry_delays_seconds = retry_delays_seconds or (3600,)
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._closed = True

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._closed = False
        await asyncio.to_thread(self._recover_interrupted_jobs)
        await asyncio.to_thread(self._cleanup_completed_snapshots)
        self._worker = asyncio.create_task(self._run(), name="qadb-sync-worker")
        self._wake.set()

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def stage(
        self,
        report_job_id: int,
        result: GeneratedDoqaReport,
    ) -> StoredDoqaReport:
        stored = await asyncio.to_thread(self._stage, report_job_id, result)
        self._wake.set()
        return stored

    def load(self, report_job_id: int, *, verify: bool = True) -> StoredDoqaReport | None:
        with self.session_factory() as session:
            job = session.scalar(
                select(QadbSyncJob).where(QadbSyncJob.report_job_id == report_job_id)
            )
            if job is None:
                return None
            stored = _stored_report(job)
        if verify:
            _verify_snapshot(stored)
        return stored

    async def report_completed(self, report_job_id: int) -> None:
        try:
            await asyncio.to_thread(self._cleanup_if_delivered, report_job_id)
        except SnapshotIntegrityError as error:
            logging.error(
                "QADB outbox cleanup skipped for report_job_id=%s: %s",
                report_job_id,
                error,
            )

    def _stage(self, report_job_id: int, result: GeneratedDoqaReport) -> StoredDoqaReport:
        existing = self.load(report_job_id)
        if existing is not None:
            return existing

        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.outbox_dir / f".{report_job_id}-{uuid4().hex}.tmp"
        final_path: Path | None = None
        try:
            shutil.copyfile(result.archive_path, temporary_path)
            content_hash = _hash_file(temporary_path)
            final_path = self.outbox_dir / f"{report_job_id}-{content_hash[:16]}.zip"
            temporary_path.replace(final_path)

            with self.session_factory() as session:
                job = QadbSyncJob(
                    report_job_id=report_job_id,
                    project_ref=str(result.external_id),
                    run_id=result.run_id,
                    title=result.title,
                    run_url=result.run_url,
                    test_count=result.test_count,
                    bug_count=result.bug_count,
                    parsed_bug_count=result.parsed_bug_count,
                    archive_path=str(final_path),
                    content_hash=content_hash,
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                return _stored_report(job)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _recover_interrupted_jobs(self) -> None:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(QadbSyncJob).where(
                        QadbSyncJob.status == QadbSyncJobStatus.PROCESSING
                    )
                )
            )
            for job in jobs:
                job.status = QadbSyncJobStatus.RETRYING
                job.next_attempt_at = None
            session.commit()
        if jobs:
            logging.info("Recovered interrupted QADB sync jobs: %s", len(jobs))

    def _cleanup_completed_snapshots(self) -> None:
        with self.session_factory() as session:
            report_job_ids = list(
                session.scalars(
                    select(QadbSyncJob.report_job_id).where(
                        QadbSyncJob.status == QadbSyncJobStatus.COMPLETED
                    )
                )
            )
        for report_job_id in report_job_ids:
            try:
                self._cleanup_if_delivered(report_job_id)
            except SnapshotIntegrityError as error:
                logging.error(
                    "QADB outbox startup cleanup skipped for report_job_id=%s: %s",
                    report_job_id,
                    error,
                )

    async def _run(self) -> None:
        while not self._closed:
            self._wake.clear()
            job_id, wait_seconds = await asyncio.to_thread(self._next_job)
            if job_id is not None:
                await self._process(job_id)
                continue
            try:
                if wait_seconds is None:
                    await self._wake.wait()
                else:
                    await asyncio.wait_for(self._wake.wait(), timeout=max(0.001, wait_seconds))
            except TimeoutError:
                pass

    def _next_job(self) -> tuple[int | None, float | None]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(QadbSyncJob)
                    .where(QadbSyncJob.status.in_(NON_TERMINAL_STATUSES))
                    .order_by(QadbSyncJob.id)
                )
            )

        heads: dict[tuple[str, int], QadbSyncJob] = {}
        for job in jobs:
            heads.setdefault((job.project_ref, job.run_id), job)

        now = _utcnow()
        ready: list[QadbSyncJob] = []
        delays: list[float] = []
        for job in heads.values():
            if job.status == QadbSyncJobStatus.PROCESSING:
                continue
            delay = _delay_until(job.next_attempt_at, now)
            if delay <= 0:
                ready.append(job)
            else:
                delays.append(delay)
        if ready:
            return min(ready, key=lambda job: job.id).id, 0.0
        return None, min(delays) if delays else None

    async def _process(self, job_id: int) -> None:
        with self.session_factory() as session:
            job = session.get(QadbSyncJob, job_id)
            if job is None or job.status not in SCHEDULABLE_STATUSES:
                return
            job.status = QadbSyncJobStatus.PROCESSING
            job.next_attempt_at = None
            job.attempts += 1
            session.commit()
            attempt = job.attempts
            stored = _stored_report(job)

        try:
            _verify_snapshot(stored)
            await asyncio.to_thread(
                self.ingestor.ingest,
                stored.archive_path,
                stored.project_ref,
                stored.run_id,
            )
        except SnapshotIntegrityError as error:
            self._mark_failed(job_id, error)
            logging.error("QADB sync snapshot is invalid job_id=%s: %s", job_id, error)
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            retry_delay = self.retry_delays_seconds[
                min(attempt - 1, len(self.retry_delays_seconds) - 1)
            ]
            with self.session_factory() as session:
                job = session.get(QadbSyncJob, job_id)
                if job is not None:
                    job.status = QadbSyncJobStatus.RETRYING
                    job.last_error = _error_text(error)
                    job.next_attempt_at = _utcnow() + timedelta(seconds=retry_delay)
                    session.commit()
            logging.warning(
                "Retrying QADB sync job_id=%s attempt=%s in %ss: %s",
                job_id,
                attempt,
                retry_delay,
                error,
            )
            return

        with self.session_factory() as session:
            job = session.get(QadbSyncJob, job_id)
            if job is not None:
                job.status = QadbSyncJobStatus.COMPLETED
                job.last_error = None
                job.next_attempt_at = None
                job.completed_at = _utcnow()
                session.commit()
        logging.info("QADB sync completed job_id=%s attempt=%s", job_id, attempt)
        await asyncio.to_thread(self._cleanup_if_delivered, stored.report_job_id)

    def _mark_failed(self, job_id: int, error: Exception) -> None:
        with self.session_factory() as session:
            job = session.get(QadbSyncJob, job_id)
            if job is not None:
                job.status = QadbSyncJobStatus.FAILED
                job.last_error = _error_text(error)
                job.next_attempt_at = None
                session.commit()

    def _cleanup_if_delivered(self, report_job_id: int) -> None:
        with self.session_factory() as session:
            sync_job = session.scalar(
                select(QadbSyncJob).where(QadbSyncJob.report_job_id == report_job_id)
            )
            report_job = session.get(DoqaReportJob, report_job_id)
            if (
                sync_job is None
                or report_job is None
                or sync_job.status != QadbSyncJobStatus.COMPLETED
                or report_job.status != DoqaReportJobStatus.COMPLETED
            ):
                return
            stored = _stored_report(sync_job)

        if not stored.archive_path.exists():
            return
        _verify_snapshot(stored)
        stored.archive_path.unlink()


def _stored_report(job: QadbSyncJob) -> StoredDoqaReport:
    return StoredDoqaReport(
        id=job.id,
        report_job_id=job.report_job_id,
        external_id=int(job.project_ref),
        project_ref=job.project_ref,
        run_id=job.run_id,
        title=job.title,
        archive_path=Path(job.archive_path),
        run_url=job.run_url,
        test_count=job.test_count,
        bug_count=job.bug_count,
        parsed_bug_count=job.parsed_bug_count,
        content_hash=job.content_hash,
    )


def _verify_snapshot(stored: StoredDoqaReport) -> None:
    if not stored.archive_path.is_file():
        raise SnapshotIntegrityError(f"Снимок отсутствует: {stored.archive_path}")
    actual_hash = _hash_file(stored.archive_path)
    if actual_hash != stored.content_hash:
        raise SnapshotIntegrityError(
            f"SHA-256 снимка не совпадает: ожидался {stored.content_hash}, получен {actual_hash}"
        )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:4000]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _delay_until(value: datetime | None, now: datetime) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0.0, (value - now).total_seconds())
