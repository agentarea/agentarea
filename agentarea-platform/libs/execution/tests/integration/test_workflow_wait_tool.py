"""The workflow-builtin ``wait`` tool: a durable timer, not an activity.

Driven through ``WorkflowEnvironment.start_time_skipping()``: the server skips
timers only while a test awaits the workflow result, so a test can land a
signal mid-wait before asking for the result.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent.wait import WAIT_MAX_SECONDS
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

_published: list[dict[str, Any]] = []
_llm_requests: list[LLMCallRequest] = []
_llm_script: list[Callable[[LLMCallRequest], dict[str, Any]]] = []
_mcp_calls: list[str] = []
_discovered_tools: list[dict[str, Any]] = []


def _function(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _turn(*calls: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            for call_id, name, arguments in calls
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _tool_turn(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _turn((call_id, name, arguments))


def _wait_turn(seconds: Any, reason: str = "video render") -> Callable[..., dict[str, Any]]:
    return lambda _request: _tool_turn("call_wait", "wait", {"seconds": seconds, "reason": reason})


def _complete_turn(_request: LLMCallRequest) -> dict[str, Any]:
    return _tool_turn("call_done", "completion", {"result": "done", "artifacts": []})


@activity.defn(name="build_agent_config_activity")
async def _mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "description": "Test agent",
        "instruction": "Be helpful.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": list(_discovered_tools), "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def _mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id or "gpt-4o-mini",
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "display_name": "GPT-4o Mini",
        "provider_display_name": "OpenAI",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="call_llm_activity")
async def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    _llm_requests.append(request)
    return _llm_script.pop(0)(request)


@activity.defn(name="execute_mcp_tool_activity")
async def _mock_execute_mcp(request: MCPToolRequest) -> dict[str, Any]:
    _mcp_calls.append(request.tool_name)
    assert _wait_events("tool.result"), "the tool ran before the wait the model asked for first"
    return {"success": True, "result": "Mock", "tool_name": request.tool_name}


@activity.defn(name="publish_workflow_events_activity")
async def _mock_publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    _published.extend(json.loads(raw) for raw in request.events_json)
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _mock_update_status(request: UpdateTaskStatusRequest) -> bool:
    return True


@activity.defn(name="validate_artifacts_activity")
async def _mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_call_llm,
    _mock_execute_mcp,
    _mock_publish_events,
    _mock_update_status,
    _mock_validate_artifacts,
]


def _make_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="render a video",
        timeout_seconds=30,
        effective_policy={
            "budget": {"run_budget_usd": "1.00"},
            "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
            "execution": {
                "max_model_turns": 5,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 100,
            },
            "tools": {"allowed": ["*"]},
        },
    )


@pytest.fixture(autouse=True)
def _reset_globals():
    _published.clear()
    _llm_requests.clear()
    _llm_script.clear()
    _mcp_calls.clear()
    _discovered_tools.clear()


def _wait_events(event_type: str) -> list[dict[str, Any]]:
    return [
        event
        for event in _published
        if event["event_type"] == event_type and event["data"].get("tool_name") == "wait"
    ]


def _wait_tool_message(request: LLMCallRequest) -> dict[str, Any]:
    return next(m for m in request.messages if m.get("tool_call_id") == "call_wait")


async def _run(drive: Callable[[Any], Any] | None = None):
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[AgentExecutionWorkflow],
            activities=_ACTIVITIES,
            workflow_runner=create_workflow_runner(),
        ):
            handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                _make_request(),
                id=f"test-{uuid.uuid4()}",
                task_queue=task_queue,
                execution_timeout=timedelta(hours=2),
            )
            if drive is not None:
                await drive(handle)
            result = await handle.result()
            history = await handle.fetch_history()
            await Replayer(
                workflows=[AgentExecutionWorkflow],
                data_converter=pydantic_data_converter,
                workflow_runner=create_workflow_runner(),
            ).replay_workflow(history)
            return result, history


@pytest.mark.asyncio
async def test_wait_sleeps_on_a_durable_timer_and_reports_the_full_wait():
    _llm_script.extend([_wait_turn(120), _complete_turn])

    result, history = await _run()

    assert result.success is True
    assert _mcp_calls == []
    timers = [
        event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
    ]
    assert timedelta(seconds=120) in timers
    assert any(e.event_type == EventType.EVENT_TYPE_TIMER_FIRED for e in history.events)

    offered = {tool["function"]["name"] for tool in _llm_requests[0].tools}
    assert "wait" in offered

    started = _wait_events("tool.call")
    assert [e["data"]["arguments"] for e in started] == [{"seconds": 120, "reason": "video render"}]
    finished = _wait_events("tool.result")
    assert len(finished) == 1
    assert finished[0]["data"]["success"] is True
    assert finished[0]["data"]["waited_seconds"] == 120
    assert finished[0]["data"]["woken_by"] is None

    tool_message = _wait_tool_message(_llm_requests[1])
    assert tool_message["name"] == "wait"
    assert "120" in tool_message["content"]
    assert "video render" in tool_message["content"]


@pytest.mark.asyncio
async def test_a_user_message_wakes_the_wait_early():
    _llm_script.extend([_wait_turn(WAIT_MAX_SECONDS), _complete_turn])

    async def drive(handle):
        for _ in range(200):
            if _wait_events("tool.call"):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the wait never started")
        await handle.signal(
            AgentExecutionWorkflow.workflow_command,
            args=["queue_message", {"message": "the render finished, check now"}],
        )

    result, _history = await _run(drive)

    assert result.success is True
    finished = _wait_events("tool.result")
    assert len(finished) == 1
    assert finished[0]["data"]["success"] is True
    assert finished[0]["data"]["woken_by"] == "user_message"
    assert finished[0]["data"]["waited_seconds"] < WAIT_MAX_SECONDS

    second_turn = _llm_requests[1].messages
    tool_index = next(i for i, m in enumerate(second_turn) if m.get("tool_call_id") == "call_wait")
    assert "user message" in second_turn[tool_index]["content"]
    assert second_turn[tool_index + 1]["role"] == "user"
    assert second_turn[tool_index + 1]["content"] == "the render finished, check now"


@pytest.mark.parametrize("seconds", [0, WAIT_MAX_SECONDS + 1, "60", True, 1.5])
@pytest.mark.asyncio
async def test_out_of_range_wait_is_rejected_to_the_model_without_a_timer(seconds):
    _llm_script.extend([_wait_turn(seconds), _complete_turn])

    result, history = await _run()

    assert result.success is True
    timers = [
        event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
    ]
    assert all(timer >= timedelta(minutes=30) for timer in timers), timers
    assert _wait_events("tool.call") == []
    finished = _wait_events("tool.result")
    assert len(finished) == 1
    assert finished[0]["data"]["success"] is False

    tool_message = _wait_tool_message(_llm_requests[1])
    payload = json.loads(tool_message["content"])
    assert payload["status"] == "invalid_wait_arguments"
    assert str(WAIT_MAX_SECONDS) in payload["error"]


@pytest.mark.asyncio
async def test_cancelling_the_task_ends_the_wait_and_closes_its_tool_row():
    from temporalio.client import WorkflowFailureError
    from temporalio.exceptions import CancelledError

    _llm_script.extend([_wait_turn(WAIT_MAX_SECONDS)])

    async def drive(handle):
        for _ in range(200):
            if _wait_events("tool.call"):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the wait never started")
        await handle.cancel()

    with pytest.raises(WorkflowFailureError) as failure:
        await _run(drive)

    assert isinstance(failure.value.cause, CancelledError)
    assert len(_llm_requests) == 1
    finished = _wait_events("tool.result")
    assert [e["data"]["success"] for e in finished] == [False]
    assert "task.cancelled" in {e["event_type"] for e in _published}


@pytest.mark.asyncio
async def test_wait_runs_in_the_position_the_model_called_it():
    _discovered_tools.append(_function("get_video"))
    _llm_script.extend(
        [
            lambda _request: _turn(
                ("call_wait", "wait", {"seconds": 60, "reason": "video render"}),
                ("call_poll", "get_video", {}),
            ),
            _complete_turn,
        ]
    )

    result, _history = await _run()

    assert result.success is True
    assert _mcp_calls == ["get_video"]
    order = [m["tool_call_id"] for m in _llm_requests[1].messages if m.get("role") == "tool"]
    assert order == ["call_wait", "call_poll"]


@pytest.mark.asyncio
async def test_a_discovered_tool_named_wait_is_refused_not_shadowed():
    from temporalio.client import WorkflowFailureError

    _discovered_tools.append(_function("wait"))
    _llm_script.extend([_wait_turn(60), _complete_turn])

    with pytest.raises(WorkflowFailureError) as failure:
        await _run()

    assert "reserved" in str(failure.value.cause)
    assert _llm_requests == []
    assert _mcp_calls == []
