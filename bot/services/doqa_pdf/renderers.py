"""Rendering layer for the parsed DoQA report.

We produce four artefacts:

* ``INDEX.md`` — human-readable list of bugs with links to per-bug files.
* ``bugs/bug-<id>.md`` — one Markdown file per bug. Front-matter is parseable
  YAML so agents can update fields programmatically without touching the body.
* ``bugs.json`` — machine-readable copy of the bug list.
* ``bugs_report.docx`` — Word document for developers who prefer Office.

A plain text file is optional and is only produced when the caller asks for it.

Run-level metadata (project, tester, statistics) is intentionally omitted —
agents and developers operate per-bug, so we keep noise out of every artefact.
"""

from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Inches, Pt, RGBColor

from .parser import Bug, ParsedReport, Step


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _yaml_scalar(value: str | int | None) -> str:
    """Render a YAML scalar that survives round-tripping through editors."""

    if value is None or value == "":
        return '""'
    if isinstance(value, int):
        return str(value)
    text = str(value)
    needs_quotes = any(ch in text for ch in ":#&*?{}[]|>%`@!,") or text.strip() != text
    if needs_quotes:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _format_steps_md(steps: list[Step]) -> str:
    if not steps:
        return "_не указаны_"
    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        number = step.number if step.number is not None else index
        lines.append(f"{number}. {step.text}")
    return "\n".join(lines)


def _format_paragraph(value: str, placeholder: str = "_не указано_") -> str:
    return value.strip() if value.strip() else placeholder


def _attachment_lines_md(bug: Bug, file_dir: Path) -> list[str]:
    if not bug.attachments:
        return ["_нет вложений_"]
    lines: list[str] = []
    for att in bug.attachments:
        if att.saved_path and att.saved_path.exists():
            try:
                rel = att.saved_path.relative_to(file_dir)
            except ValueError:
                rel = att.saved_path
            lines.append(f"- {att.source_name}")
            lines.append(f"  ![{att.source_name}]({rel})")
        else:
            lines.append(f"- {att.source_name}")
    return lines


def _bug_front_matter(bug: Bug) -> str:
    return (
        "---\n"
        f"id: {bug.bug_id}\n"
        f"title: {_yaml_scalar(bug.title)}\n"
        "---\n"
    )


def render_bug_markdown(bug: Bug, file_dir: Path) -> str:
    front_matter = _bug_front_matter(bug)
    attachments_md = "\n".join(_attachment_lines_md(bug, file_dir))

    body = f"""# Bug #{bug.bug_id} — {bug.title}

## Описание

{_format_paragraph(bug.description)}

## Шаги воспроизведения

{_format_steps_md(bug.steps)}

## Ожидаемый результат

{_format_paragraph(bug.expected, "_не указан_")}

## Фактический результат

{_format_paragraph(bug.actual, "_не указан_")}

## Вложения

{attachments_md}
"""
    return front_matter + "\n" + body


def render_bug_files(report: ParsedReport, output_dir: Path) -> list[Path]:
    bugs_dir = output_dir / "bugs"
    bugs_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for bug in report.bugs:
        path = bugs_dir / f"bug-{bug.bug_id}.md"
        content = render_bug_markdown(bug, file_dir=bugs_dir)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Index Markdown (bug list)
# ---------------------------------------------------------------------------


