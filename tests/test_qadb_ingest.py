from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from bot.integrations.qadb import QadbReportIngestor


class RecordingIngestor(QadbReportIngestor):
    def __init__(self) -> None:
        super().__init__("https://qadb.example", "secret")
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


class QadbReportIngestorTests(unittest.TestCase):
    def test_archive_is_uploaded_and_rows_are_upserted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
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


if __name__ == "__main__":
    unittest.main()
