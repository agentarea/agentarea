"""``runs.get_events`` says what each event is about, not only its message.

Failure, tool and model events carry their facts in typed fields rather than a
``message``; a reader of a run over MCP needs the error of a failed call, the
outcome of a tool call and the usage of a model call, without the full results.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset, _event_projection

RUN_ID = uuid4()


def test_failed_model_call_carries_its_error():
    assert _event_projection(
        "llm.call.failed",
        {
            "iteration": 2,
            "error": "The provider is out of credits.",
            "error_type": "ProviderOutOfCredits",
            "failure_reason": "provider_out_of_credits",
            "error_detail": "402 Payment Required: insufficient credits",
            "model_id": "m-1",
        },
    ) == {
        "error": "The provider is out of credits.",
        "error_type": "ProviderOutOfCredits",
        "failure_reason": "provider_out_of_credits",
        "error_detail": "402 Payment Required: insufficient credits",
        "model_id": "m-1",
    }


def test_failed_task_carries_status_and_cause():
    assert _event_projection(
        "task.failed",
        {
            "success": False,
            "status": "failed",
            "error": "Provider credentials cannot be decrypted.",
            "error_type": "ProviderCredentialsUnreadable",
            "failure_reason": "provider_credentials_unreadable",
            "blocked_reason": None,
            "final_response": "long text",
            "total_cost": "0.01",
        },
    ) == {
        "status": "failed",
        "success": False,
        "error": "Provider credentials cannot be decrypted.",
        "error_type": "ProviderCredentialsUnreadable",
        "failure_reason": "provider_credentials_unreadable",
    }


def test_tool_call_names_its_arguments_without_their_values():
    assert _event_projection(
        "tool.call",
        {
            "tool_name": "shell",
            "tool_call_id": "call-1",
            "arguments": {"command": "cat /etc/secret"},
        },
    ) == {"tool_name": "shell", "tool_call_id": "call-1", "argument_names": ["command"]}


def test_tool_result_carries_outcome_not_result():
    assert _event_projection(
        "tool.result",
        {
            "tool_name": "shell",
            "tool_call_id": "call-1",
            "success": False,
            "replayed": True,
            "error": "exit 1",
            "exit_code": 1,
            "result": "x" * 10_000,
            "arguments": {"command": "false"},
        },
    ) == {
        "tool_name": "shell",
        "tool_call_id": "call-1",
        "success": False,
        "replayed": True,
        "error": "exit 1",
        "exit_code": 1,
    }


def test_completed_model_call_carries_cost_and_token_usage():
    assert _event_projection(
        "llm.call.completed",
        {
            "model_id": "m-1",
            "model_name": "gpt-x",
            "cost": "0.002",
            "provider_cost_usd": "0.002",
            "usage": {
                "cost": "0.002",
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 20,
                    "total_tokens": 1020,
                    "cached_prompt_tokens": 800,
                },
            },
            "content": "the whole reply",
            "thinking": "reasoning",
        },
    ) == {
        "model_id": "m-1",
        "model_name": "gpt-x",
        "cost": "0.002",
        "provider_cost_usd": "0.002",
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 20,
            "total_tokens": 1020,
            "cached_prompt_tokens": 800,
        },
    }


def test_message_is_kept_and_unknown_types_carry_only_it():
    assert _event_projection("BudgetWarning", {"message": "80% used", "x": 1}) == {
        "message": "80% used"
    }
    assert _event_projection("iteration.started", {"iteration": 1}) == {}


class _FakeEventRepository:
    def __init__(self, records):
        self.records = records

    async def list_for_task(self, task_id, *, event_type=None, limit=50, offset=0):
        return self.records[offset : offset + limit], len(self.records)


@pytest.mark.asyncio
async def test_get_events_returns_projections(monkeypatch):
    records = [
        SimpleNamespace(
            id=uuid4(),
            event_type="llm.call.failed",
            timestamp=datetime(2026, 10, 13, tzinfo=UTC),
            data={"error": "Provider rejected the request: bad tool schema", "iteration": 1},
        ),
        SimpleNamespace(
            id=uuid4(),
            event_type="task.failed",
            timestamp=datetime(2026, 10, 13, 0, 0, 1, tzinfo=UTC),
            data={"status": "failed", "success": False, "error": "boom"},
        ),
    ]
    repository = _FakeEventRepository(records)

    @asynccontextmanager
    async def fake_context():
        yield None, None, SimpleNamespace(create_repository=lambda _cls: repository), None, None

    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)

    body = json.loads(await RunsToolset().get_events(str(RUN_ID)))

    assert body["total"] == 2
    assert [e["event_type"] for e in body["events"]] == ["llm.call.failed", "task.failed"]
    assert body["events"][0]["error"] == "Provider rejected the request: bad tool schema"
    assert "message" not in body["events"][0]
    assert body["events"][1] | {"id": None, "timestamp": None} == {
        "id": None,
        "timestamp": None,
        "event_type": "task.failed",
        "status": "failed",
        "success": False,
        "error": "boom",
    }
