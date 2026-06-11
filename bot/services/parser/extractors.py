from __future__ import annotations

import re
from urllib.parse import urlparse

from bot.services.parser.schemas import ExtractedEntities, UrlEntity

MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_]{3,32})")
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
ARCHIVE_RE = re.compile(r"\b([A-Za-zА-Яа-я0-9_-]+\.(?:zip|rar|7z))\b", re.IGNORECASE)
TASK_ID_RE = re.compile(
    r"\b("
    r"(?:[A-Za-zА-Яа-я]+[_-]?\d{1,6})|"
    r"(?:ID\s*[A-Za-zА-Яа-я_-]*[- ]?\d{1,6})|"
    r"(?:id[A-Za-zА-Яа-я_-]*[- ]?\d{1,6})"
    r")\b",
    re.IGNORECASE,
)
FILE_PATH_RE = re.compile(r"\b(?:[\w-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}\b")
LINE_NUMBER_RE = re.compile(r"(?:(?:строк[ае]?|line)\s*(\d+)|(\d+)\s*(?:строк[ае]?|line))", re.IGNORECASE)
GITHUB_BRANCH_RE = re.compile(r"/archive/refs/heads/(?P<branch>[^/]+)\.(?:zip|tar\.gz)$", re.IGNORECASE)
GITHUB_REPO_RE = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/", re.IGNORECASE)
FIGMA_SLUG_RE = re.compile(r"^/design/[^/]+/(?P<slug>[^/?#]+)", re.IGNORECASE)
SHORT_TEXT_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./-]{1,80}$")

INSTRUCTION_MARKERS = (
    "нужно",
    "проверь",
    "проверить",
    "на проверку",
    "на тест",
    "please",
    "todo",
    "сделай",
)


def humanize_slug(value: str) -> str:
    cleaned = value.strip().replace("%20", " ")
    cleaned = re.sub(r"\.(?=\w)", " ", cleaned)
    cleaned = re.sub(r"[_-]+", " ", cleaned)
    cleaned = re.sub(r"\b(?:id[a-zа-я]*\s*)?\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned


def extract_branch_names(urls: list[UrlEntity]) -> list[str]:
    branches: list[str] = []
    for entity in urls:
        if entity.kind != "github":
            continue
        parsed = urlparse(entity.url)
        match = GITHUB_BRANCH_RE.search(parsed.path)
        if match:
            branches.append(match.group("branch"))
    return sorted(set(branches))


def extract_app_name_candidates(lines: list[str], urls: list[UrlEntity]) -> list[str]:
    candidates: list[str] = []

    for entity in urls:
        parsed = urlparse(entity.url)
        if entity.kind == "figma":
            match = FIGMA_SLUG_RE.match(parsed.path)
            if match:
                slug = humanize_slug(match.group("slug"))
                if slug:
                    candidates.append(slug)
        elif entity.kind == "github":
            match = GITHUB_REPO_RE.match(parsed.path)
            if match:
                repo_name = humanize_slug(match.group("repo"))
                if repo_name:
                    candidates.append(repo_name)

    for line in lines:
        lowered = line.lower()
        if line.startswith("@") or "http://" in lowered or "https://" in lowered:
            continue
        if "/" in line and "." in line:
            continue
        if any(marker in lowered for marker in INSTRUCTION_MARKERS):
            continue
        if SHORT_TEXT_LINE_RE.match(line):
            candidates.append(line.strip())

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        unique_candidates.append(normalized)
    return unique_candidates


def classify_url(url: str) -> str:
    lowered = url.lower()
    if "figma.com" in lowered:
        return "figma"
    if "docs.google.com" in lowered or "drive.google.com" in lowered:
        return "google_docs"
    if "github.com" in lowered or "gitlab.com" in lowered:
        return "github"
    return "other"


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def extract_entities(text: str) -> ExtractedEntities:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    urls = [UrlEntity(url=match.group(0), kind=classify_url(match.group(0))) for match in URL_RE.finditer(text)]
    raw_file_paths: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if lowered.startswith(("http://", "https://", "www.")):
            continue
        for match in FILE_PATH_RE.finditer(line):
            raw_file_paths.add(match.group(0))
    file_paths = sorted(
        {
            path
            for path in raw_file_paths
            if "." in path.rsplit("/", 1)[-1]
        }
    )
    instruction_lines = [
        line for line in lines if any(marker in line.lower() for marker in INSTRUCTION_MARKERS)
    ]

    return ExtractedEntities(
        mentions=sorted({match.group(1) for match in MENTION_RE.finditer(text)}),
        urls=urls,
        archive_names=ordered_unique([match.group(1) for match in ARCHIVE_RE.finditer(text)]),
        candidate_task_ids=ordered_unique([match.group(1) for match in TASK_ID_RE.finditer(text)]),
        file_paths=file_paths,
        line_numbers=[int(match.group(1) or match.group(2)) for match in LINE_NUMBER_RE.finditer(text)],
        instruction_lines=instruction_lines,
        branch_names=extract_branch_names(urls),
        app_name_candidates=extract_app_name_candidates(lines, urls),
    )
