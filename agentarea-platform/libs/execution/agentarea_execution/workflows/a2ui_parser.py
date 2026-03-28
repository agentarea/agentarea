"""A2UI v0.9 response parser.

Detects the ---a2ui_JSON--- delimiter in LLM output, splits text from A2UI JSON,
validates the JSON structure, and returns parsed events.

This module uses only stdlib (json, logging) and is safe for the Temporal sandbox.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

A2UI_DELIMITER = "---a2ui_JSON---"

VALID_A2UI_EVENT_TYPES = frozenset(
    {
        "A2UICreateSurface",
        "A2UIUpdateComponents",
        "A2UIUpdateDataModel",
        "A2UIDeleteSurface",
    }
)

MAX_JSON_SIZE = 100 * 1024  # 100KB limit for A2UI JSON payloads


@dataclass
class A2UIParseResult:
    """Result of parsing A2UI content from an LLM response."""

    text_content: str
    a2ui_events: list[dict[str, Any]] = field(default_factory=list)
    raw_json: str | None = None
    parse_error: str | None = None


def parse_a2ui_response(content: str) -> A2UIParseResult:
    """Parse LLM response content, extracting A2UI JSON after delimiter.

    The LLM is prompted to output:
        <text response>
        ---a2ui_JSON---
        {"events": [<A2UI event objects>]}

    Returns A2UIParseResult with text_content (before delimiter) and
    a2ui_events (validated list of event dicts).
    """
    if A2UI_DELIMITER not in content:
        return A2UIParseResult(text_content=content)

    parts = content.split(A2UI_DELIMITER, 1)
    text_part = parts[0].rstrip()
    json_part = parts[1].strip()

    if not json_part:
        return A2UIParseResult(
            text_content=text_part,
            parse_error="Empty A2UI JSON after delimiter",
        )

    if len(json_part) > MAX_JSON_SIZE:
        return A2UIParseResult(
            text_content=text_part,
            parse_error=f"A2UI JSON exceeds {MAX_JSON_SIZE} byte limit",
        )

    try:
        parsed = json.loads(json_part)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid A2UI JSON: {e}")
        return A2UIParseResult(
            text_content=text_part,
            raw_json=json_part,
            parse_error=f"Invalid JSON: {e}",
        )

    if not isinstance(parsed, dict):
        return A2UIParseResult(
            text_content=text_part,
            raw_json=json_part,
            parse_error="A2UI payload must be a JSON object",
        )

    events = parsed.get("events", [])
    if not isinstance(events, list):
        return A2UIParseResult(
            text_content=text_part,
            raw_json=json_part,
            parse_error="'events' must be a list",
        )

    valid_events = []
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            logger.warning(f"A2UI event {i} is not an object, skipping")
            continue

        event_type = event.get("type")
        surface_id = event.get("surface_id")

        if event_type not in VALID_A2UI_EVENT_TYPES:
            logger.warning(f"Unknown A2UI event type: {event_type}, skipping")
            continue

        if not surface_id:
            logger.warning(f"A2UI event {event_type} missing surface_id, skipping")
            continue

        valid_events.append(event)

    return A2UIParseResult(
        text_content=text_part,
        a2ui_events=valid_events,
        raw_json=json_part,
    )
