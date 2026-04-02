from __future__ import annotations

from bot.services.parser.classifier import classify_intent
from bot.services.parser.extractors import extract_entities
from bot.services.parser.normalizers import resolve_task_id
from bot.services.parser.schemas import ParseResult


class MessageParser:
    def parse(self, text: str, *, is_reply: bool = False) -> ParseResult:
        entities = extract_entities(text)
        resolved_task_id = resolve_task_id(entities)
        classification = classify_intent(text, entities, resolved_task_id, is_reply=is_reply)
        return ParseResult(
            text=text,
            entities=entities,
            resolved_task_id=resolved_task_id,
            classification=classification,
        )
