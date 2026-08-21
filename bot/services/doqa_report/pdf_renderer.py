from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
)
FONT_BOLD_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
)

STATUS_LABELS = {
    "passed": "Пройдено",
    "failed": "Провалено",
    "broken": "Сломано",
    "blocked": "Заблокировано",
    "skipped": "Пропущено",
    "initial": "Не начато",
}


class _TextExtractor(HTMLParser):
    block_tags = {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: Any) -> str:
    if value is None:
        return ""
    parser = _TextExtractor()
    parser.feed(str(value))
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_doqa_report_pdf(
    report: dict[str, Any],
    output_path: Path,
    *,
    font_path: Path | None = None,
) -> Path:
    regular_font, bold_font = _register_fonts(font_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"DoQA run {report.get('id', '')}",
    )
    styles = _styles(regular_font, bold_font)
    story: list[Any] = []

    run_id = report.get("id", "")
    title = html_to_text(report.get("title")) or "Без названия"
    story.append(Paragraph(_escape(f"DoQA — прогон #{run_id}"), styles["TitleDoqa"]))
    story.append(Paragraph(_escape(title), styles["SubtitleDoqa"]))
    description = html_to_text(report.get("description"))
    if description:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_escape_multiline(description), styles["BodyDoqa"]))

    story.append(Spacer(1, 5 * mm))
    progress = report.get("progress") or {}
    stats = [["Показатель", "Значение"]]
    stats.append(["Тестов", str(report.get("testCount", 0))])
    stats.append(["Багов", str(report.get("bugCount", 0))])
    for key, label in STATUS_LABELS.items():
        if key in progress:
            stats.append([label, str(progress.get(key, 0))])
    story.append(_table(stats, regular_font, bold_font, (115 * mm, 45 * mm)))

    configurations = report.get("configurations") or []
    if configurations:
        values = [html_to_text(item.get("value") or item.get("title") or item.get("name")) for item in configurations]
        values = [value for value in values if value]
        if values:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Конфигурации", styles["HeadingDoqa"]))
            story.append(Paragraph(_escape(", ".join(values)), styles["BodyDoqa"]))

    elements = report.get("elements") or []
    if elements:
        story.append(PageBreak())
        story.append(Paragraph("Результаты тестов", styles["SectionDoqa"]))
    for index, element in enumerate(elements, start=1):
        _append_element(story, element, index, styles, regular_font, bold_font)

    document.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return output_path


def render_doqa_parser_input_pdf(
    report: dict[str, Any],
    output_path: Path,
    *,
    font_path: Path | None = None,
) -> Path:
    """Create a temporary PDF shaped for the existing DoQA bug parser."""

    regular_font, bold_font = _register_fonts(font_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = _styles(regular_font, bold_font)
    story: list[Any] = []
    bugs = [bug for element in report.get("elements") or [] for bug in element.get("bugs") or []]

    for index, bug in enumerate(bugs):
        if index:
            story.append(PageBreak())
        bug_id = str(bug.get("id") or "")
        title = html_to_text(bug.get("title")) or "Без названия"
        priority = html_to_text(bug.get("priority")) or "medium"
        status = html_to_text(bug.get("status")) or "Открыт"
        sections = extract_bug_sections(bug.get("content") or bug.get("description"))

        story.append(Paragraph("QA Bot 21.08.2026 12:00", styles["BodyDoqa"]))
        story.append(Paragraph(_escape(f"{bug_id} {title}"), styles["HeadingDoqa"]))
        story.append(Paragraph("Приоритет Статус", styles["BodyDoqa"]))
        story.append(Paragraph(_escape(f"{priority} {status}"), styles["BodyDoqa"]))
        for label, key in (
            ("Описание:", "description"),
            ("Шаги:", "steps"),
            ("Ожидаемый результат:", "expected"),
            ("Фактический результат:", "actual"),
        ):
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(label, styles["HeadingDoqa"]))
            value = sections.get(key, "")
            if key == "steps":
                value = _normalize_step_lines(value)
            story.append(Paragraph(_escape_multiline(value or "не указано"), styles["BodyDoqa"]))

        attachments = bug.get("attachments") or []
        if attachments:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph("Вложения:", styles["HeadingDoqa"]))
            for attachment in attachments:
                name = html_to_text(
                    attachment.get("originalName") or attachment.get("name") or "вложение"
                )
                story.append(Paragraph(_escape(f"Скриншот ошибки: {name}"), styles["BodyDoqa"]))

    if not bugs:
        story.append(Paragraph("Отчёт не содержит багов", styles["HeadingDoqa"]))

    document.build(story)
    return output_path