def render_index_markdown(report: ParsedReport) -> str:
    lines: list[str] = [
        "# DoQA bugs",
        "",
        f"Найдено багов: **{len(report.bugs)}**",
        "",
        "| # | ID | Приоритет | Статус | Название | Файл |",
        "|---|----|-----------|--------|----------|------|",
    ]
    for number, bug in enumerate(report.bugs, start=1):
        title = bug.title.replace("|", "\\|")
        lines.append(
            f"| {number} | #{bug.bug_id} | {bug.priority or '—'} | "
            f"{bug.status or '—'} | {title} | "
            f"[bug-{bug.bug_id}.md](bugs/bug-{bug.bug_id}.md) |"
        )
    lines.extend([
        "",
        "## Где какие данные",
        "",
        "- `bugs/bug-<id>.md` — описание бага: описание, шаги, ожидаемый/фактический результат, вложения. YAML front-matter содержит только `id` и `title` для машинной идентификации.",
        "- `bugs.json` — те же данные плюс `priority`, `status` и пути до вложений — для пайплайнов и автоматизаций.",
        "- `attachments/` — извлечённые из PDF скриншоты.",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def write_index(report: ParsedReport, output_dir: Path) -> Path:
    path = output_dir / "INDEX.md"
    path.write_text(render_index_markdown(report), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def render_json(report: ParsedReport, output_dir: Path) -> str:
    payload = {
        "bugs": [bug.to_dict(attachments_base=output_dir) for bug in report.bugs],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_json(report: ParsedReport, output_dir: Path) -> Path:
    path = output_dir / "bugs.json"
    path.write_text(render_json(report, output_dir), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Plain text (legacy)
# ---------------------------------------------------------------------------


def render_text(report: ParsedReport, output_dir: Path) -> str:
    lines: list[str] = [
        "Баги из DoQA отчета",
        f"Количество багов: {len(report.bugs)}",
        "",
    ]
    for number, bug in enumerate(report.bugs, start=1):
        lines.append(f"{number}. Баг #{bug.bug_id}: {bug.title}")
        lines.append(f"   - Приоритет: {bug.priority or 'не указан'}")
        lines.append(f"   - Статус: {bug.status or 'не указан'}")

        if bug.attachments:
            lines.append("   - Вложения:")
            for attachment in bug.attachments:
                if attachment.saved_path:
                    try:
                        saved_text = attachment.saved_path.relative_to(output_dir)
                    except ValueError:
                        saved_text = attachment.saved_path
                    lines.append(f"     - {attachment.source_name} -> {saved_text}")
                else:
                    lines.append(f"     - {attachment.source_name}")
        else:
            lines.append("   - Вложения: нет")

        lines.append(f"   - Описание: {bug.description or 'не указано'}")
        lines.append("   - Шаги:")
        if bug.steps:
            for step in bug.steps:
                prefix = f"Шаг {step.number}: " if step.number is not None else "- "
                lines.append(f"     - {prefix}{step.text}")
        else:
            lines.append("     - не указаны")
        lines.append(f"   - Ожидаемый результат: {bug.expected or 'не указан'}")
        lines.append(f"   - Фактический результат: {bug.actual or 'не указан'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_text(report: ParsedReport, output_dir: Path) -> Path:
    path = output_dir / "bugs_report.txt"
    path.write_text(render_text(report, output_dir), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _set_cell_text(cell, label: str, value: str) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(label)
    run.bold = True
    paragraph.add_run(value or "не указано")


def _add_bullet(document: Document, text: str) -> None:
    document.add_paragraph(text, style="List Bullet")


def render_docx(report: ParsedReport, output_dir: Path) -> Path:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    styles = document.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(10)
    styles["Title"].font.name = "Arial"
    styles["Heading 1"].font.name = "Arial"
    styles["Heading 1"].font.size = Pt(16)
    styles["Heading 1"].font.color.rgb = RGBColor(31, 41, 55)
    styles["Heading 2"].font.name = "Arial"
    styles["Heading 2"].font.size = Pt(12)
    styles["Heading 2"].font.color.rgb = RGBColor(31, 41, 55)

    title = document.add_heading("Баги из DoQA отчета", level=0)
    title.alignment = 0
    document.add_paragraph(f"Количество багов: {len(report.bugs)}")

    for number, bug in enumerate(report.bugs, start=1):
        if number > 1:
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

        document.add_heading(f"{number}. Баг #{bug.bug_id}: {bug.title}", level=1)

        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        _set_cell_text(table.cell(0, 0), "Приоритет: ", bug.priority)
        _set_cell_text(table.cell(0, 1), "Статус: ", bug.status)
        _set_cell_text(
            table.cell(0, 2),
            "Вложения: ",
            str(len(bug.attachments)) if bug.attachments else "нет",
        )

        document.add_heading("Описание", level=2)
        document.add_paragraph(bug.description or "не указано")

        document.add_heading("Шаги", level=2)
        if bug.steps:
            for step in bug.steps:
                prefix = f"Шаг {step.number}: " if step.number is not None else ""
                _add_bullet(document, f"{prefix}{step.text}")
        else:
            _add_bullet(document, "не указаны")

        document.add_heading("Ожидаемый результат", level=2)
        document.add_paragraph(bug.expected or "не указан")

        document.add_heading("Фактический результат", level=2)
        document.add_paragraph(bug.actual or "не указан")

        document.add_heading("Вложения", level=2)
        if not bug.attachments:
            document.add_paragraph("Нет вложений")
            continue

        for attachment in bug.attachments:
            document.add_paragraph(attachment.source_name, style="List Bullet")
            if attachment.saved_path and attachment.saved_path.exists():
                document.add_picture(str(attachment.saved_path), width=Inches(6.4))
            else:
                document.add_paragraph("Файл вложения не был найден")

    report_path = output_dir / "bugs_report.docx"
    document.save(report_path)
    return report_path
