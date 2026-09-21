"""DoQA PDF parser core: extract text, detect bug blocks, build structured data.

A DoQA PDF mixes a summary table on page 1 with per-bug detail blocks on the
following pages. We anchor on the bug "header" line (initials + reporter +
date + time) and read forward until the next anchor or until we hit a
summary-table row. The reporter/date/PDF page numbers are used internally for
boundary detection and attachment extraction but are not exposed in the parsed
output — only bug content is surfaced to agents and developers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pdfplumber


SECTION_HEADERS = {
    "Описание:": "description",
    "Описание": "description",
    "Шаги:": "steps",
    "Шаги": "steps",
    "Ожидаемый результат:": "expected",
    "Ожидаемый результат": "expected",
    "Фактический результат:": "actual",
    "Фактический результат": "actual",
    "Вложения:": "attachments",
    "Вложения": "attachments",
}

ATTACHMENT_MARKERS = ("Скринкаст ошибки", "Скриншот ошибки", "Видео ошибки")

TEST_RESULT_WORDS = ("Пройден", "Провален", "Сломан", "Заблокирован", "Пропущен", "Не начат")
CLOSED_BUG_STATUSES = {"закрыт", "closed"}

# Header that DoQA prints on top of every detail page. We match by prefix
# because DoQA sometimes injects icon glyphs from a private-use area between
# the column labels.
PAGE_HEADER_PREFIX = "№ ID Тип Название"
PAGE_FOOTER_RE = re.compile(r"^about:blank\s+Страница\s+\d+\s+из\s+\d+$")
PRINTED_AT_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4},\s+\d{1,2}:\d{2}\s+(?:AM|PM)$")

# Test group titles that can appear as the first line of a summary-table row
# and would otherwise leak into the previous bug's "actual" section.
SUMMARY_GROUP_PREFIXES = (
    "Base Mobile",
    "Base Mobile Checklist",
    "AI Music Generator",
    "AI Music Generator /",
    "AI Video Generator",
    "AI Video Generator /",
)

# Anchor of a bug block. New DoQA exports expose the decorative "bug" icon to
# pdfplumber as a broken ``bu`` / ``g`` glyph around the author line, so the
# first fragment is accepted here and the second one is skipped below.
ANCHOR_RE = re.compile(
    r"^(?:bu(?:g)?\s+)?(?:(?P<initials>[А-ЯЁA-Z]{1,4})\s+)?(?P<name>[^\d]+?)\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2})$"
)

# A summary-table row like "2 67  / Онбординг и 0 0 Богдан Топорин Пройден".
SUMMARY_ROW_RE = re.compile(r"^\d+\s+\d+\s+\S")

BUG_ID_TITLE_RE = re.compile(r"^(?P<id>\d+)\s+(?P<title>.+)$")
DECORATIVE_GLYPH_RE = re.compile(r"^(?:bu|bug|g|checkmar|k)$", re.IGNORECASE)


@dataclass
class Attachment:
    """A single attachment reference parsed out of the bug body."""

    source_name: str
    saved_path: Path | None = None

    def to_dict(self, base_dir: Path | None = None) -> dict:
        path: str | None = None
        if self.saved_path is not None:
            try:
                path = str(self.saved_path.relative_to(base_dir)) if base_dir else str(self.saved_path)
            except ValueError:
                path = str(self.saved_path)
        return {"name": self.source_name, "path": path}


@dataclass
class Step:
    """A reproduction step. `number` may be None when the source had no prefix."""

    number: int | None
    text: str

    def to_dict(self) -> dict:
        return {"number": self.number, "text": self.text}


@dataclass
class Bug:
    """A bug as it will be surfaced to agents and developers.

    ``pdf_page`` is kept for internal use only (we need it to fetch the right
    page when extracting embedded screenshots) and is intentionally absent
    from :meth:`to_dict`.
    """

    bug_id: str
    title: str
    priority: str = ""
    status: str = ""
    description: str = ""
    steps: list[Step] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    pdf_page: int = 0

    def to_dict(self, attachments_base: Path | None = None) -> dict:
        return {
            "id": self.bug_id,
            "title": self.title,
            "priority": self.priority,
            "status": self.status,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "expected": self.expected,
            "actual": self.actual,
            "attachments": [att.to_dict(attachments_base) for att in self.attachments],
        }


@dataclass
class ParsedReport:
    """The parser's full output: just the source PDF path and a list of bugs."""

    source_pdf: Path
    bugs: list[Bug]


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


