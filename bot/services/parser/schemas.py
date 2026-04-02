from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    NEW_TASK = "NEW_TASK"
    TASK_UPDATE = "TASK_UPDATE"
    TASK_DONE = "TASK_DONE"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class UrlEntity:
    url: str
    kind: str


@dataclass(slots=True)
class ExtractedEntities:
    mentions: list[str] = field(default_factory=list)
    urls: list[UrlEntity] = field(default_factory=list)
    archive_names: list[str] = field(default_factory=list)
    candidate_task_ids: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    line_numbers: list[int] = field(default_factory=list)
    instruction_lines: list[str] = field(default_factory=list)
    branch_names: list[str] = field(default_factory=list)
    app_name_candidates: list[str] = field(default_factory=list)

    def first_url_by_kind(self, kind: str) -> str | None:
        for entity in self.urls:
            if entity.kind == kind:
                return entity.url
        return None


@dataclass(slots=True)
class ResolvedTaskId:
    task_number: int
    task_family: str
    canonical_task_key: str
    source_value: str
    source_kind: str


@dataclass(slots=True)
class ClassificationResult:
    intent: Intent
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParseResult:
    text: str
    entities: ExtractedEntities
    resolved_task_id: ResolvedTaskId | None
    classification: ClassificationResult
