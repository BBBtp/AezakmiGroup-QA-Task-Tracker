from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pdfplumber

from bot.handlers.doqa_reports import parse_doqa_run_id, parse_doqa_run_id_from_reference
from bot.integrations.doqa.client import _find_matching_runs
from bot.services.doqa_pdf.parser import parse_bugs
from bot.services.doqa_pdf.service import DoqaPdfService
from bot.services.doqa_report.pdf_renderer import (
    html_to_text,
    render_doqa_parser_input_pdf,
    render_doqa_report_pdf,
)
from bot.services.doqa_report.service import DoqaReportEmptyError, DoqaReportService


SAMPLE_REPORT = {
    "id": 385,
    "title": "Регрессионный прогон CRM",
    "description": "Проверка <b>основных</b> сценариев",
    "testCount": 2,
    "bugCount": 1,
    "progress": {"passed": 1, "failed": 1, "broken": 0},
    "configurations": [{"value": "Chrome"}],
    "elements": [
        {
            "id": 10,
            "title": "Создание сделки",
            "status": "failed",
            "content": "<p>Шаг 1</p><p>Ожидаемый результат</p>",
            "bugs": [
                {
                    "id": 77,
                    "title": "Не сохраняется сделка",
                    "content": "<p>Форма показывает ошибку</p>",
                }
            ],
        }
    ],
}


class FakeDoqaClient:
    async def find_run_by_title_id(self, external_id: int):
        self.requested_external_id = external_id
        return {"id": 385, "name": f"Фаст-трек | ID {external_id} | Проект"}

    async def get_full_report(self, run_id: int):
        self.requested_run_id = run_id
        return SAMPLE_REPORT


class DoqaReportCommandTests(unittest.TestCase):
    def test_extracts_run_id_from_command(self) -> None:
        self.assertEqual(parse_doqa_run_id("/zip 385"), 385)
        self.assertEqual(parse_doqa_run_id("/zip@task_bot 42"), 42)
        self.assertEqual(parse_doqa_run_id("/doqa_report 385"), 385)
        self.assertEqual(parse_doqa_run_id("/doqa_report@task_bot 42"), 42)

    def test_rejects_missing_or_extra_arguments(self) -> None:
        self.assertIsNone(parse_doqa_run_id("/zip"))
        self.assertIsNone(parse_doqa_run_id("/zip 1 later"))
        self.assertIsNone(parse_doqa_run_id("/report 385"))
        self.assertIsNone(parse_doqa_run_id("/doqa_report"))
        self.assertIsNone(parse_doqa_run_id("/doqa_report 1 later"))

    def test_extracts_run_id_from_replied_message(self) -> None:
        self.assertEqual(
            parse_doqa_run_id_from_reference(
                "https://j8n4sm.doqa.app/ru/home/detail/2/2/runs/385"
            ),
            385,
        )
        self.assertEqual(parse_doqa_run_id_from_reference("Прогон #42 завершён"), 42)
        self.assertIsNone(parse_doqa_run_id_from_reference("Задача 42 завершена"))

    def test_finds_exact_external_id_in_nested_run_listing(self) -> None:
        listing = {
            "data": {
                "data": {"id": 14, "name": "Корень", "isFolder": True},
                "children": [
                    {"data": {"id": 440, "name": "ID 67 | Другой"}},
                    {"data": {"id": 441, "name": "Фаст-трек | ID 671 | Chat AI"}},
                    {"data": {"id": 442, "name": "Фаст-трек | ID 6710 | Другой"}},
                ],
            }
        }

        matches = list(_find_matching_runs(listing, 671))

        self.assertEqual([run["id"] for run in matches], [441])


class DoqaPdfRendererTests(unittest.TestCase):
    def test_html_is_converted_to_plain_text(self) -> None:
        self.assertEqual(html_to_text("<p>Первый</p><p>Второй &amp; третий</p>"), "Первый\n\nВторой & третий")

    def test_renderer_creates_readable_cyrillic_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.pdf"
            render_doqa_report_pdf(SAMPLE_REPORT, output)

            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            with pdfplumber.open(output) as document:
                text = "\n".join(page.extract_text() or "" for page in document.pages)
            self.assertIn("Регрессионный прогон CRM", text)
            self.assertIn("Не сохраняется сделка", text)

    def test_internal_pdf_is_accepted_by_existing_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "parser-input.pdf"
            render_doqa_parser_input_pdf(SAMPLE_REPORT, output)

            parsed = parse_bugs(output)

            self.assertEqual([bug.bug_id for bug in parsed.bugs], ["77"])
            self.assertEqual(parsed.bugs[0].title, "Не сохраняется сделка")


class DoqaReportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_builds_link_and_cleans_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeDoqaClient()
            parser = DoqaPdfService(
                Path(directory) / "runs",
                max_input_bytes=2 * 1024 * 1024,
                max_pages=20,
            )
            service = DoqaReportService(
                client,
                parser,
                "https://doqa.example/runs/{run_id}",
            )

            result = await service.create_report(671)

            self.assertEqual(client.requested_external_id, 671)
            self.assertEqual(client.requested_run_id, 385)
            self.assertEqual(result.external_id, 671)
            self.assertEqual(result.run_url, "https://doqa.example/runs/385")
            self.assertEqual(result.test_count, 2)
            self.assertEqual(result.bug_count, 1)
            self.assertEqual(result.parsed_bug_count, 1)
            self.assertTrue(result.archive_path.is_file())

            service.cleanup(result)
            self.assertFalse(result.parser_run.directory.exists())

    async def test_service_does_not_return_empty_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            closed_report = {
                **SAMPLE_REPORT,
                "elements": [
                    {
                        **SAMPLE_REPORT["elements"][0],
                        "bugs": [{**SAMPLE_REPORT["elements"][0]["bugs"][0], "status": "closed"}],
                    }
                ],
            }

            class ClosedReportClient:
                async def find_run_by_title_id(self, external_id: int):
                    return {"id": 385, "name": f"ID {external_id}"}

                async def get_full_report(self, run_id: int):
                    return closed_report

            parser = DoqaPdfService(
                Path(directory) / "runs",
                max_input_bytes=2 * 1024 * 1024,
                max_pages=20,
            )
            service = DoqaReportService(
                ClosedReportClient(),
                parser,
                "https://doqa.example/runs/{run_id}",
            )

            with self.assertRaisesRegex(DoqaReportEmptyError, "нет открытых багов"):
                await service.create_report(385)
