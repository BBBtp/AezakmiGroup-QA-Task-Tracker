from __future__ import annotations

import re

from bot.services.parser.schemas import ExtractedEntities, ResolvedTaskId

ARCHIVE_BASE_RE = re.compile(r"^(?P<base>[A-Za-zА-Яа-я0-9_-]+)\.(?:zip|rar|7z)$", re.IGNORECASE)
ARCHIVE_SUFFIX_RE = re.compile(r"(?P<base>.+?)(?:/archive/refs/heads/.+)?\.(?:zip|rar|7z|tar\.gz)$", re.IGNORECASE)
FAMILY_NUMBER_RE = re.compile(
    r"(?P<family>[A-Za-zА-Яа-я]+)[\s_-]?(?P<number>\d{1,6})$",
    re.IGNORECASE,
)
FAMILY_NUMBER_PREFIX_RE = re.compile(
    r"^(?P<family>[A-Za-zА-Яа-я]+)[\s_-]?(?P<number>\d{1,6})(?:[\s_-].+)?$",
    re.IGNORECASE,
)
ID_PREFIX_RE = re.compile(r"^id[\s_-]*(?P<number>\d{1,6})$", re.IGNORECASE)
ID_WITH_FAMILY_RE = re.compile(
    r"^id(?P<family>[A-Za-zА-Яа-я]+)?[\s_-]*(?P<number>\d{1,6})$",
    re.IGNORECASE,
)


def _normalize_raw_id(value: str) -> tuple[str, int] | None:
    cleaned = value.strip().replace(" ", "_").replace("-", "_")
    cleaned = re.sub(r"__+", "_", cleaned)
    lowered = cleaned.lower()

    archive_suffix_match = ARCHIVE_SUFFIX_RE.match(lowered)
    if archive_suffix_match:
        lowered = archive_suffix_match.group("base")

    archive_match = ARCHIVE_BASE_RE.match(lowered)
    if archive_match:
        lowered = archive_match.group("base")

    if match := FAMILY_NUMBER_RE.match(lowered):
        family = match.group("family").lower()
        number = int(match.group("number"))
        return family, number

    if match := FAMILY_NUMBER_PREFIX_RE.match(lowered):
        family = match.group("family").lower()
        number = int(match.group("number"))
        return family, number

    if match := ID_WITH_FAMILY_RE.match(lowered):
        family = (match.group("family") or "id").lower()
        number = int(match.group("number"))
        return family, number

    if match := ID_PREFIX_RE.match(lowered):
        return "id", int(match.group("number"))

    return None


def resolve_task_id(entities: ExtractedEntities) -> ResolvedTaskId | None:
    candidates: list[tuple[str, str]] = []

    for archive_name in entities.archive_names:
        candidates.append(("archive", archive_name))
    for candidate in entities.candidate_task_ids:
        candidates.append(("pattern", candidate))
    for file_path in entities.file_paths:
        candidates.append(("file_path", file_path.rsplit("/", 1)[-1]))

    for source_kind, raw_value in candidates:
        normalized = _normalize_raw_id(raw_value)
        if normalized is None:
            continue

        family, number = normalized
        return ResolvedTaskId(
            task_number=number,
            task_family=family,
            canonical_task_key=f"{family}_{number}",
            source_value=raw_value,
            source_kind=source_kind,
        )

    return None
