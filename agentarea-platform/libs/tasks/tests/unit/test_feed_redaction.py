"""The feed shows a tool call's arguments and result as the event log redacts them."""

import json
from uuid import uuid4

from agentarea_common.events.contract import TOOL_CALL, TOOL_RESULT
from agentarea_tasks.domain.feed import FeedBodies, feed_event
from agentarea_tasks.domain.models import ConversationEntry

BEARER = "sk-live-4f9a2c"
PASSWORD = "hunter2-correct-horse"


def _entries() -> list[ConversationEntry]:
    arguments = {
        "command": f"curl -H 'Authorization: Bearer {BEARER}' https://api.example.com",
        "password": PASSWORD,
        "timeout": 30,
    }
    redacted = {"command": "[omitted]", "password": "[redacted]", "timeout": 30}
    return [
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
                    "function": {"name": "shell", "arguments": json.dumps(arguments)},
                }
            ],
        ),
        ConversationEntry(
            seq=2,
            event_id=uuid4(),
            kind="message",
            role="tool",
            content=f"token={BEARER} ok",
            tool_call_id="call-1",
        ),
        ConversationEntry(
            seq=3,
            event_id=uuid4(),
            kind="event",
            role="event",
            content="",
            name=TOOL_CALL,
            meta={"tool_call_id": "call-1", "tool_name": "shell", "arguments": redacted},
        ),
        ConversationEntry(
            seq=4,
            event_id=uuid4(),
            kind="event",
            role="event",
            content="",
            name=TOOL_RESULT,
            meta={"tool_call_id": "call-1", "tool_name": "shell", "arguments": redacted},
        ),
    ]


def _shown(bodies: FeedBodies) -> list[dict]:
    shown = [feed_event(entry, bodies) for entry in _entries()]
    return [data for item in shown if item is not None for _, data in [item]]


def test_a_secret_in_tool_arguments_never_reaches_the_feed():
    entries = _entries()
    for revealed in (False, True):
        for data in _shown(FeedBodies.of(entries, revealed=revealed)):
            assert BEARER not in json.dumps(data)
            assert PASSWORD not in json.dumps(data)
            assert data["arguments"]["password"] == "[redacted]"
            assert data["arguments"]["timeout"] == 30


def test_the_tasks_authority_sees_the_command_and_result_with_secrets_masked():
    [call, result] = _shown(FeedBodies.of(_entries(), revealed=True))
    command = "curl -H 'Authorization: Bearer [redacted]' https://api.example.com"
    assert call["arguments"]["command"] == command
    assert result["arguments"]["command"] == command
    assert result["result"] == "token=[redacted] ok"


def test_a_member_sees_the_sanitized_form():
    [call, result] = _shown(FeedBodies.of(_entries()))
    assert call["arguments"]["command"].startswith("[omitted from event log")
    assert result["result"].startswith("[omitted from event log")
