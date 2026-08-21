from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aiogram import Bot
from aiogram.types import FSInputFile, ReactionTypeEmoji, ReplyParameters
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bot.db.models import DoqaReportJob, DoqaReportJobStatus
from bot.integrations.doqa import DoqaApiError

from .service import DoqaReportEmptyError, DoqaReportResult, DoqaReportService


ACTIVE_JOB_STATUSES = (
    DoqaReportJobStatus.QUEUED,
    DoqaReportJobStatus.PROCESSING,
    DoqaReportJobStatus.RETRYING,
)
REACTION_ZIP_ACCEPTED = ("🫡", "🤓")
REACTION_ZIP_SENT = ("👌", "😎")


class DoqaReportQueue:
    def __init__(
        self,
        bot: Bot,
        session_factory: sessionmaker,
        report_service: DoqaReportService,
        *,
        retry_delays_seconds: tuple[int, ...] = (15, 60, 180),
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.report_service = report_service
        self.retry_delays_seconds = retry_delays_seconds or (15, 60, 180)
        self._tasks: set[asyncio.Task[None]] = set()
        self._running_job_ids: set[int] = set()
        self._closed = False

    async def start(self) -> None:
        self._closed = False
        with self.session_factory() as session:
            jobs = session.scalars(
                select(DoqaReportJob).where(DoqaReportJob.status.in_(ACTIVE_JOB_STATUSES))
            ).all()
            for job in jobs:
                if job.status == DoqaReportJobStatus.PROCESSING:
                    job.status = DoqaReportJobStatus.QUEUED
                    job.next_attempt_at = None
            session.commit()
            job_ids = [job.id for job in jobs]

        for job_id in job_ids:
            self._spawn(job_id)
        if job_ids:
            logging.info("Recovered pending DoQA report jobs: %s", len(job_ids))

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def enqueue(
        self,
        *,
        chat_id: int,
        command_message_id: int,
        target_message_id: int,
        external_id: int,
    ) -> DoqaReportJob:
        with self.session_factory() as session:
            job = session.scalar(
                select(DoqaReportJob).where(
                    DoqaReportJob.chat_id == chat_id,
                    DoqaReportJob.command_message_id == command_message_id,
                )
            )
            if job is None:
                job = DoqaReportJob(
                    chat_id=chat_id,
                    command_message_id=command_message_id,
                    reaction_message_id=command_message_id,
                    target_message_id=target_message_id,
                    external_id=external_id,
                    max_attempts=len(self.retry_delays_seconds) + 1,
                )
                session.add(job)
                session.commit()
                session.refresh(job)
            job_id = job.id
            job_status = job.status

        if job_status in ACTIVE_JOB_STATUSES:
            await self._set_reaction(chat_id, command_message_id, REACTION_ZIP_ACCEPTED)
            self._spawn(job_id)
        elif job_status == DoqaReportJobStatus.COMPLETED:
            await self._set_reaction(chat_id, command_message_id, REACTION_ZIP_SENT)
        return job

    def find_failed_job_for_error(self, chat_id: int, error_message_id: int) -> int | None:
        with self.session_factory() as session:
            return session.scalar(
                select(DoqaReportJob.id).where(
                    DoqaReportJob.chat_id == chat_id,
                    DoqaReportJob.error_message_id == error_message_id,
                    DoqaReportJob.status == DoqaReportJobStatus.FAILED,
                )
            )

    async def retry(self, job_id: int, *, reaction_message_id: int) -> bool:
        with self.session_factory() as session:
            job = session.get(DoqaReportJob, job_id)
            if job is None or job.status != DoqaReportJobStatus.FAILED:
                return False
            job.status = DoqaReportJobStatus.QUEUED
            job.attempts = 0
            job.next_attempt_at = None
            job.last_error = None
            job.error_message_id = None
            job.reaction_message_id = reaction_message_id
            session.commit()
            chat_id = job.chat_id

        await self._set_reaction(chat_id, reaction_message_id, REACTION_ZIP_ACCEPTED)
        self._spawn(job_id)
        return True

    def _spawn(self, job_id: int) -> None:
        if self._closed or job_id in self._running_job_ids:
            return
        self._running_job_ids.add(job_id)
        task = asyncio.create_task(self._run_job(job_id), name=f"doqa-report-{job_id}")
        self._tasks.add(task)

        def done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            self._running_job_ids.discard(job_id)
            if not completed.cancelled() and completed.exception() is not None:
                logging.error(
                    "DoQA report worker crashed job_id=%s",
                    job_id,
                    exc_info=completed.exception(),
                )

        task.add_done_callback(done)

    async def _run_job(self, job_id: int) -> None:
        while not self._closed:
            job = self._load_job(job_id)
            if job is None or job.status not in ACTIVE_JOB_STATUSES:
                return

            delay = _delay_until(job.next_attempt_at)
            if delay > 0:
                await asyncio.sleep(delay)

            with self.session_factory() as session:
                current = session.get(DoqaReportJob, job_id)
                if current is None or current.status not in ACTIVE_JOB_STATUSES:
                    return
                current.status = DoqaReportJobStatus.PROCESSING
                current.next_attempt_at = None
                current.attempts += 1
                session.commit()
                attempt = current.attempts
                max_attempts = current.max_attempts
                external_id = current.external_id
                chat_id = current.chat_id
                target_message_id = current.target_message_id
                reaction_message_id = current.reaction_message_id

            result: DoqaReportResult | None = None
            try:
                result = await self.report_service.create_report(external_id)
                sent = await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(result.archive_path),
                    caption=_report_caption(result),
                    reply_parameters=ReplyParameters(
                        message_id=target_message_id,
                        allow_sending_without_reply=True,
                    ),
                )
                with self.session_factory() as session:
                    current = session.get(DoqaReportJob, job_id)
                    if current is not None:
                        current.status = DoqaReportJobStatus.COMPLETED
                        current.run_id = result.run_id
                        current.sent_message_id = sent.message_id
                        current.last_error = None
                        current.next_attempt_at = None
                        session.commit()
                await self._set_reaction(chat_id, reaction_message_id, REACTION_ZIP_SENT)
                return
            except Exception as error:
                if _is_transient(error) and attempt < max_attempts:
                    retry_delay = self.retry_delays_seconds[
                        min(attempt - 1, len(self.retry_delays_seconds) - 1)
                    ]
                    with self.session_factory() as session:
                        current = session.get(DoqaReportJob, job_id)
                        if current is not None:
                            current.status = DoqaReportJobStatus.RETRYING
                            current.last_error = _error_log_text(error)
                            current.next_attempt_at = _utcnow() + timedelta(seconds=retry_delay)
                            session.commit()
                    logging.warning(
                        "Retrying DoQA report job_id=%s attempt=%s/%s in %ss: %s",
                        job_id,
                        attempt,
                        max_attempts,
                        retry_delay,
                        error,
                    )
                    continue

                await self._fail_job(
                    job_id,
                    error,
                    chat_id=chat_id,
                    reply_to_message_id=reaction_message_id,
                )
                return
            finally:
                if result is not None:
                    await asyncio.to_thread(self.report_service.cleanup, result)

    def _load_job(self, job_id: int) -> DoqaReportJob | None:
        with self.session_factory() as session:
            return session.get(DoqaReportJob, job_id)

    async def _fail_job(
        self,
        job_id: int,
        error: Exception,
        *,
        chat_id: int,
        reply_to_message_id: int,
    ) -> None:
        text = _error_chat_text(error)
        with self.session_factory() as session:
            job = session.get(DoqaReportJob, job_id)
            if job is not None:
                job.status = DoqaReportJobStatus.FAILED
                job.last_error = _error_log_text(error)
                job.next_attempt_at = None
                session.commit()

        logging.exception("DoQA report job failed job_id=%s", job_id, exc_info=error)
        try:
            error_message = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_parameters=ReplyParameters(
                    message_id=reply_to_message_id,
                    allow_sending_without_reply=True,
                ),
            )
        except Exception:
            logging.exception("Failed to send DoQA error to chat job_id=%s", job_id)
            return

        with self.session_factory() as session:
            job = session.get(DoqaReportJob, job_id)
            if job is not None:
                job.error_message_id = error_message.message_id
                session.commit()

    async def _set_reaction(
        self,
        chat_id: int,
        message_id: int,
        emojis: tuple[str, ...],
    ) -> None:
        for emoji in emojis:
            try:
                await self.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=message_id,
                    reaction=[ReactionTypeEmoji(emoji=emoji)],
                )
                return
            except Exception as error:
                logging.warning(
                    "Failed to set ZIP reaction %s for chat=%s message=%s: %s",
                    emoji,
                    chat_id,
                    message_id,
                    error,
                )


