"""Small, fail-closed queue between the Telegram Mini App and a Mac Codex worker."""

from __future__ import annotations

import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timezone

from aiohttp import web
from sqlalchemy import func, select

from bot.db.models import CodexJob, CodexJobStatus, CodexRunSnapshot, CodexRunEvent

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
TERMINAL = {"completed", "failed", "interrupted"}
TELEMETRY = {"published", "publish_failed", "local"}
ERROR_CODES = {"codex_failed", "worker_error", "network_error", "telemetry_error"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(job: CodexJob) -> dict:
    signal = job.heartbeat_at or job.started_at
    stale = job.status is CodexJobStatus.RUNNING and signal is not None and (
        _now() - signal.replace(tzinfo=signal.tzinfo or timezone.utc)
    ).total_seconds() > 90
    return {
        "id": job.id,
        "issue_key": job.issue_key,
        "status": "unknown" if stale else job.status.value,
        "requested_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "telemetry_status": job.telemetry_status,
        "error_code": job.error_code,
    }


def require_user(request: web.Request) -> int:
    user = request.get("miniapp_user") or {}
    user_id = user.get("id")
    allowed = request.app["settings"].codex_allowed_user_ids
    if not isinstance(user_id, int) or user_id not in allowed:
        raise web.HTTPForbidden(text="Codex jobs are not enabled for this user")
    return user_id


def _worker(request: web.Request) -> None:
    expected = request.app["settings"].codex_worker_token
    supplied = request.headers.get("Authorization", "")
    if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise web.HTTPUnauthorized(text="Worker authentication required")


def _claim_matches(job: CodexJob, token: str) -> bool:
    return bool(job.claim_token and isinstance(token, str) and hmac.compare_digest(job.claim_token, token))


async def list_jobs(request: web.Request) -> web.Response:
    user_id = require_user(request)
    with request.app["session_factory"]() as session:
        jobs = session.scalars(
            select(CodexJob).where(CodexJob.requested_by_user_id == user_id)
            .order_by(CodexJob.created_at.desc()).limit(30)
        ).all()
        return web.json_response({"jobs": [_json(job) for job in jobs]})


async def create_job(request: web.Request) -> web.Response:
    user_id = require_user(request)
    try:
        payload = await request.json()
        issue_key = payload["issue_key"]
        job_id = str(uuid.UUID(payload["id"]))
    except (KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid Codex job")
    if not isinstance(issue_key, str) or not ISSUE_KEY.fullmatch(issue_key) or len(issue_key) > 40:
        raise web.HTTPBadRequest(text="Invalid issue key")
    with request.app["session_factory"]() as session:
        existing = session.get(CodexJob, job_id)
        if existing:
            if existing.requested_by_user_id != user_id or existing.issue_key != issue_key:
                raise web.HTTPConflict(text="Job ID already used")
            return web.json_response({"job": _json(existing)})
        active = session.scalar(select(func.count()).select_from(CodexJob).where(
            CodexJob.requested_by_user_id == user_id,
            CodexJob.status.in_([CodexJobStatus.QUEUED, CodexJobStatus.RUNNING]),
        ))
        if active:
            raise web.HTTPConflict(text="Finish the current Codex job before starting another")
        job = CodexJob(id=job_id, issue_key=issue_key, requested_by_user_id=user_id,
                       status=CodexJobStatus.QUEUED)
        session.add(job)
        session.commit()
        session.refresh(job)
        return web.json_response({"job": _json(job)}, status=201)


async def claim_job(request: web.Request) -> web.Response:
    _worker(request)
    with request.app["session_factory"]() as session:
        with session.begin():
            job = session.scalar(
                select(CodexJob).where(CodexJob.status == CodexJobStatus.QUEUED)
                .order_by(CodexJob.created_at, CodexJob.id)
                .with_for_update(skip_locked=True).limit(1)
            )
            if job is None:
                return web.json_response({"job": None})
            job.status = CodexJobStatus.RUNNING
            job.claim_token = secrets.token_urlsafe(32)
            job.started_at = _now()
            job.heartbeat_at = job.started_at
            result = {"id": job.id, "issue_key": job.issue_key, "claim_token": job.claim_token}
    return web.json_response({"job": result})


async def heartbeat_job(request: web.Request) -> web.Response:
    _worker(request)
    payload = await request.json()
    token = payload.get("claim_token") if isinstance(payload, dict) else None
    with request.app["session_factory"]() as session:
        job = session.get(CodexJob, request.match_info["job_id"])
        if not job or job.status is not CodexJobStatus.RUNNING or not _claim_matches(job, token):
            raise web.HTTPConflict(text="Job is not claimed by this worker")
        job.heartbeat_at = _now()
        session.commit()
    return web.json_response({"ok": True})


async def complete_job(request: web.Request) -> web.Response:
    _worker(request)
    payload = await request.json()
    if not isinstance(payload, dict) or payload.get("status") not in TERMINAL or payload.get("telemetry") not in TELEMETRY:
        raise web.HTTPBadRequest(text="Invalid Codex result")
    error_code = payload.get("error_code")
    if error_code is not None and error_code not in ERROR_CODES:
        raise web.HTTPBadRequest(text="Invalid error code")
    with request.app["session_factory"]() as session:
        job = session.get(CodexJob, request.match_info["job_id"])
        if not job or not _claim_matches(job, payload.get("claim_token")):
            raise web.HTTPConflict(text="Job is not claimed by this worker")
        if job.status.value in TERMINAL:
            if job.status.value != payload["status"]:
                raise web.HTTPConflict(text="Job already finished differently")
            return web.json_response({"job": _json(job)})
        if job.status is not CodexJobStatus.RUNNING:
            raise web.HTTPConflict(text="Job is not running")
        job.status = CodexJobStatus(payload["status"])
        job.telemetry_status = payload["telemetry"]
        job.error_code = error_code
        job.finished_at = _now()
        session.commit()
        return web.json_response({"job": _json(job)})


async def upload_telemetry(request: web.Request) -> web.Response:
    _worker(request)
    if request.content_length and request.content_length > 512 * 1024:
        raise web.HTTPRequestEntityTooLarge(max_size=512 * 1024, actual_size=request.content_length)
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list) or len(payload["events"]) > 100:
        raise web.HTTPBadRequest(text="Invalid telemetry batch")
    from bot.office_data import _event, _manifest
    try:
        manifest = _manifest(payload.get("manifest"))
        events = [_event(value, manifest["issueKey"], manifest["runId"]) for value in payload["events"]]
    except (ValueError, TypeError, KeyError):
        raise web.HTTPBadRequest(text="Invalid telemetry data")
    if manifest["runId"] != request.match_info["job_id"]:
        raise web.HTTPBadRequest(text="Telemetry run ID mismatch")
    with request.app["session_factory"]() as session:
        job = session.get(CodexJob, manifest["runId"])
        if not job or job.issue_key != manifest["issueKey"] or not _claim_matches(job, payload.get("claim_token")):
            raise web.HTTPConflict(text="Job is not claimed by this worker")
        snapshot = session.get(CodexRunSnapshot, manifest["runId"])
        serialized = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        if snapshot is None:
            session.add(CodexRunSnapshot(run_id=manifest["runId"], issue_key=manifest["issueKey"], manifest_json=serialized))
        else:
            snapshot.manifest_json = serialized
        for event in events:
            encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            previous = session.get(CodexRunEvent, (manifest["runId"], event["seq"]))
            if previous:
                if previous.payload_json != encoded:
                    raise web.HTTPConflict(text="Event sequence already contains different data")
            else:
                session.add(CodexRunEvent(run_id=manifest["runId"], seq=event["seq"], payload_json=encoded))
        session.commit()
    return web.json_response({"ok": True, "accepted": len(events)})
