from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bot.config import load_settings
from bot.integrations.qadb import QadbReportIngestor


class RecordingIngestor(QadbReportIngestor):
    def __init__(self) -> None:
        super().__init__("https://qadb.example/db", "secret", "qadb")
        self.rest_calls = []
        self.uploads = []

    def _ensure_bucket(self) -> None:
        pass

    def _upload(self, path: str, data: bytes) -> None:
        self.uploads.append((path, data))

    def _rest(self, method, table, *, payload=None, query=None, prefer=None):
        self.rest_calls.append((method, table, payload, query, prefer))
        if table == "qa_reports":
            return [{"id": "report-1"}]
        if method == "GET" and table == "qa_bugs":
            return []
        return None


class RemoteDbProtocolIngestor(QadbReportIngestor):
    def __init__(self, *, bucket_exists: bool = True) -> None:
        super().__init__("https://qadb.example/db", "secret", "qadb")
        self.bucket_exists = bucket_exists
        self.calls: list[tuple[str, str, bytes | None, dict | None, dict | None]] = []

    def _request(self, method, path, *, body=None, headers=None, query=None):
        self.calls.append((method, path, body, headers, query))
        if method == "GET" and path == "/api/storage/qadb/bucket":
            buckets = [{"name": "qa-reports"}] if self.bucket_exists else []
            return 200, json.dumps(buckets).encode()
        if method == "POST" and path == "/api/projects/qadb/storage/buckets":
            self.bucket_exists = True
            return 201, b'{"bucket":{"name":"qa-reports"}}'
        if method == "POST" and path == "/api/data/qadb/qa_reports":
            return 201, b'{"inserted":1,"rows":[{"id":"report-1"}]}'
        if method == "POST" and path == "/api/data/qadb/qa_bugs":
            return 201, b'{"inserted":1,"rows":[]}'
        if method == "GET" and path == "/api/data/qadb/qa_bugs":
            return 200, b'{"rows":[],"total":0,"limit":50,"offset":0}'
        if method == "POST" and path.startswith("/api/storage/qadb/object/qa-reports/"):
            return 200, b'{"Key":"qa-reports/file","Id":"object-1"}'
        raise AssertionError(f"Unexpected request: {method} {path}")


class QadbReportIngestorTests(unittest.TestCase):
    def _archive(self, directory: str) -> Path:
        archive_path = Path(directory) / "report.zip"
        bugs = {
            "bugs": [
                {
                    "id": "77",
                    "title": "Не сохраняется сделка",
                    "status": "open",
                    "steps": [],
                    "attachments": [],
                }
            ]
        }
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("bugs.json", json.dumps(bugs, ensure_ascii=False))
            archive.writestr("INDEX.md", "# DoQA bugs")
            archive.writestr("bugs/bug-77.md", "# Bug 77")
            archive.writestr("notes.txt", "must not leave the bot")
        return archive_path

    def test_archive_is_uploaded_and_rows_are_upserted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._archive(directory)
            ingestor = RecordingIngestor()
            result = ingestor.ingest(archive_path, "ID 671", 385)

            self.assertEqual(result["report_id"], "report-1")
            self.assertEqual([path for path, _ in ingestor.uploads], [
                "671/385/INDEX.md",
                "671/385/bugs.json",
                "671/385/bugs/bug-77.md",
            ])
            report_call = next(call for call in ingestor.rest_calls if call[1] == "qa_reports")
            self.assertEqual(report_call[2][0]["project_ref_raw"], "671")
            bug_call = next(
                call for call in ingestor.rest_calls
                if call[0] == "POST" and call[1] == "qa_bugs"
            )
            self.assertEqual(bug_call[2][0]["bug_key"], "671:77")
            self.assertEqual(bug_call[2][0]["report_id"], "report-1")

    def test_remote_db_protocol_uses_project_scoped_data_and_storage_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ingestor = RemoteDbProtocolIngestor()
            result = ingestor.ingest(self._archive(directory), "ID 671", 385)

        paths = [(method, path) for method, path, *_ in ingestor.calls]
        self.assertEqual(result["report_id"], "report-1")
        self.assertIn(("GET", "/api/storage/qadb/bucket"), paths)
        self.assertIn(("POST", "/api/data/qadb/qa_reports"), paths)
        self.assertIn(("POST", "/api/data/qadb/qa_bugs"), paths)
        self.assertIn(("GET", "/api/data/qadb/qa_bugs"), paths)
        self.assertTrue(
            any(path.startswith("/api/storage/qadb/object/qa-reports/") for _, path in paths)
        )
        self.assertFalse(any("/rest/v1/" in path or "/storage/v1/" in path for _, path in paths))

    def test_missing_bucket_is_created_through_project_admin_api(self) -> None:
        ingestor = RemoteDbProtocolIngestor(bucket_exists=False)

        ingestor._ensure_bucket()

        self.assertIn(
            ("POST", "/api/projects/qadb/storage/buckets"),
            [(method, path) for method, path, *_ in ingestor.calls],
        )

    def test_qadb_project_slug_is_required_with_credentials(self) -> None:
        environment = {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///test.db",
            "QADB_URL": "https://qadb.example/db",
            "QADB_SERVICE_KEY": "secret",
        }
        with patch("bot.config.load_dotenv"), patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(ValueError, "QADB_PROJECT_SLUG"):
                load_settings()

    def test_qadb_project_slug_is_loaded_with_credentials(self) -> None:
        environment = {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///test.db",
            "QADB_URL": "https://qadb.example/db",
            "QADB_PROJECT_SLUG": "qadb",
            "QADB_SERVICE_KEY": "secret",
        }
        with patch("bot.config.load_dotenv"), patch.dict("os.environ", environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.qadb_project_slug, "qadb")


if __name__ == "__main__":
    unittest.main()
