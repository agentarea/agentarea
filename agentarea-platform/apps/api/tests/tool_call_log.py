"""A task log holding one shell call whose command carries a bearer token, for the feed surfaces."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_tasks.domain.feed import FeedBodies
from agentarea_tasks.domain.models import ConversationEntry

BEARER = "sk-live-4f9a2c77QpZ"
PASSWORD = "hunter2-correct-horse"  # pragma: allowlist secret
COMMAND = f"curl -H 'Authorization: Bearer {BEARER}' https://api.example.com/items"
MASKED_COMMAND = "curl -H 'Authorization: Bearer [redacted]' https://api.example.com/items"
OUTPUT = "items: 3\nfirst: alpha\n" * 40
_WHEN = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_SANITIZED = {"command": "[omitted from event log: 70 units]", "password": "[redacted]"}


def _event(seq: int, name: str) -> ConversationEntry:
    return ConversationEntry(
        seq=seq,
        event_id=uuid4(),
        kind="event",
        role="event",
        content="",
        name=name,
        meta={"tool_call_id": "call-1", "tool_name": "shell", "arguments": _SANITIZED},
        execution_id="exec-1",
        occurred_at=_WHEN,
    )


TOOL_CALL = _event(3, "tool.call")
TOOL_RESULT = _event(4, "tool.result")
EVENT_ROWS = [TOOL_CALL, TOOL_RESULT]
MESSAGE_ROWS = [
    ConversationEntry(
        seq=1,
        event_id=uuid4(),
        kind="message",
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "shell",
                    "arguments": json.dumps({"command": COMMAND, "password": PASSWORD}),
                },
            }
        ],
        occurred_at=_WHEN,
    ),
    ConversationEntry(
        seq=2,
        event_id=uuid4(),
        kind="message",
        role="tool",
        content=OUTPUT,
        tool_call_id="call-1",
        occurred_at=_WHEN,
    ),
]


class FakeFeedReader:
    """``TaskFeedReader`` over the log above."""

    def __init__(self, session: Any = None, user_context: Any = None):
        pass

    async def page(self, task_id: UUID, *, event_type=None, limit=50, offset=0):
        return EVENT_ROWS[offset : offset + limit], len(EVENT_ROWS)

    async def after(self, task_id: UUID, *, after_seq: int, limit: int):
        return [row for row in EVENT_ROWS if row.seq > after_seq][:limit]

    async def at(self, task_id: UUID, seq: int):
        return next((row for row in EVENT_ROWS if row.seq == seq), None)

    async def bodies(self, task_id: UUID, entries, *, revealed: bool = False) -> FeedBodies:
        return FeedBodies.of(MESSAGE_ROWS, revealed=revealed)


def assert_owner_view(call: dict, result: dict) -> None:
    """The task's authority: the command and output whole, the secrets masked."""
    text = json.dumps([call, result])
    assert BEARER not in text and PASSWORD not in text
    assert call["arguments"]["command"] == MASKED_COMMAND
    assert call["arguments"]["password"] == "[redacted]"
    assert result["result"] == OUTPUT


def assert_member_view(call: dict, result: dict) -> None:
    """Anyone else: the command and output omitted, as the event log redacts them."""
    text = json.dumps([call, result])
    assert BEARER not in text and PASSWORD not in text
    assert "api.example.com" not in text
    assert call["arguments"]["command"].startswith("[omitted from event log")
    assert "items: 3" not in text
