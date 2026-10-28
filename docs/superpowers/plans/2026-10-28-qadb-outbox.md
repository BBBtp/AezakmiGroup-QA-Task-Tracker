# QADB Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver automatic `/zip` archives to Telegram immediately while durably retrying the exact generated snapshot to QADB in the background.

**Architecture:** A new PostgreSQL-backed QADB outbox owns immutable ZIP snapshots stored in a Docker volume. `DoqaReportQueue` stages or reloads that snapshot before Telegram delivery, while an independent worker retries QADB ingestion with per-run FIFO ordering and never re-fetches DoQA.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy 2, aiogram 3, PostgreSQL/SQLite tests, Docker Compose, stdlib filesystem and SHA-256 utilities.

**Spec:** `docs/superpowers/specs/2026-10-28-qadb-outbox-design.md`

## Global Constraints

- Only automatic Telegram `/zip` reports create QADB outbox jobs; Mini App/manual PDF flows remain excluded.
- Each command's staged ZIP is immutable and verified by SHA-256 before every consumer reads it.
- A later `/zip` for the same `project_ref + run_id` may replace the prior QADB snapshot, but older snapshots for that key synchronize first.
- QADB failures never block Telegram delivery or produce repeated chat error messages.
- Pending snapshots survive container replacement under `/app/task_tracker_data`.
- No new external service or Python dependency.

## Review Focus

- QADB becomes unavailable after staging but before any QADB write: Telegram still receives the ZIP and the outbox remains retryable.
- The process restarts while a QADB row is `PROCESSING`: startup safely resumes from the existing bytes without another DoQA request.
- Multiple snapshots share one `project_ref + run_id`: QADB sees them in creation order while unrelated keys continue during backoff.
- The durable file is missing or has the wrong SHA-256: neither Telegram nor QADB consumes it, and no regeneration silently changes the snapshot.
- QADB is unconfigured or a manual report is requested: no outbox row or durable snapshot is created.

---

### Task 1: Persist QADB outbox configuration and jobs

**Files:**
- Modify: `bot/db/models.py`
- Modify: `bot/config.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Test: `tests/test_qadb_sync_queue.py`

**Interfaces:**
- Produces: `QadbSyncJobStatus` with `QUEUED`, `PROCESSING`, `RETRYING`, `COMPLETED`, and `FAILED`.
- Produces: `QadbSyncJob`, uniquely keyed by `report_job_id`, containing immutable report metadata, `archive_path`, `content_hash`, retry state, and timestamps.
- Produces: `Settings.qadb_outbox_dir: Path` and `Settings.qadb_sync_retry_delays_seconds: tuple[int, ...]`.

- [ ] **Step 1: Write failing model and configuration tests**

Assert that `init_db()` creates `qadb_sync_jobs`, duplicate `report_job_id` rows violate the unique constraint, defaults resolve to `task_tracker_data/qadb_outbox` and `(15, 60, 300, 900, 3600)`, and configured retry delays are parsed as positive integers.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m unittest tests.test_qadb_sync_queue.QadbSyncPersistenceTests -v`
Expected: FAIL because the model and settings do not exist.

- [ ] **Step 3: Add the enum, model, settings, environment documentation, and durable Compose volume**

Create the table through existing `Base.metadata.create_all`; mount named volume `task_tracker_data` at `/app/task_tracker_data`; add no hand-written destructive migration.

- [ ] **Step 4: Run the focused tests and verify pass**

Run: `python -m unittest tests.test_qadb_sync_queue.QadbSyncPersistenceTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/db/models.py bot/config.py .env.example docker-compose.yml tests/test_qadb_sync_queue.py
git commit -m "feat: persist qadb sync jobs"
```

### Task 2: Build the immutable QADB outbox worker

**Files:**
- Create: `bot/services/qadb_sync/__init__.py`
- Create: `bot/services/qadb_sync/queue.py`
- Modify: `tests/test_qadb_sync_queue.py`

**Interfaces:**
- Produces: `StoredDoqaReport` with the report metadata and durable `archive_path` required by Telegram captions and QADB ingestion.
- Produces: `SnapshotIntegrityError` for missing or hash-mismatched archives.
- Produces: `QadbSyncQueue(session_factory, ingestor, outbox_dir, retry_delays_seconds)`.
- Produces: async `start()`, `close()`, and `stage(report_job_id: int, result: DoqaReportResult) -> StoredDoqaReport`.
- Produces: `load(report_job_id: int, *, verify: bool = True) -> StoredDoqaReport | None` and async `report_completed(report_job_id: int) -> None`.

- [ ] **Step 1: Write failing staging and integrity tests**

Test atomic durable copying, SHA-256 persistence, idempotent staging by `report_job_id`, exact-byte reload, missing-file failure, hash-mismatch failure, and no DoQA regeneration interface.

