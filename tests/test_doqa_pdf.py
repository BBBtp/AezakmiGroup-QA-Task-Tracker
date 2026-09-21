from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf

from bot.handlers.doqa_documents import is_doqa_parse_caption
from bot.services.doqa_pdf.service import DoqaPdfService
from bot.services.doqa_pdf.parser import parse_bugs


class DoqaCaptionTests(unittest.TestCase):
    def test_explicit_parse_markers_are_supported(self) -> None:
        self.assertTrue(is_doqa_parse_caption("/parse"))
        self.assertTrue(is_doqa_parse_caption("/parse@task_bot"))
        self.assertTrue(is_doqa_parse_caption(" #DoQA "))

    def test_unrelated_caption_is_not_intercepted(self) -> None:
        self.assertFalse(is_doqa_parse_caption(None))
        self.assertFalse(is_doqa_parse_caption("обычный PDF"))
        self.assertFalse(is_doqa_parse_caption("/parse позже"))


class DoqaPdfServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_new_doqa_export_with_split_bug_icon_is_parsed(self) -> None:
        pages = [[
            "21/9/2026, 11:51 AM",
            "bu ГК Глеб Кальсин 21.09.2026 11:47",
            "g",
            "3717 AI Chat Companion / Экран чата и отправка сообщений",
            "Приоритет Статус",
            "Средний Открыт",
            "Описание:",
            "Проверки основного экрана общения.",
            "Шаги:",
            "Шаг 1: Отправить сообщение.",
            "Ожидаемый результат",
            "Сообщение отправлено.",
            "Фактический результат",
            "Сообщение зависло.",
        ]]

        with patch("bot.services.doqa_pdf.parser.extract_pages", return_value=pages):
            report = parse_bugs(Path("new-doqa-export.pdf"))

        self.assertEqual(len(report.bugs), 1)
        self.assertEqual(report.bugs[0].bug_id, "3717")
        self.assertEqual(report.bugs[0].status, "Открыт")
        self.assertEqual(report.bugs[0].actual, "Сообщение зависло.")

    async def test_process_creates_docx_json_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "runs"
            service = DoqaPdfService(
                output_root,
                max_input_bytes=2 * 1024 * 1024,
                max_pages=10,
            )
            run = service.prepare_run("../пример отчёта.PDF")
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), "DoQA report without bug blocks")
            document.save(run.input_pdf)
            document.close()

            result = await service.process(run)

            self.assertEqual(result.report.bugs, [])
            self.assertTrue(result.docx_path.is_file())
            self.assertTrue((run.directory / "bugs.json").is_file())
            self.assertTrue(result.archive_path.is_file())
            with zipfile.ZipFile(result.archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("bugs.json", names)
            self.assertIn("bugs_report.docx", names)
            self.assertNotIn("doqa_report.zip", names)

            service.cleanup(run)
            self.assertFalse(run.directory.exists())

    async def test_rejects_file_with_fake_pdf_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DoqaPdfService(
                Path(directory) / "runs",
                max_input_bytes=1024,
                max_pages=10,
            )
            run = service.prepare_run("report.pdf")
            run.input_pdf.write_text("not a pdf", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "не похож на PDF"):
                await service.process(run)

            service.cleanup(run)

    async def test_rejects_pdf_over_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DoqaPdfService(
                Path(directory) / "runs",
                max_input_bytes=2 * 1024 * 1024,
                max_pages=1,
            )
            run = service.prepare_run("report.pdf")
            document = pymupdf.open()
            document.new_page()
            document.new_page()
            document.save(run.input_pdf)
            document.close()

            with self.assertRaisesRegex(ValueError, "Максимум: 1"):
                await service.process(run)

            service.cleanup(run)
