from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from bot.web import (
    PendingDoqaDownload,
    _get_doqa_download,
    doqa_download_handler,
    doqa_report_handler,
    miniapp_auth_middleware,
)


class FakeRequest:
    def __init__(self, app: dict, *, payload: object | None = None, token: str = "") -> None:
        self.app = app
        self._payload = payload
        self.match_info = {"token": token}
        self.path = f"/api/doqa/download/{token}"

    async def json(self) -> object:
        return self._payload


class FakeManualReportService:
    def __init__(self, archive_path: Path) -> None:
        self.archive_path = archive_path
        self.cleaned = False

    async def create_report(self, external_id: int):
        return SimpleNamespace(
            archive_path=self.archive_path,
            run_id=812,
            parsed_bug_count=3,
        )

    def cleanup(self, result) -> None:
        self.cleaned = True


class DoqaWebDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_report_returns_https_compatible_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "report.zip"
            archive_path.write_bytes(b"zip-content")
            service = FakeManualReportService(archive_path)
            app = {
                "doqa_report_service": service,
                "doqa_downloads": {},
            }

            create_response = await doqa_report_handler(
                FakeRequest(app, payload={"external_id": 467})  # type: ignore[arg-type]
            )
            payload = json.loads(create_response.text)

            self.assertTrue(payload["download_url"].startswith("/api/doqa/download/"))
            self.assertNotIn("blob:", payload["download_url"])
            self.assertEqual(payload["filename"], "doqa_467_run_812.zip")
            self.assertTrue(service.cleaned)

            token = payload["download_url"].rsplit("/", 1)[-1]
            download_response = await doqa_download_handler(
                FakeRequest(app, token=token)  # type: ignore[arg-type]
            )

            self.assertEqual(download_response.body, b"zip-content")
            self.assertEqual(download_response.content_type, "application/zip")
            self.assertIn("doqa_467_run_812.zip", download_response.headers["Content-Disposition"])

    async def test_token_download_does_not_require_miniapp_cookie(self) -> None:
        request = FakeRequest({}, token="secret-token")

        async def handler(_request):
            return web.Response(status=200)

        response = await miniapp_auth_middleware(request, handler)  # type: ignore[arg-type]

        self.assertEqual(response.status, 200)

    def test_expired_download_is_removed(self) -> None:
        app = {
            "doqa_downloads": {
                "expired": PendingDoqaDownload(
                    data=b"zip",
                    filename="old.zip",
                    bug_count=1,
                    run_id=1,
                    expires_at=time.monotonic() - 1,
                )
            }
        }

        self.assertIsNone(_get_doqa_download(app, "expired"))  # type: ignore[arg-type]
        self.assertEqual(app["doqa_downloads"], {})
