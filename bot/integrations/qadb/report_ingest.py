from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BUCKET = "qa-reports"
RETRIABLE_STATUS = {429, 500, 502, 503, 504}
KNOWN_ARTIFACTS = (
    re.compile(r"^bugs\.json$", re.I),
    re.compile(r"^INDEX\.md$", re.I),
    re.compile(r"^bugs_report\.docx$", re.I),
    re.compile(r"^bugs/[^/]+\.md$", re.I),
    re.compile(r"^doqa_run_\d+[^/]*\.pdf$", re.I),
    re.compile(r"^attachments/.+$"),
)
PDF_DATE_RE = re.compile(rb"/(?:CreationDate|ModDate)\s*\(\s*D:(\d{14})(Z|[+-]\d{2}'?\d{2}'?)?")


class QadbReportIngestError(RuntimeError):
    pass


class QadbReportIngestor:
    """Upload a generated DoQA archive and its bugs to QADB."""

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        report_timezone: str = "+03:00",
        timeout_seconds: int = 60,
    ) -> None:
        self.url = url.rstrip("/")
        self.service_key = service_key
        self.report_timezone = report_timezone
        self.timeout_seconds = timeout_seconds

    def ingest(self, archive_path: Path, project_ref: str, run_id: int | str) -> dict[str, Any]:
        ref = _normalize_project_ref(project_ref)
        files = _read_archive(archive_path)
        bugs = _parse_bugs(files, ref)
        report_at, time_source = _report_time(files, self.report_timezone)
        storage_path = f"{ref}/{run_id}"

        self._ensure_bucket()
        for name, data in sorted(files.items()):
            self._upload(f"{storage_path}/{name}", data)

        report_row = {
            "project_ref_raw": ref,
            "run_id": str(run_id),
            "report_at": report_at.isoformat(),
            "report_date": report_at.date().isoformat(),
            "report_time_source": time_source,
            "source": "doqa",
            "bug_count": len(bugs),
            "storage_path": storage_path,
            "index_md": _decode(files.get("INDEX.md")),
            "raw": json.loads(files["bugs.json"].decode("utf-8")),
            "content_hash": _content_hash(files),
        }
        saved = self._rest(
            "POST",
            "qa_reports",
            payload=[report_row],
            query={"on_conflict": "project_ref_raw,run_id"},
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not saved:
            raise QadbReportIngestError("QADB не вернула сохранённый отчёт")
        report_id = saved[0]["id"]
        self._replace_bugs(report_id, bugs)
        return {"report_id": report_id, "bug_count": len(bugs), "storage_path": storage_path}

    def _replace_bugs(self, report_id: str, bugs: list[dict[str, Any]]) -> None:
        for start in range(0, len(bugs), 100):
            self._rest(
                "POST",
                "qa_bugs",
                payload=[dict(bug, report_id=report_id) for bug in bugs[start : start + 100]],
                query={"on_conflict": "report_id,external_id"},
                prefer="resolution=merge-duplicates,return=minimal",
            )
        stored = self._rest(
            "GET", "qa_bugs", query={"select": "external_id", "report_id": f"eq.{report_id}"}
        ) or []
        fresh = {bug["external_id"] for bug in bugs}
        stale = sorted({row["external_id"] for row in stored} - fresh)
        for start in range(0, len(stale), 50):
            values = ",".join(json.dumps(value) for value in stale[start : start + 50])
            self._rest(
                "DELETE",
                "qa_bugs",
                query={"report_id": f"eq.{report_id}", "external_id": f"in.({values})"},
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        target = f"{self.url}{path}"
        if query:
            target += "?" + urllib.parse.urlencode(query)
        for attempt in range(3):
            request = urllib.request.Request(target, data=body, method=method)
            request.add_header("apikey", self.service_key)
            request.add_header("Authorization", f"Bearer {self.service_key}")
            for name, value in (headers or {}).items():
                request.add_header(name, value)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                raw = error.read()
                if error.code not in RETRIABLE_STATUS or attempt == 2:
                    return error.code, raw
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 2:
                    raise QadbReportIngestError(f"QADB недоступна: {getattr(error, 'reason', error)}") from error
            time.sleep(2 * (attempt + 1))
        raise QadbReportIngestError("QADB недоступна")

    def _rest(
        self,
        method: str,
        table: str,
        *,
        payload: Any = None,
        query: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        status, raw = self._request(method, f"/rest/v1/{table}", body=body, headers=headers, query=query)
        if status >= 300:
            raise QadbReportIngestError(
                f"{method} {table} -> HTTP {status}: {raw[:500].decode('utf-8', 'replace')}"
            )
        return json.loads(raw) if raw else None

    def _ensure_bucket(self) -> None:
        status, raw = self._request(
            "POST",
            "/storage/v1/bucket",
            body=json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        if status < 300 or status == 409 or b"already exists" in raw.lower():
            return
        raise QadbReportIngestError(f"Бакет {BUCKET} недоступен: HTTP {status}")

    def _upload(self, path: str, data: bytes) -> None:
        quoted = urllib.parse.quote(path, safe="/")
        status, raw = self._request(
            "POST",
            f"/storage/v1/object/{BUCKET}/{quoted}",
            body=data,
            headers={"Content-Type": mimetypes.guess_type(path)[0] or "application/octet-stream", "x-upsert": "true"},
        )
        if status >= 300:
            raise QadbReportIngestError(
                f"Загрузка {path} -> HTTP {status}: {raw[:300].decode('utf-8', 'replace')}"
            )


def _read_archive(path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path) as archive:
            files = {
                info.filename.replace("\\", "/"): archive.read(info)
                for info in archive.infolist()
                if not info.is_dir() and not info.filename.startswith("__MACOSX/")
            }
    except zipfile.BadZipFile as error:
        raise QadbReportIngestError("ZIP-отчёт повреждён") from error
    known = {name: data for name, data in files.items() if any(pattern.match(name) for pattern in KNOWN_ARTIFACTS)}
    if "bugs.json" not in known:
        raise QadbReportIngestError("В ZIP-отчёте нет bugs.json")
    return known


def _normalize_project_ref(value: str) -> str:
    text = re.sub(r"^(?:id|проект|project)\s*[:#]?\s*", "", str(value).strip(), flags=re.I)
    text = text.lstrip("#").strip().lower()
    if not text:
        raise QadbReportIngestError("Пустой project_ref")
    return text


def _parse_bugs(files: dict[str, bytes], project_ref: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(files["bugs.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QadbReportIngestError(f"bugs.json не читается: {error}") from error
    raw_bugs = payload.get("bugs") if isinstance(payload, dict) else payload
    if not isinstance(raw_bugs, list):
        raise QadbReportIngestError("bugs.json должен содержать список bugs")
    bodies = {
        Path(name).stem.removeprefix("bug-"): data.decode("utf-8", "replace")
        for name, data in files.items()
        if name.startswith("bugs/bug-") and name.endswith(".md")
    }
    result = []
    seen = set()
    for raw in raw_bugs:
        if not isinstance(raw, dict):
            continue
        external_id = str(raw.get("id") or "").strip() or "h-" + hashlib.sha256(
            f"{raw.get('title')}|{raw.get('description')}".encode()
        ).hexdigest()[:10]
        if external_id in seen:
            continue
        seen.add(external_id)
        result.append({
            "bug_key": f"{project_ref}:{external_id}", "external_id": external_id,
            "title": _clean(raw.get("title")), "priority": _clean(raw.get("priority")),
            "status": (_clean(raw.get("status")) or "open").lower(),
            "description": _clean(raw.get("description")),
            "steps": raw.get("steps") if isinstance(raw.get("steps"), list) else [],
            "expected": _clean(raw.get("expected")), "actual": _clean(raw.get("actual")),
            "attachments": raw.get("attachments") if isinstance(raw.get("attachments"), list) else [],
            "body_md": bodies.get(external_id),
        })
    return result


def _report_time(files: dict[str, bytes], fallback_timezone: str) -> tuple[datetime, str]:
    for name, data in sorted(files.items()):
        if not name.lower().endswith(".pdf"):
            continue
        match = PDF_DATE_RE.search(data)
        if match:
            moment = datetime.strptime(match.group(1).decode(), "%Y%m%d%H%M%S")
            zone = (match.group(2) or b"Z").decode().replace("'", "")
            if zone.upper() == "Z":
                offset = timezone.utc
            else:
                delta = timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5]))
                offset = timezone(-delta if zone[0] == "-" else delta)
            return moment.replace(tzinfo=offset).astimezone(timezone.utc), "pdf"
    _parse_timezone(fallback_timezone)  # Validate the configured tester offset.
    return datetime.now(timezone.utc), "fallback"


def _parse_timezone(value: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", value.strip())
    if not match:
        raise QadbReportIngestError(
            f"QADB_REPORT_TZ не разобран: {value!r}; нужен вид +03:00 или -0530"
        )
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return timezone(-delta if match.group(1) == "-" else delta)


def _content_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        if name.endswith((".json", ".md")):
            digest.update(name.encode())
            digest.update(files[name])
    return digest.hexdigest()


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _decode(value: bytes | None) -> str | None:
    return value.decode("utf-8", "replace") if value is not None else None
