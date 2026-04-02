from __future__ import annotations

from bot.services.parser.schemas import ClassificationResult, ExtractedEntities, Intent, ResolvedTaskId

DONE_PHRASES = (
    "все окей",
    "всё окей",
    "готово",
    "сделано",
    "done",
    "fixed",
    "закрыто",
)
UPDATE_PHRASES = (
    "на бэке поправили",
    "обновили",
    "перезалил",
    "перезалили",
    "поправили",
    "исправил",
    "исправили",
    "фикс",
    "залил фикс",
    "пофиксил",
    "пофиксили",
    "updated",
    "fix",
    "fixed",
    "залил",
)
NEW_TASK_PHRASES = (
    "на проверку",
    "на тест",
    "нужно проверить",
    "посмотрите",
    "можете глянуть",
    "bug report",
    "описание задачи",
)


def classify_intent(
    text: str,
    entities: ExtractedEntities,
    resolved_task_id: ResolvedTaskId | None,
    is_reply: bool,
) -> ClassificationResult:
    lowered = text.lower()
    reasons: list[str] = []
    confidence = 0.05

    if any(phrase in lowered for phrase in DONE_PHRASES):
        confidence = 0.65
        reasons.append("completion phrase detected")
        if resolved_task_id:
            confidence += 0.2
            reasons.append("task id resolved for completion")
        if is_reply:
            confidence += 0.1
            reasons.append("reply context may resolve task")
        return ClassificationResult(intent=Intent.TASK_DONE, confidence=min(confidence, 1.0), reasons=reasons)

    if any(phrase in lowered for phrase in UPDATE_PHRASES):
        confidence = 0.6 if is_reply or resolved_task_id else 0.45
        reasons.append("update phrase detected")
        if resolved_task_id:
            confidence += 0.15
            reasons.append("task id resolved for update")
        if is_reply:
            confidence += 0.1
            reasons.append("reply context for update")
        return ClassificationResult(intent=Intent.TASK_UPDATE, confidence=min(confidence, 1.0), reasons=reasons)

    if resolved_task_id:
        confidence += 0.35
        reasons.append("task id resolved")
    if entities.archive_names:
        confidence += 0.2
        reasons.append("archive name present")
    if entities.mentions:
        confidence += 0.15
        reasons.append("assignee mention present")
    if entities.urls:
        confidence += 0.12
        reasons.append("task-related link present")
    if any(phrase in lowered for phrase in NEW_TASK_PHRASES) or entities.instruction_lines:
        confidence += 0.18
        reasons.append("task-related instruction present")

    if resolved_task_id and (
        entities.mentions or entities.urls or any(phrase in lowered for phrase in NEW_TASK_PHRASES) or entities.instruction_lines
    ):
        return ClassificationResult(intent=Intent.NEW_TASK, confidence=min(confidence, 1.0), reasons=reasons)

    return ClassificationResult(intent=Intent.UNKNOWN, confidence=min(confidence, 1.0), reasons=reasons)