- [ ] **Step 2: Run staging tests and verify failure**

Run: `python -m unittest tests.test_qadb_sync_queue.QadbSnapshotTests -v`
Expected: FAIL because `QadbSyncQueue` does not exist.

- [ ] **Step 3: Implement immutable staging, loading, verification, and dual-consumer cleanup**

Use a temporary file plus `Path.replace()` in the configured outbox directory. Delete only a verified archive whose `QadbSyncJob` is `COMPLETED` and whose `DoqaReportJob` is also `COMPLETED`.

- [ ] **Step 4: Write failing worker scheduling tests**

Test deferred retry without duplicate rows, startup recovery from `PROCESSING`, eventual success, per-key FIFO, unrelated-key progress during backoff, terminal integrity failure, and cleanup after both consumers complete.

- [ ] **Step 5: Run worker tests and verify failure**

Run: `python -m unittest tests.test_qadb_sync_queue.QadbSyncWorkerTests -v`
Expected: FAIL on unimplemented scheduling and retry behavior.

- [ ] **Step 6: Implement the background worker**

The single worker selects due rows that have no older non-terminal row with the same `project_ref + run_id`. Retry indefinitely using the configured sequence and repeat its final delay; restore interrupted `PROCESSING` rows on `start()`; wake promptly when `stage()` adds work.

- [ ] **Step 7: Run all QADB sync tests**

Run: `python -m unittest tests.test_qadb_sync_queue -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add bot/services/qadb_sync tests/test_qadb_sync_queue.py
git commit -m "feat: add durable qadb outbox worker"
```

### Task 3: Decouple `/zip` delivery from QADB synchronization

**Files:**
- Modify: `bot/services/doqa_report/service.py`
- Modify: `bot/services/doqa_report/queue.py`
- Modify: `bot/app.py`
- Modify: `tests/test_doqa_queue.py`
- Modify: `tests/test_doqa_report.py`

**Interfaces:**
- Consumes: `QadbSyncQueue.stage`, `load`, `start`, `close`, and `report_completed` from Task 2.
- Changes: `DoqaReportService.create_report(external_id)` only generates a report; it never writes QADB.
- Changes: `DoqaReportQueue(..., qadb_sync_queue: QadbSyncQueue | None = None)` stages or reloads a durable snapshot before Telegram delivery.

- [ ] **Step 1: Write failing delivery-decoupling tests**

Assert that a QADB ingestor failure occurs only in the background, Telegram receives the ZIP once, the report job becomes `COMPLETED`, and no chat error is sent. Assert that a Telegram retry and a recovered report job reuse the staged bytes without another `create_report()` call.

- [ ] **Step 2: Run focused queue tests and verify failure**

Run: `python -m unittest tests.test_doqa_queue -v`
Expected: FAIL because QADB ingestion is still inside report generation and no sync queue is accepted.

- [ ] **Step 3: Remove QADB ingestion from report generation and integrate stored snapshots into `DoqaReportQueue`**

When QADB is configured, first load an existing snapshot; otherwise generate once, stage it, clean parser temporary files, and send the stored archive. After Telegram success, mark the report job complete and notify the sync queue so dual-consumer cleanup can run.

- [ ] **Step 4: Wire lifecycle in `bot/app.py`**

Construct `QadbSyncQueue` only when QADB credentials exist, pass it only to the automatic report queue, start it before automatic report jobs, and close it during shutdown. Keep `manual_doqa_report_service` free of QADB behavior.

- [ ] **Step 5: Run report and QADB tests**

Run: `python -m unittest tests.test_doqa_queue tests.test_doqa_report tests.test_qadb_ingest tests.test_qadb_sync_queue -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/app.py bot/services/doqa_report bot/services/qadb_sync tests/test_doqa_queue.py tests/test_doqa_report.py
git commit -m "feat: deliver zip independently of qadb"
```

### Task 4: Verify the complete bot and deployment contract

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-28-qadb-outbox-design.md` only if implementation revealed a documented mismatch
- Modify: `docs/superpowers/plans/2026-10-28-qadb-outbox.md` to check completed steps

**Interfaces:**
- Consumes: all prior tasks.
- Produces: deployment instructions explaining the volume, retry settings, log messages, and behavior of already-failed jobs.

- [ ] **Step 1: Add deployment and operational documentation**

Document that `docker compose up -d --build --force-recreate app` creates the persistent volume, existing failed jobs without snapshots require a new `/zip`, pending QADB rows resume automatically, and manual tools never enqueue QADB work.

- [ ] **Step 2: Run the full Python test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 3: Validate Compose rendering**

Run: `docker compose config --quiet`
Expected: exit code 0.

- [ ] **Step 4: Inspect the final diff and working tree**

Run: `git diff --check && git status --short`
Expected: no whitespace errors; only planned files changed.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers
git commit -m "docs: describe qadb outbox operations"
```

