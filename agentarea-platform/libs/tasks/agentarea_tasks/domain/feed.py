"""What a task's feed shows of its log: each event row, and each message a person sent."""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agentarea_common.events.contract import MESSAGE_RECEIVED, TOOL_CALL, TOOL_RESULT
from agentarea_common.events.redaction import reveal_tool_value, sanitize_tool_event_value

from .models import ConversationEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedBodies:
    """The full bodies of a run's tool calls, from its messages, by tool call id.

    The run's events carry bounded copies (the workflow keeps Temporal payloads
    small); the log's messages hold what the tool really got and returned. A
    body stored outside its row is not here. ``revealed`` is for a reader who
    holds the task's authority: the arguments and result whole, with their
    secrets masked. Anyone else sees them as the event log redacts them.
    """

    results: dict[str, str] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    revealed: bool = False

    @classmethod
    def of(cls, rows: Iterable[ConversationEntry], *, revealed: bool = False) -> "FeedBodies":
        results: dict[str, str] = {}
        arguments: dict[str, Any] = {}
        for row in rows:
            if row.kind != "message":
                continue
            if row.role == "tool" and row.tool_call_id and row.body_ref is None:
                results[row.tool_call_id] = row.content
            if row.role == "assistant":
                for call in row.tool_calls or []:
                    call_id = call.get("id") if isinstance(call, dict) else None
                    function = call.get("function") if isinstance(call, dict) else None
                    if not call_id or not isinstance(function, dict):
                        continue
                    arguments[call_id] = _arguments(call_id, function.get("arguments"))
        return cls(results=results, arguments=arguments, revealed=revealed)


def _arguments(call_id: str, raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Tool call %s has arguments that are not JSON; shown as text", call_id)
        return raw


def feed_event(
    entry: ConversationEntry, bodies: FeedBodies | None = None
) -> tuple[str, dict[str, Any]] | None:
    """The row as a feed event ``(type, data)``, or None for a row the feed leaves out.

    An event row is its event; a tool call's arguments and result come from
    ``bodies`` when it has them. A person's message, the run's input or a
    follow-up, is ``message.received`` with its text; a text stored outside the
    row is flagged instead of carried. Model and tool messages and compactions
    stay out: their events (``llm.call.completed``, ``tool.result``,
    ``context.compacted``) are in the feed already.
    """
    if entry.kind == "event":
        if not entry.name:
            raise ValueError(f"event row {entry.seq} has no type")
        data = dict(entry.meta or {})
        call_id = data.get("tool_call_id")
        if bodies is not None and isinstance(call_id, str):
            if entry.name in (TOOL_CALL, TOOL_RESULT) and call_id in bodies.arguments:
                arguments = bodies.arguments[call_id]
                data["arguments"] = (
                    reveal_tool_value(arguments)
                    if bodies.revealed
                    else sanitize_tool_event_value(arguments)
                )
            if entry.name == TOOL_RESULT and call_id in bodies.results:
                result = bodies.results[call_id]
                data["result"] = (
                    reveal_tool_value(result)
                    if bodies.revealed
                    else sanitize_tool_event_value(result, field_name="result")
                )
        return entry.name, data
    if entry.kind == "message" and entry.role == "user":
        data = {
            "content": entry.content,
            "attachments": entry.attachments or [],
            "iteration": entry.iteration,
            "execution_id": entry.execution_id,
        }
        if entry.body_ref is not None:
            data["content_stored_separately"] = True
        return MESSAGE_RECEIVED, data
    return None