def _report_caption(result: DoqaReportResult) -> str:
    return (
        f"<b>DoQA — ID {result.external_id}, прогон #{result.run_id}</b>\n"
        f"{html.escape(result.title)}\n\n"
        f"Тестов: {result.test_count}\n"
        f"Багов в DoQA: {result.bug_count}\n"
        f"Багов в архиве: {result.parsed_bug_count}\n"
        f'<a href="{html.escape(result.run_url, quote=True)}">Открыть прогон в DoQA</a>'
    )


def _is_transient(error: Exception) -> bool:
    if isinstance(error, DoqaReportEmptyError):
        return False
    if isinstance(error, DoqaApiError):
        return error.status is None or error.status >= 500
    return True


def _error_chat_text(error: Exception) -> str:
    if isinstance(error, DoqaReportEmptyError):
        return f"{error}\n\nОтветьте на это сообщение словом «повтори», когда прогон обновится."
    if isinstance(error, DoqaApiError):
        return (
            f"Не удалось получить отчёт DoQA: {html.escape(str(error))}\n\n"
            "Ответьте на это сообщение словом «повтори», чтобы запустить снова."
        )
    error_id = uuid4().hex[:8]
    return (
        f"Не удалось сформировать ZIP-архив. Код ошибки: <code>{error_id}</code>.\n\n"
        "Ответьте на это сообщение словом «повтори», чтобы запустить снова."
    )


def _error_log_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:4000]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _delay_until(value: datetime | None) -> float:
    if value is None:
        return 0.0
    now = _utcnow()
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0.0, (value - now).total_seconds())