def extract_bug_sections(value: Any) -> dict[str, str]:
    text = html_to_text(value)
    result = {"description": "", "steps": "", "expected": "", "actual": ""}
    if not text:
        return result
    labels = {
        "описание": "description",
        "description": "description",
        "шаги": "steps",
        "steps": "steps",
        "ожидаемый результат": "expected",
        "expected result": "expected",
        "фактический результат": "actual",
        "actual result": "actual",
    }
    pattern = re.compile(
        r"(?im)^\s*(описание|description|шаги|steps|ожидаемый результат|expected result|"
        r"фактический результат|actual result)\s*:?\s*$"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        result["description"] = text
        return result
    prefix = text[: matches[0].start()].strip()
    if prefix:
        result["description"] = prefix
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = labels[match.group(1).casefold()]
        content = text[start:end].strip()
        result[key] = "\n".join(part for part in (result[key], content) if part)
    return result


def _normalize_step_lines(value: str) -> str:
    lines = []
    for line in value.splitlines():
        match = re.match(r"^\s*(\d+)[.)]\s*(.+)$", line)
        lines.append(f"Шаг {match.group(1)}: {match.group(2)}" if match else line)
    return "\n".join(lines)


def _append_element(story, element, index, styles, regular_font, bold_font) -> None:
    element_id = element.get("id") or element.get("caseId") or element.get("testCaseId") or ""
    title = html_to_text(
        element.get("title")
        or element.get("name")
        or element.get("caseTitle")
        or f"Тест {element_id}"
    )
    status = html_to_text(element.get("status")) or "—"
    story.append(Paragraph(_escape(f"{index}. {title}"), styles["HeadingDoqa"]))
    story.append(
        _table(
            [["ID", str(element_id or "—")], ["Статус", STATUS_LABELS.get(status, status)]],
            regular_font,
            bold_font,
            (35 * mm, 125 * mm),
        )
    )
    content = html_to_text(element.get("content") or element.get("description"))
    if content:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(_escape_multiline(content), styles["BodyDoqa"]))

    for bug in element.get("bugs") or []:
        bug_id = bug.get("id", "")
        bug_title = html_to_text(bug.get("title")) or "Без названия"
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_escape(f"Баг #{bug_id}: {bug_title}"), styles["BugDoqa"]))
        bug_content = html_to_text(bug.get("content") or bug.get("description"))
        if bug_content:
            story.append(Paragraph(_escape_multiline(bug_content), styles["BodyDoqa"]))
    story.append(Spacer(1, 6 * mm))


def _styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "TitleDoqa": ParagraphStyle(
            "TitleDoqa",
            parent=base["Title"],
            fontName=bold_font,
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1F2937"),
        ),
        "SubtitleDoqa": ParagraphStyle(
            "SubtitleDoqa",
            parent=base["Heading2"],
            fontName=regular_font,
            fontSize=13,
            leading=17,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#475467"),
        ),
        "SectionDoqa": ParagraphStyle(
            "SectionDoqa",
            parent=base["Heading1"],
            fontName=bold_font,
            fontSize=17,
            leading=21,
            spaceAfter=8,
        ),
        "HeadingDoqa": ParagraphStyle(
            "HeadingDoqa",
            parent=base["Heading2"],
            fontName=bold_font,
            fontSize=12,
            leading=16,
            spaceBefore=4,
            spaceAfter=5,
        ),
        "BugDoqa": ParagraphStyle(
            "BugDoqa",
            parent=base["Heading3"],
            fontName=bold_font,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#B42318"),
            spaceAfter=4,
        ),
        "BodyDoqa": ParagraphStyle(
            "BodyDoqa",
            parent=base["BodyText"],
            fontName=regular_font,
            fontSize=9,
            leading=13,
        ),
    }


def _table(data, regular_font, bold_font, widths) -> Table:
    prepared = [
        [Paragraph(_escape(cell), ParagraphStyle("cell", fontName=regular_font, fontSize=9, leading=12)) for cell in row]
        for row in data
    ]
    table = Table(prepared, colWidths=widths, repeatRows=1 if len(data) > 2 else 0)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4FF")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D5DD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _register_fonts(font_path: Path | None) -> tuple[str, str]:
    regular_path = font_path if font_path and font_path.is_file() else next(
        (path for path in FONT_CANDIDATES if path.is_file()), None
    )
    if regular_path is None:
        raise RuntimeError("Не найден TTF-шрифт с поддержкой кириллицы")
    bold_path = next((path for path in FONT_BOLD_CANDIDATES if path.is_file()), regular_path)
    regular_name = "DoqaReportSans"
    bold_name = "DoqaReportSansBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
    return regular_name, bold_name


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def _escape_multiline(value: Any) -> str:
    return _escape(value).replace("\n", "<br/>")


def _page_number(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Страница {document.page}")
    canvas.restoreState()
