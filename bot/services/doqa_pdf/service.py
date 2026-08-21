from __future__ import annotations

import asyncio
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pymupdf

from .parser import ParsedReport, parse_bugs, save_page_images
from .renderers import render_bug_files, render_docx, write_index, write_json


@dataclass(frozen=True, slots=True)
class DoqaRun:
    run_id: str
    directory: Path
    input_pdf: Path


@dataclass(frozen=True, slots=True)
class DoqaParseResult:
    report: ParsedReport
    docx_path: Path
    archive_path: Path


class DoqaPdfService:
    def __init__(
        self,
        output_root: Path,
        *,
        max_input_bytes: int,
        max_pages: int,
        concurrency: int = 1,
    ) -> None:
        self.output_root = output_root
        self.max_input_bytes = max_input_bytes
        self.max_pages = max_pages
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    def prepare_run(self, original_filename: str | None) -> DoqaRun:
        run_id = uuid4().hex
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        filename = _safe_pdf_filename(original_filename)
        return DoqaRun(run_id=run_id, directory=run_dir, input_pdf=run_dir / filename)

    async def process(self, run: DoqaRun) -> DoqaParseResult:
        async with self._semaphore:
            return await asyncio.to_thread(self._process_sync, run)

    def cleanup(self, run: DoqaRun) -> None:
        resolved_root = self.output_root.resolve()
        resolved_run = run.directory.resolve()
        if resolved_root in resolved_run.parents and resolved_run.name == run.run_id:
            shutil.rmtree(resolved_run, ignore_errors=True)

    def _process_sync(self, run: DoqaRun) -> DoqaParseResult:
        self._validate_pdf(run.input_pdf)
        report = parse_bugs(run.input_pdf)
        save_page_images(run.input_pdf, report.bugs, run.directory)
        write_index(report, run.directory)
        render_bug_files(report, run.directory)
        write_json(report, run.directory)
        docx_path = render_docx(report, run.directory)
        archive_path = _build_zip(run.directory)
        return DoqaParseResult(report=report, docx_path=docx_path, archive_path=archive_path)

    def _validate_pdf(self, pdf_path: Path) -> None:
        size = pdf_path.stat().st_size
        if size == 0:
            raise ValueError("PDF-файл пустой")
        if size > self.max_input_bytes:
            limit_mb = self.max_input_bytes // (1024 * 1024)
            raise ValueError(f"PDF слишком большой. Максимальный размер: {limit_mb} МБ")
        with pdf_path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise ValueError("Файл не похож на PDF")
        try:
            with pymupdf.open(pdf_path) as document:
                if document.needs_pass:
                    raise ValueError("PDF защищён паролем")
                if document.page_count > self.max_pages:
                    raise ValueError(
                        f"В PDF {document.page_count} страниц. Максимум: {self.max_pages}"
                    )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Не удалось открыть PDF") from exc


def _safe_pdf_filename(original_filename: str | None) -> str:
    name = Path(original_filename or "report.pdf").name
    stem = re.sub(r"[^\w .-]+", "_", Path(name).stem, flags=re.UNICODE)
    stem = re.sub(r"\s+", "_", stem).strip("._") or "report"
    return f"{stem}.pdf"


def _build_zip(run_dir: Path) -> Path:
    archive_path = run_dir / "doqa_report.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path == archive_path or not path.is_file():
                continue
            archive.write(path, path.relative_to(run_dir))
    return archive_path
