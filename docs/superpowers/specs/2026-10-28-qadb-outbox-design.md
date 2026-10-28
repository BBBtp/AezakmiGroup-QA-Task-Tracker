# QADB Outbox Design

## Intent

Automatic `/zip` reports must remain useful when QADB is unavailable. The bot must send the
generated archive to Telegram without waiting for QADB, retain the exact archive that was sent,
and synchronize that immutable snapshot later. The current behavior couples report delivery to
QADB ingestion, so a DNS or Supabase outage makes `/zip` fail even though DoQA and Telegram work.

## Goals

- Send an automatic `/zip` archive to Telegram as soon as DoQA generation succeeds.
- Persist the exact generated ZIP before external delivery so restarts cannot lose the QADB
  payload.
- Retry QADB ingestion in the background until it succeeds, including after app restarts.
- Retry the same bytes and metadata for a command; never re-fetch DoQA for QADB retries.
- Keep QADB's current latest-snapshot semantics: a later `/zip` for the same
  `project_ref + run_id` may replace the previous snapshot through the existing upserts.
- Preserve current QADB idempotency: fixed Storage paths, report upsert by
  `project_ref_raw + run_id`, and bug upsert by `report_id + external_id`.
- Keep manual Mini App reports and manual PDF parsing completely outside QADB synchronization.

## Non-goals

- Keeping historical versions of the same DoQA run in QADB.
- Changing the QADB schema, triggers, or audit behavior.
- Introducing Redis, RabbitMQ, S3, or another service.
- Automatically recovering reports from old failed `/zip` jobs that have no preserved snapshot.

## User-visible behavior

An automatic `/zip` command has two independent outcomes after a report is generated:

1. Telegram delivery proceeds from the persisted snapshot and determines whether the command job
   is complete from the user's perspective.
2. QADB synchronization runs in the background and never blocks Telegram delivery.

If QADB is down, the user still receives the ZIP. The bot logs the deferred QADB attempt; it does
not send repeated QADB failure messages into the task chat. Existing DoQA generation errors and
Telegram delivery errors retain their current retry and user-error behavior.

## Architecture

### Immutable snapshot and durable outbox

Add a `qadb_sync_jobs` table. Each row belongs to one `doqa_report_jobs` row and stores:

- the automatic report job ID;
- `project_ref` and exact `run_id`;
- Telegram caption metadata needed to resend without regenerating the report;
- a path to an immutable ZIP in a durable outbox directory;
- the ZIP SHA-256 hash;
- sync status, attempt count, next-attempt time, last error, and timestamps.

The report job ID is unique in the outbox. Retrying the same Telegram command therefore reuses its
existing snapshot. A new `/zip` command creates a new snapshot, even when it resolves to the same
DoQA run.

The outbox directory is configurable and stored under the existing `task_tracker_data` tree by
default. Docker Compose mounts that tree as a named volume so image rebuilds and container
replacement preserve unsynchronized archives. Snapshot creation copies to a temporary file in the
outbox and atomically renames it before the database row is committed.

### Report generation and Telegram delivery

Remove QADB ingestion from `DoqaReportService.create_report`. The service only fetches DoQA and
generates an archive.

`DoqaReportQueue` asks the outbox for an existing snapshot before generation. If none exists, it
generates the report, stages the immutable snapshot, and cleans the parser's temporary run. It then
sends the durable snapshot to Telegram. A Telegram retry or process restart reads the same archive
and caption metadata rather than regenerating from DoQA.

When QADB is not configured, report generation and Telegram delivery keep the current behavior and
do not create outbox rows.

### QADB synchronization worker

Use one background worker with FIFO ordering per `project_ref + run_id`. A later snapshot for the
same run is eligible only after every older snapshot for that key is terminal (`COMPLETED` or
`FAILED`), so the newest successful command is applied last. Unrelated projects and runs may
continue while one key is waiting for its retry deadline; one broken report must not block the
entire QADB queue.

The worker calls the existing `QadbReportIngestor.ingest` with the durable archive. On failure it
stores the error and schedules another attempt using configurable exponential-style delays. After
the configured sequence is exhausted, the final delay repeats indefinitely. Startup converts an
interrupted `PROCESSING` row back into retryable work and resumes the queue.

The existing QADB writer remains at-least-once. Partial retries may repeat upserts, but they cannot
create duplicate report or bug rows when QADB has the required unique constraints. The integration
does not publish historical events; it writes the current report and bug snapshot. Storage objects
with matching paths are overwritten as they are today.

### Cleanup

The durable ZIP has two consumers: Telegram and QADB. Verify its SHA-256 before every Telegram send
and QADB ingestion attempt. A missing or mismatched file is a non-retryable local-corruption error:
the affected Telegram report job fails visibly if it has not been delivered, the QADB row becomes
`FAILED`, and the bot never regenerates or substitutes a different DoQA snapshot. Delete a valid ZIP only after both the automatic
report job is `COMPLETED` and the QADB sync row is `COMPLETED`. Keep the database outbox row as the
delivery record. Never delete an unsynchronized archive automatically.

If QADB is unavailable for a long time, disk usage grows by the size of pending automatic report
archives. This is intentional: preserving exact snapshots takes priority over bounded storage.
Operational logs must include pending job ID, attempt, retry delay, and final success.

## Failure and recovery rules

- Crash before atomic rename: no committed outbox row; the report job may regenerate safely.
- Crash after rename but before row commit: an orphan file may remain; it is harmless and can be
  reported or cleaned by a later maintenance task, but must not be guessed into a sync job.
- Crash after row commit: startup resumes both Telegram delivery and QADB synchronization from the
  saved snapshot.
- Missing or hash-mismatched snapshot: fail that consumer terminally, log the expected and actual
  state, and allow newer or unrelated queue keys to proceed.
- QADB fails after partial writes: retry the same archive; existing upserts converge to one report
  snapshot.
- Telegram fails after staging: retain the archive and retry Telegram from it without consulting
  DoQA.
- New `/zip` for the same run: create a new immutable snapshot; the sequential QADB worker applies
  it after older queued versions.

## Configuration and deployment

- `QADB_OUTBOX_DIR`, default `task_tracker_data/qadb_outbox`.
- `QADB_SYNC_RETRY_DELAYS_SECONDS`, default `15,60,300,900,3600`; repeat `3600` indefinitely.
- Mount a named Docker volume at `/app/task_tracker_data` for the app service.
- No new external service or Python dependency.

## Verification

Automated tests must prove:

- QADB failure does not block Telegram ZIP delivery.
- The exact staged bytes are reused across Telegram retries and app restarts.
- Pending QADB work resumes after restart and eventually completes.
- Repeated QADB failures keep one outbox row and schedule retries without generating another report.
- Multiple snapshots for the same run synchronize in creation order while unrelated retrying keys
  do not block each other.
- A missing or hash-mismatched snapshot is never sent, ingested, or regenerated.
- Snapshot cleanup waits for both Telegram and QADB completion.
- Manual report paths do not create QADB outbox work.