# DoQA reuses Private Use Area code points as glyph dividers. Map the ones we
# have observed in real reports to plain ASCII; drop the rest (mostly UI icons).
_PUA_REPLACEMENTS = {
    "\ue082": ")",
    "\ue088": ".",
    "\ue092": ":",
}
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _replace_pua(match: re.Match) -> str:
    return _PUA_REPLACEMENTS.get(match.group(0), "")


def normalize_text(text: str) -> str:
    text = (
        text.replace("\u02c2", "<")
        .replace("\u02c8", "-")
        .replace("\u00a0", " ")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    text = _PUA_RE.sub(_replace_pua, text)
    return _MULTI_SPACE_RE.sub(" ", text)


def extract_pages(pdf_path: Path) -> list[list[str]]:
    """Return non-empty stripped lines, grouped by 1-based page number."""

    pages: list[list[str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            lines = [line.strip() for line in normalize_text(text).splitlines()]
            pages.append([line for line in lines if line])
    return pages


# ---------------------------------------------------------------------------
# Bug blocks
# ---------------------------------------------------------------------------


@dataclass
class _Row:
    page: int
    text: str


def _flatten(pages: list[list[str]]) -> list[_Row]:
    rows: list[_Row] = []
    for page_num, lines in enumerate(pages, start=1):
        for line in lines:
            rows.append(_Row(page=page_num, text=line))
    return rows


def _is_summary_row(text: str) -> bool:
    return bool(SUMMARY_ROW_RE.match(text))


def _is_result_continuation(text: str) -> bool:
    return any(text.endswith(word) for word in TEST_RESULT_WORDS)


def _is_page_header(text: str) -> bool:
    return text.startswith(PAGE_HEADER_PREFIX)


def _is_page_chrome(text: str) -> bool:
    return _is_page_header(text) or bool(PAGE_FOOTER_RE.match(text)) or bool(PRINTED_AT_RE.match(text))


def _is_decorative_glyph(text: str) -> bool:
    """Return True for icon names leaked by DoQA's PDF accessibility layer."""
    return bool(DECORATIVE_GLYPH_RE.fullmatch(text.strip()))


def _section_name(text: str) -> str | None:
    """Normalize headings such as ``Вложения :`` emitted by newer exports."""
    normalized = re.sub(r"\s+:\s*$", ":", text.strip())
    return SECTION_HEADERS.get(normalized)


def _is_closed_status(status: str) -> bool:
    normalized = status.strip().casefold().replace("ё", "е")
    return normalized in CLOSED_BUG_STATUSES


def _starts_summary_block(rows: list[_Row], index: int) -> bool:
    """Return True if the row marks the boundary between bug body and summary table.

    Only the boundary line itself triggers this — the lookahead checks that a
    summary row really follows, so real "actual result" text right before a
    summary table is preserved.
    """

    text = rows[index].text
    if _is_summary_row(text) or _is_result_continuation(text):
        return True

    stripped = text.rstrip("/").strip()
    for prefix in SUMMARY_GROUP_PREFIXES:
        if stripped == prefix.rstrip("/").strip():
            for j in range(index + 1, min(index + 4, len(rows))):
                next_text = rows[j].text
                if _is_summary_row(next_text) or _is_result_continuation(next_text):
                    return True
                if ANCHOR_RE.match(next_text) or next_text in SECTION_HEADERS:
                    return False
    return False


def _parse_steps(lines: list[str]) -> list[Step]:
    steps: list[Step] = []
    current: Step | None = None
    for line in lines:
        match = re.match(r"^Шаг\s+(\d+)\s*[:.\-]\s*(.+)$", line)
        if match:
            if current:
                steps.append(current)
            current = Step(number=int(match.group(1)), text=match.group(2).strip())
        else:
            if current:
                current.text = f"{current.text} {line}".strip()
            else:
                current = Step(number=None, text=line)
    if current:
        steps.append(current)
    return steps


def _parse_block(rows: list[_Row]) -> Bug | None:
    if not rows:
        return None

    anchor = ANCHOR_RE.match(rows[0].text)
    if not anchor:
        return None

    bug = Bug(bug_id="", title="", pdf_page=rows[0].page)

    if len(rows) < 2:
        return None

    index = 1
    while index < len(rows) and (
        _is_page_chrome(rows[index].text) or _is_decorative_glyph(rows[index].text)
    ):
        index += 1

    if index >= len(rows):
        return None

    id_match = BUG_ID_TITLE_RE.match(rows[index].text)
    if not id_match:
        return None
    bug.pdf_page = rows[index].page
    bug.bug_id = id_match.group("id")
    title_parts = [id_match.group("title").strip()]

    index += 1
    while index < len(rows) and rows[index].text != "Приоритет Статус":
        if _is_page_chrome(rows[index].text):
            index += 1
            continue
        title_parts.append(rows[index].text)
        index += 1
    bug.title = " ".join(title_parts).strip()

    if index >= len(rows):
        return bug

    index += 1
    while index < len(rows) and _is_page_chrome(rows[index].text):
        index += 1

    if index < len(rows):
        values = rows[index].text.split()
        if values:
            bug.priority = values[0]
        if len(values) > 1:
            bug.status = " ".join(values[1:])
        index += 1

    sections: dict[str, list[str]] = {
        "description": [],
        "steps": [],
        "expected": [],
        "actual": [],
        "attachments": [],
    }
    current: str | None = None

    while index < len(rows):
        text = rows[index].text
        position = index
        index += 1

        if _is_page_chrome(text):
            continue
        section_name = _section_name(text)
        if section_name is not None:
            current = section_name
            continue
        if any(marker in text for marker in ATTACHMENT_MARKERS):
            sections["attachments"].append(text.strip())
            current = None
            continue
        if _starts_summary_block(rows, position):
            current = None
            continue
        if current is None:
            continue
        sections[current].append(text)

    bug.description = " ".join(sections["description"]).strip()
    bug.steps = _parse_steps(sections["steps"])
    bug.expected = " ".join(sections["expected"]).strip()
    bug.actual = " ".join(sections["actual"]).strip()
    bug.attachments = [Attachment(source_name=name) for name in sections["attachments"]]

    return bug


def parse_bugs(pdf_path: Path) -> ParsedReport:
    pages = extract_pages(pdf_path)
    rows = _flatten(pages)
    anchor_indices = [i for i, row in enumerate(rows) if ANCHOR_RE.match(row.text)]

    bugs: list[Bug] = []
    for idx, start in enumerate(anchor_indices):
        end = anchor_indices[idx + 1] if idx + 1 < len(anchor_indices) else len(rows)
        bug = _parse_block(rows[start:end])
        if bug is not None and bug.bug_id and not _is_closed_status(bug.status):
            bugs.append(bug)

    return ParsedReport(source_pdf=pdf_path, bugs=bugs)


# ---------------------------------------------------------------------------
# Attachments (images embedded in the PDF)
# ---------------------------------------------------------------------------


def _safe_stem(value: str) -> str:
    stem = Path(value).stem or value
    stem = re.sub(r"[^\w .-]+", "_", stem, flags=re.UNICODE)
    return re.sub(r"\s+", "_", stem).strip("._") or "attachment"


def save_page_images(pdf_path: Path, bugs: list[Bug], output_dir: Path) -> None:
    """Extract images from the PDF page on which each bug lives.

    DoQA exports inline screenshots and ad-hoc service graphics; we keep the
    largest images first so real screenshots win over UI chrome.
    """

    attachments_dir = output_dir / "attachments"

    doc = pymupdf.open(pdf_path)
    for bug in bugs:
        if not bug.attachments:
            continue

        attachments_dir.mkdir(parents=True, exist_ok=True)
        page = doc[bug.pdf_page - 1]
        images = page.get_images(full=True)
        if not images:
            continue

        candidates = sorted(images, key=lambda img: img[2] * img[3], reverse=True)
        for attachment, image_info in zip(bug.attachments, candidates):
            xref = image_info[0]
            image = doc.extract_image(xref)
            extension = image.get("ext", "png")
            filename = f"bug_{bug.bug_id}_{_safe_stem(attachment.source_name)}.{extension}"
            saved_path = attachments_dir / filename
            saved_path.write_bytes(image["image"])
            attachment.saved_path = saved_path
