"""Read-only Agent Office projection from the private S3-compatible store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import zlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from aiohttp import web
from sqlalchemy import select

from bot.codex_channel import require_user
from bot.db.models import CodexRunSnapshot, CodexRunEvent

RUN_PREFIX = "factory/agent-runs/v1/"
EVENT_PREFIX = "factory/events"
ISSUE = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
RUN = re.compile(r"^[a-f0-9-]{36}$")
SEGMENT = re.compile(r"^segments/[0-9]{6}\.ndjson\.gz$")
SAFE_TEXT = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")
SAFE_BRANCH = re.compile(r"^[a-zA-Z0-9_./-]{1,120}$")
EVENT_TYPES = {"intake_evaluated", "draft_pr_created", "verification_completed", "stale_source_detected"}
STAGES = {"intake", "engineer", "runner"}
OUTCOMES = {"ready", "needs_information", "not_automatable", "created", "passed", "failed", "blocked", "stale"}
STATUSES = {"queued", "running", "completed", "failed", "interrupted", "unknown"}
SOURCE_TYPES = {"wrapper", "codex-exec"}
KINDS = {"run.started", "run.finished", "process.heartbeat", "stream.parse_error",
         "thread.started", "turn.started", "turn.completed", "turn.failed", "turn.interrupted",
         "codex.error", "source.unknown", "source.parse_error"}
KINDS.update(f"{name}.{phase}" for name in ("command", "file", "mcp", "web", "agent_message", "plan", "item")
             for phase in ("started", "updated", "completed"))
METRICS = {"candidates", "acceptanceCriteria", "coveredCriteria", "reviewIterations", "firstPassCi",
           "total", "passed", "failed", "broken", "skipped", "flaky", "retries"}
MAX_OBJECT = 256 * 1024


def create_reader(settings):
    values = (settings.office_minio_endpoint, settings.office_minio_bucket,
              settings.office_minio_access_key, settings.office_minio_secret_key)
    if not all(values):
        return None
    endpoint = urlparse(settings.office_minio_endpoint)
    if endpoint.scheme != "https" and not (endpoint.scheme == "http" and endpoint.hostname in {"127.0.0.1", "localhost", "crm-minio"}):
        raise ValueError("OFFICE_MINIO_ENDPOINT must use HTTPS or a local private endpoint")
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3", endpoint_url=settings.office_minio_endpoint,
        aws_access_key_id=settings.office_minio_access_key,
        aws_secret_access_key=settings.office_minio_secret_key,
        region_name=settings.office_minio_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}),
    )
    return Reader(client, settings.office_minio_bucket)


def _text(value):
    return value if isinstance(value, str) and SAFE_TEXT.fullmatch(value) else None


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _iso(value):
    return value if _stamp(value) else None


def _manifest(value):
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1 or
        not ISSUE.fullmatch(str(value.get("issueKey", ""))) or
        not RUN.fullmatch(str(value.get("runId", ""))) or
        not _stamp(value.get("startedAt")) or
        not isinstance(value.get("eventCount"), int) or value["eventCount"] < 0 or
        value.get("status") not in STATUSES):
        raise ValueError("Invalid manifest")
    signal = _stamp(value.get("lastProcessSignalAt"))
    stale = value["status"] == "running" and (signal is None or
        (datetime.now(timezone.utc) - signal.astimezone(timezone.utc)).total_seconds() > 60)
    branch = value.get("branch")
    if not isinstance(branch, str) or not SAFE_BRANCH.fullmatch(branch) or ".." in branch:
        branch = None
    if branch and re.search(r"sk-[a-z0-9-]{8,}|token|password|secret|bearer", branch, re.I):
        branch = None
    result = {
        "schemaVersion": 1, "runId": value["runId"], "issueKey": value["issueKey"],
        "correlationId": _text(value.get("correlationId")),
        "attempt": value.get("attempt") if isinstance(value.get("attempt"), int) else 1,
        "parentRunId": value.get("parentRunId") if RUN.fullmatch(str(value.get("parentRunId", ""))) else None,
        "codexThreadId": _text(value.get("codexThreadId")),
        "workflowRunId": _text(value.get("workflowRunId")),
        "workflowRunAttempt": value.get("workflowRunAttempt") if isinstance(value.get("workflowRunAttempt"), int) else None,
        "branch": branch, "baseCommit": _text(value.get("baseCommit")), "headCommit": _text(value.get("headCommit")),
        "stage": _text(value.get("stage")), "actor": _text(value.get("actor")),
        "startedAt": value["startedAt"], "lastActionAt": _iso(value.get("lastActionAt")),
        "lastProcessSignalAt": _iso(value.get("lastProcessSignalAt")), "finishedAt": _iso(value.get("finishedAt")),
        "eventCount": value["eventCount"], "status": "unknown" if stale else value["status"],
        "telemetry": value.get("telemetry") if value.get("telemetry") in {"local", "published", "publish_failed"} else "local",
        "telemetryError": "publish_failed" if value.get("telemetryError") == "publish_failed" else None,
    }
    if stale:
        result["derived"] = {"rule": "running_and_process_signal_older_than_60s", "source": "lastProcessSignalAt"}
    return result


def _event(value, issue_key, run_id):
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1 or
        value.get("issueKey") != issue_key or value.get("runId") != run_id or
        not isinstance(value.get("seq"), int) or value["seq"] < 1 or
        not re.fullmatch(r"agev_[a-f0-9]{32}", str(value.get("eventId", ""))) or
        value.get("source") not in SOURCE_TYPES or not _stamp(value.get("observedAt")) or
        not _stamp(value.get("occurredAt")) or value.get("kind") not in KINDS):
        raise ValueError("Invalid agent event")
    detail = value.get("detail") if isinstance(value.get("detail"), dict) else {}
    safe_detail = {key: _text(detail.get(key)) for key in
                   ("threadId", "tool", "server", "itemType", "code", "reason", "sandbox", "stage")
                   if _text(detail.get(key))}
    label = detail.get("label")
    if isinstance(label, str) and re.fullmatch(r"(?:command|pwd|git (?:status|diff|show|log)|npm (?:run|test|ci)(?: [a-z:]+)?|npx playwright test)", label):
        safe_detail["label"] = label
    for key in ("exitCode", "stderrBytes", "parseErrors", "durationMs"):
        if isinstance(detail.get(key), (int, float)) and not isinstance(detail[key], bool):
            safe_detail[key] = detail[key]
    for key in ("outputDigest", "diffDigest"):
        if isinstance(detail.get(key), str) and re.fullmatch(r"sha256:[a-f0-9]{64}", detail[key]):
            safe_detail[key] = detail[key]
    if isinstance(detail.get("contentOmitted"), bool):
        safe_detail["contentOmitted"] = detail["contentOmitted"]
    if isinstance(detail.get("changes"), list):
        safe_detail["changes"] = [
            {"path": change["path"], "kind": _text(change.get("kind"))}
            for change in detail["changes"][:100]
            if isinstance(change, dict) and isinstance(change.get("path"), str)
            and len(change["path"]) <= 250 and not change["path"].startswith("/")
            and ".." not in change["path"] and not re.search(r"\.env|\.auth|storage[-_.]?state|credentials?|secrets?|\.aws|token|password", change["path"], re.I)
        ]
    return {
        "schemaVersion": 1, "eventId": _text(value.get("eventId")), "runId": run_id, "issueKey": issue_key,
        "correlationId": _text(value.get("correlationId")), "attempt": value.get("attempt", 1),
        "seq": value["seq"], "occurredAt": value["occurredAt"], "observedAt": value["observedAt"],
        "source": value["source"], "sourceType": _text(value.get("sourceType")),
        "codexVersion": _text(value.get("codexVersion")), "kind": value["kind"],
        "actor": _text(value.get("actor")), "itemId": _text(value.get("itemId")),
        "parentItemId": _text(value.get("parentItemId")),
        "status": value.get("status") if value.get("status") in {"completed", "failed", "in_progress", "declined"} else None,
        "detail": safe_detail,
    }


def _factory_event(value):
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1 or
        value.get("type") not in EVENT_TYPES or value.get("stage") not in STAGES or
        value.get("outcome") not in OUTCOMES or not ISSUE.fullmatch(str(value.get("issueKey", ""))) or
        not _stamp(value.get("occurredAt")) or not _text(value.get("eventId")) or
        not _text(value.get("correlationId")) or
        not isinstance(value.get("fingerprint"), str) or
        not re.fullmatch(r"sha256:[a-f0-9]{64}", value["fingerprint"])):
        raise ValueError("Invalid factory event")
    links = value.get("links") if isinstance(value.get("links"), dict) else {}
    safe_links = {}
    for name in ("pullRequest", "githubRun", "report"):
        link = links.get(name)
        parsed = urlparse(link) if isinstance(link, str) else None
        safe_links[name] = link if parsed and parsed.scheme == "https" and not parsed.username and not parsed.password else None
    metrics = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
    failures = value.get("failureCategories") if isinstance(value.get("failureCategories"), dict) else {}
    return {
        "schemaVersion": 1, "eventId": value["eventId"], "occurredAt": value["occurredAt"],
        "correlationId": value["correlationId"], "type": value["type"],
        "stage": value["stage"], "outcome": value["outcome"], "issueKey": value["issueKey"],
        "requirementId": value.get("requirementId") if isinstance(value.get("requirementId"), int) else None,
        "caseId": value.get("caseId") if isinstance(value.get("caseId"), int) else None,
        "fingerprint": value["fingerprint"],
        "metrics": {key: item for key, item in metrics.items() if key in METRICS and isinstance(item, (int, bool))},
        "failureCategories": {key: item for key, item in failures.items() if isinstance(key, str) and re.fullmatch(r"[a-z0-9_-]{1,40}", key) and isinstance(item, int)},
        "links": safe_links,
    }


class Reader:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    def keys(self, prefix, limit):
        keys = []
        token = None
        while len(keys) < limit:
            args = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": min(1000, limit - len(keys))}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            keys.extend(item["Key"] for item in page.get("Contents", []))
            token = page.get("NextContinuationToken")
            if not token:
                break
        if token:
            raise ValueError("Office listing limit exceeded")
        return keys

    def prefixes(self, prefix, limit):
        found = []
        token = None
        while len(found) < limit:
            args = {"Bucket": self.bucket, "Prefix": prefix, "Delimiter": "/",
                    "MaxKeys": min(1000, limit - len(found))}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            found.extend(item["Prefix"] for item in page.get("CommonPrefixes", []))
            token = page.get("NextContinuationToken")
            if not token:
                break
        if token:
            raise ValueError("Office listing limit exceeded")
        return found

    def get(self, key, max_bytes=MAX_OBJECT):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        if response.get("ContentLength", 0) > max_bytes:
            raise ValueError("Office object too large")
        body = response["Body"]
        try:
            raw = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(raw) > max_bytes:
            raise ValueError("Office object too large")
        return raw

    def json(self, key):
        return json.loads(self.get(key))

    def runs(self):
        keys = []
        for issue_prefix in self.prefixes(RUN_PREFIX, 1000):
            for run_prefix in self.prefixes(issue_prefix, 1000):
                keys.append(run_prefix + "manifest.json")
                if len(keys) > 1000:
                    raise ValueError("Office listing limit exceeded")
        runs = []
        for key in keys:
            try:
                runs.append(_manifest(self.json(key)))
            except (ValueError, KeyError, TypeError):
                continue
        return sorted(runs, key=lambda item: item["startedAt"], reverse=True)[:50]

    def events(self, issue_key, run_id, after):
        prefix = f"{RUN_PREFIX}{issue_key.lower()}/{run_id}/"
        manifest = self.json(prefix + "manifest.json")
        _manifest(manifest)
        if manifest["issueKey"] != issue_key or manifest["runId"] != run_id:
            raise ValueError("Run identity mismatch")
        events = []
        for segment in manifest.get("segments", []):
            if segment.get("lastSeq", 0) <= after or segment.get("firstSeq", 0) > after + 100:
                continue
            name = segment.get("key", "")
            if not SEGMENT.fullmatch(name):
                raise ValueError("Invalid segment")
            body = self.get(prefix + name)
            if "sha256:" + hashlib.sha256(body).hexdigest() != segment.get("digest"):
                raise ValueError("Segment digest mismatch")
            unzip = zlib.decompressobj(16 + zlib.MAX_WBITS)
            plain = unzip.decompress(body, 2 * 1024 * 1024 + 1)
            if len(plain) > 2 * 1024 * 1024 or not unzip.eof:
                raise ValueError("Segment size limit exceeded")
            for line in plain.splitlines():
                event = _event(json.loads(line), issue_key, run_id)
                if event["seq"] > after and len(events) < 100:
                    events.append(event)
        next_seq = events[-1]["seq"] if events else after
        return {"events": events, "nextSeq": next_seq, "hasMore": manifest["eventCount"] > next_seq}

    def factory(self):
        events = []
        for key in self.keys(EVENT_PREFIX, 5000):
            if re.search(r"/afev_[a-f0-9]{32}\.json$", key):
                events.append(_factory_event(self.json(key)))
        events.sort(key=lambda item: (item["occurredAt"], item["eventId"]))
        return {"source": "minio", "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "events": events, "readinessByEventId": {}}


def _reader(request):
    require_user(request)
    reader = request.app.get("office_reader")
    if reader is None:
        raise web.HTTPServiceUnavailable(text="Agent Office storage is not configured")
    return reader


async def list_runs(request):
    require_user(request)
    source = request.query.get("source", "relay")
    if source == "relay":
        with request.app["session_factory"]() as session:
            rows = session.scalars(select(CodexRunSnapshot).order_by(CodexRunSnapshot.updated_at.desc()).limit(50)).all()
            runs = [json.loads(row.manifest_json) for row in rows]
        return web.json_response({"source": "relay", "fetchedAt": datetime.now(timezone.utc).isoformat(), "runs": runs},
                                 headers={"Cache-Control": "no-store"})
    if source != "minio":
        raise web.HTTPBadRequest(text="Unknown office source")
    reader = _reader(request)
    try:
        runs = await asyncio.to_thread(reader.runs)
    except Exception:
        raise web.HTTPServiceUnavailable(text="Agent runs are unavailable")
    return web.json_response({"source": "minio", "fetchedAt": datetime.now(timezone.utc).isoformat(), "runs": runs},
                             headers={"Cache-Control": "no-store"})


async def run_events(request):
    require_user(request)
    issue_key, run_id = request.match_info["issue_key"], request.match_info["run_id"]
    try:
        after = int(request.query.get("after", "0"))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid page")
    source = request.query.get("source", "relay")
    if (not ISSUE.fullmatch(issue_key) or not RUN.fullmatch(run_id) or after < 0 or
        source not in {"relay", "minio"}):
        raise web.HTTPBadRequest(text="Invalid run")
    if source == "relay":
        with request.app["session_factory"]() as session:
            snapshot = session.get(CodexRunSnapshot, run_id)
            if snapshot is None or snapshot.issue_key != issue_key:
                raise web.HTTPNotFound(text="Run not found")
            rows = session.scalars(select(CodexRunEvent).where(CodexRunEvent.run_id == run_id,
                                CodexRunEvent.seq > after).order_by(CodexRunEvent.seq).limit(100)).all()
            events = [json.loads(row.payload_json) for row in rows]
            next_seq = rows[-1].seq if rows else after
            manifest = json.loads(snapshot.manifest_json)
            has_more = manifest["eventCount"] > next_seq
        return web.json_response({"events": events, "nextSeq": next_seq, "hasMore": has_more},
                                 headers={"Cache-Control": "no-store"})
    reader = _reader(request)
    try:
        page = await asyncio.to_thread(reader.events, issue_key, run_id, after)
    except Exception:
        raise web.HTTPServiceUnavailable(text="Agent events are unavailable")
    return web.json_response(page, headers={"Cache-Control": "no-store"})


async def factory_events(request):
    reader = _reader(request)
    if request.query.get("source", "minio") != "minio":
        raise web.HTTPBadRequest(text="Only MinIO is available")
    try:
        feed = await asyncio.to_thread(reader.factory)
    except Exception:
        raise web.HTTPServiceUnavailable(text="Factory events are unavailable")
    return web.json_response(feed, headers={"Cache-Control": "no-store"})
