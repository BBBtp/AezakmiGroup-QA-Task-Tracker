from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from bot.integrations.doqa import DoqaClient
from bot.services.doqa_pdf.service import DoqaPdfService, DoqaRun

from .pdf_renderer import render_doqa_parser_input_pdf


class DoqaReportEmptyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DoqaReportResult:
    external_id: int
    run_id: int
    title: str
    archive_path: Path
    run_url: str
    test_count: int
    bug_count: int
    parsed_bug_count: int
    parser_run: DoqaRun


class DoqaReportService:
    def __init__(
        self,
        client: DoqaClient,
        pdf_parser: DoqaPdfService,
        report_url_template: str,
        *,
        font_path: Path | None = None,
        concurrency: int = 1,
    ) -> None:
        self.client = client
        self.pdf_parser = pdf_parser
        self.report_url_template = report_url_template
        self.font_path = font_path
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    async def create_report(self, external_id: int) -> DoqaReportResult:
        async with self._semaphore:
            found_run = await self.client.find_run_by_title_id(external_id)
            run_id = int(found_run["id"])
            report = await self.client.get_full_report(run_id)
            actual_run_id = int(report.get("id") or run_id)
            parser_run = self.pdf_parser.prepare_run(f"doqa_run_{actual_run_id}.pdf")
            try:
                await asyncio.to_thread(
                    render_doqa_parser_input_pdf,
                    report,
                    parser_run.input_pdf,
                    font_path=self.font_path,
                )
                parsed = await self.pdf_parser.process(parser_run)
                if not parsed.report.bugs:
                    raise DoqaReportEmptyError(
                        f"В прогоне #{actual_run_id} нет открытых багов для архива"
                    )
            except Exception:
                self.pdf_parser.cleanup(parser_run)
                raise
            return DoqaReportResult(
                external_id=external_id,
                run_id=actual_run_id,
                title=str(report.get("title") or f"Прогон #{actual_run_id}"),
                archive_path=parsed.archive_path,
                run_url=self.report_url_template.format(run_id=actual_run_id),
                test_count=int(report.get("testCount") or 0),
                bug_count=int(report.get("bugCount") or 0),
                parsed_bug_count=len(parsed.report.bugs),
                parser_run=parser_run,
            )

    def cleanup(self, result: DoqaReportResult) -> None:
        self.pdf_parser.cleanup(result.parser_run)
