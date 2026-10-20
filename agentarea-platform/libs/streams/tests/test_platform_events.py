"""What a task event becomes in the workspace's platform stream."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from agentarea_common.events.contract import (
    APPROVAL_REQUESTED,
    INPUT_REQUEST,
    LLM_COMPLETED,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TOOL_RESULT,
)
from agentarea_streams.domain.envelope import read_event
from agentarea_streams.domain.platform import (
    PLATFORM_SOURCE_TYPE,
    PLATFORM_STATUSES,
    SUMMARY_CHARS,
    PlatformTask,
    platform_event_data,
    platform_event_key,
    projects,
)
from agentarea_streams.domain.source_types import SourceTypeEntry

CATALOG = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"


def _task(depth=0):
    return PlatformTask(
        id=uuid4(), agent_id=uuid4(), owner="u", correlation_id="chain-1", depth=depth
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (TASK_COMPLETED, True),
        (TASK_FAILED, True),
        (TASK_CANCELLED, True),
        (APPROVAL_REQUESTED, True),
        (INPUT_REQUEST, True),
        (LLM_COMPLETED, False),
        (TOOL_RESULT, False),
    ],
)
def test_only_outcomes_and_waits_reach_the_stream(kind, expected):
    assert projects(kind) is expected


def test_a_completed_task_reports_its_result_cost_and_agent():
    task = _task()
    data = platform_event_data(
        TASK_COMPLETED,
        task,
        {"final_response": "done", "total_cost": "0.0123", "tokens_used": 40, "success": True},
    )
    assert data == {
        "task_id": str(task.id),
        "agent_id": str(task.agent_id),
        "kind": TASK_COMPLETED,
        "status": "completed",
        "result": "done",
        "cost": "0.0123",
    }


def test_a_conversational_turn_reports_its_reply_as_the_result():
    data = platform_event_data(
        TASK_COMPLETED, _task(), {"result": "paid", "execution_status": "waiting"}
    )
    assert data["result"] == "paid"


def test_a_failed_task_reports_its_error_and_never_the_detail():
    task = _task()
    data = platform_event_data(
        TASK_FAILED,
        task,
        {
            "error": "model not found",
            "failure_reason": "model_unavailable",
            "error_detail": {"traceback": "long"},
            "total_cost": "0",
        },
    )
    assert data["status"] == "failed"
    assert data["error"] == "model not found"
    assert data["failure_reason"] == "model_unavailable"
    assert "error_detail" not in data


def test_a_cancelled_task_is_cancelled():
    assert platform_event_data(TASK_CANCELLED, _task(), {})["status"] == "cancelled"


def test_an_approval_request_names_the_tool_and_never_its_arguments():
    data = platform_event_data(
        APPROVAL_REQUESTED,
        _task(),
        {
            "escalation_id": "e1",
            "tool_name": "send_payment",
            "arguments": {"card": "4111111111111111"},
            "reason": "over limit",
        },
    )
    assert data["status"] == "waiting_for_approval"
    assert data["tool_name"] == "send_payment"
    assert data["reason"] == "over limit"
    assert "arguments" not in data
    assert "4111" not in str(data)


def test_an_input_request_carries_its_question():
    data = platform_event_data(INPUT_REQUEST, _task(), {"question": "Which account?"})
    assert (data["status"], data["question"]) == ("waiting_for_input", "Which account?")


def test_a_long_result_is_cut_and_secrets_in_it_are_masked():
    data = platform_event_data(
        TASK_COMPLETED,
        _task(),
        {"final_response": "token=sk-abcdefghijklmnopqrstuvwxyz0123 " + "x" * 5000},
    )
    assert len(data["result"]) <= SUMMARY_CHARS + 1
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in data["result"]  # pragma: allowlist secret


def test_the_key_is_the_task_event_id():
    event_id = uuid4()
    assert platform_event_key(TASK_FAILED, event_id, {}) == str(event_id)


def test_one_approval_request_recorded_twice_is_one_event():
    first = platform_event_key(APPROVAL_REQUESTED, uuid4(), {"escalation_id": "e1"})
    again = platform_event_key(APPROVAL_REQUESTED, uuid4(), {"escalation_id": "e1"})
    assert first == again == "approval:e1"


def test_one_input_request_recorded_twice_is_one_event():
    first = platform_event_key(INPUT_REQUEST, uuid4(), {"input_request_id": "r1"})
    again = platform_event_key(INPUT_REQUEST, uuid4(), {"input_request_id": "r1"})
    assert first == again == "input:r1"


def test_the_event_is_one_hop_deeper_than_its_task():
    assert _task(depth=2).event_depth == 3


@pytest.mark.parametrize("kind", sorted(PLATFORM_STATUSES))
def test_the_catalog_entry_names_each_platform_event_by_its_kind(kind: str):
    raw = next(
        entry
        for entry in json.loads(CATALOG.read_text())["source_types"]
        if entry["slug"] == PLATFORM_SOURCE_TYPE
    )
    entry = SourceTypeEntry.model_validate(raw)
    body = platform_event_data(kind, _task(), {})
    assert kind in entry.events
    assert read_event(entry, None, source_id=uuid4(), headers={}, body=body).kind == kind
