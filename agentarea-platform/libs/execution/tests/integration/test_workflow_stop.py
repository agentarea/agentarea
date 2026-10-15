"""Stopping a run, continuing its conversation afterwards, and retrying a failed turn.

A stop cancels the tool call it interrupts: the activity hears it on its next
heartbeat, the run is cancelled at once, and whatever the call still returned,
and cost, is recorded afterwards flagged cancelled. A stopped or failed run
leaves its conversation where a later message, or a retry, continues it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.activities.agent.conversation import pending_entries
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    AgentExecutionResume,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    MCPToolRequest,
    RecordRequest,
    RecordResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent.stopping import STOPPED_WHILE_RUNNING
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.task_log import model_window
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

_log: dict[int, ConversationEntry] = {}
_model_windows: list[list[dict[str, Any]]] = []
_llm_script: list[Callable[[], Any]] = []
_model_runs: list[str] = []
_published: list[dict[str, Any]] = []
_status_requests: list[UpdateTaskStatusRequest] = []
_tool_runs: list[str] = []
_tool_behaviour: dict[str, str] = {}

_POLICY = {
    "budget": {"run_budget_usd": "100.00"},
    "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
    "execution": {
        "max_model_turns": 5,
        "max_tool_calls_per_turn": 10,
        "max_tool_calls_total": 100,
    },
    "tools": {"allowed": ["*"]},
}


def _write(next_seq: int, messages: list[dict[str, Any]]) -> None:
    _log.update((entry.seq, entry) for entry in pending_entries(next_seq, messages))


def _tool_turn() -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_report",
                "type": "function",
                "function": {"name": "build_report", "arguments": json.dumps({"rows": 10})},
            }
        ],
        "finish_reason": "tool_calls",
        "cost": "0.01",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def _completion_turn() -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"complete-{len(_model_windows)}",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": "Report ready", "artifacts": []}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": "0.01",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def _provider_down() -> dict[str, Any]:
    raise ApplicationError("provider unavailable", type="ProviderError", non_retryable=True)


@activity.defn(name="build_agent_config_activity")
async def _build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Stop Agent",
        "model_id": "gpt-4o-mini",
        "description": "Stop test agent",
        "instruction": "Build reports.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _discover_tools(_request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "build_report",
                    "description": "Build a report",
                    "parameters": {"type": "object", "properties": {"rows": {"type": "integer"}}},
                },
            }
        ],
        "context_strategy": "STATIC",
    }


@activity.defn(name="resolve_model_activity")
async def _resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
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
async def _call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Answer from the window the log holds, then the pending entries, as the real one."""
    window = request.conversation
    assert window is not None
    logged = [entry for seq, entry in sorted(_log.items()) if seq < window.next_seq]
    unwritten = pending_entries(window.next_seq, request.messages)
    _model_windows.append([entry.as_message() for entry in (*model_window(logged), *unwritten)])
    turn = _llm_script.pop(0)()
    return await turn if inspect.isawaitable(turn) else turn


async def _model_reply_cut_off() -> dict[str, Any]:
    """A long reply the stop cuts off before the provider reports usage."""
    _model_runs.append("started")
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        _model_runs.append("told to stop")
        raise


async def _model_reply_billed_before_the_stop() -> dict[str, Any]:
    """A reply the provider had already billed for when the stop cut it short."""
    _model_runs.append("started")
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        _model_runs.append("told to stop")
    return {**_tool_turn(), "content": "Building the", "cost": "0.50", "interrupted": True}


@activity.defn(name="execute_mcp_tool_activity")
async def _build_report(request: MCPToolRequest) -> dict[str, Any]:
    """A long call: it either stops when told, or finishes and bills regardless."""
    _tool_runs.append("started")
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        _tool_runs.append("told to stop")
        if _tool_behaviour.get("on_stop") == "stop":
            raise
    return {
        "success": True,
        "result": "Report with 10 rows",
        "tool_name": request.tool_name,
        "managed_by": MANAGED_BY_PLATFORM,
        "usage": {"resource_ref": "reports", "quantity": "10"},
        "cost": "2.50",
    }


@activity.defn(name="publish_workflow_events_activity")
async def _publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    _published.extend(json.loads(raw) for raw in request.events_json)
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _update_task_status(request: UpdateTaskStatusRequest) -> dict[str, bool]:
    _status_requests.append(request)
    if request.conversation is not None:
        _write(request.conversation.next_seq, request.conversation_pending)
    return {"success": True}


@activity.defn(name="validate_artifacts_activity")
async def _validate_artifacts(_request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


@activity.defn(name="record_activity")
async def _record(request: RecordRequest) -> RecordResult:
    for row in request.rows:
        _log.setdefault(
            row.seq,
            ConversationEntry(**row.model_dump(exclude={"event_id"}), event_id=row.event_id),
        )
    if request.status is not None:
        await _update_task_status(request.status)
    if request.events_json:
        await _publish_events(
            WorkflowEventsRequest(
                events_json=request.events_json,
                workspace_id=request.workspace_id,
                user_id=request.user_id,
            )
        )
    return RecordResult(rows=len(request.rows), events=len(request.events_json))


_ACTIVITIES = [
    _build_config,
    _discover_tools,
    _resolve_model,
    _call_llm,
    _build_report,
    _publish_events,
    _record,
    _update_task_status,
    _validate_artifacts,
]


@pytest.fixture(autouse=True)
def _reset() -> None:
    _log.clear()
    _model_windows.clear()
    _llm_script.clear()
    _published.clear()
    _status_requests.clear()
    _tool_runs.clear()
    _tool_behaviour.clear()
    _model_runs.clear()


def _request(task_id: uuid.UUID, resume: AgentExecutionResume | None = None):
    return AgentExecutionRequest(
        task_id=task_id,
        agent_id=uuid.UUID(int=9),
        user_id="stop-user",
        workspace_id="stop-workspace",
        task_query="Build the quarterly report",
        effective_policy=_POLICY,
        resume=resume,
    )


async def _start(env, task_queue: str, request: AgentExecutionRequest, message: str | None = None):
    signal: dict[str, Any] = (
        {
            "start_signal": "workflow_command",
            "start_signal_args": ["queue_message", {"message": message}],
        }
        if message is not None
        else {}
    )
    return await env.client.start_workflow(
        AgentExecutionWorkflow.run,
        request,
        id=f"task-{request.task_id}",
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        task_queue=task_queue,
        execution_timeout=timedelta(days=1),
        **signal,
    )


def _worker(env, task_queue: str, executor) -> Worker:
    # Cancellation reaches an activity on a heartbeat; a short throttle lets the
    # test hear it in milliseconds rather than at 80% of the heartbeat timeout.
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[AgentExecutionWorkflow],
        activities=_ACTIVITIES,
        activity_executor=executor,
        workflow_runner=create_workflow_runner(),
        max_heartbeat_throttle_interval=timedelta(milliseconds=100),
        default_heartbeat_throttle_interval=timedelta(milliseconds=100),
    )


async def _replay(history) -> None:
    await Replayer(
        workflows=[AgentExecutionWorkflow],
        data_converter=pydantic_data_converter,
        workflow_runner=create_workflow_runner(),
    ).replay_workflow(history)


async def _stop_while_the_tool_runs(handle: WorkflowHandle) -> None:
    await _stop_once(handle, _tool_runs)


async def _stop_once(handle: WorkflowHandle, runs: list[str]) -> None:
    for _ in range(400):
        if runs:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("the call never started")
    await handle.cancel()
    with pytest.raises(WorkflowFailureError) as failure:
        await handle.result()
    assert isinstance(failure.value.cause, CancelledError)


def _tool_results() -> list[dict[str, Any]]:
    return [event["data"] for event in _published if event["event_type"] == "tool.result"]


def _event_types() -> list[str]:
    return [event["event_type"] for event in _published]


def _assert_stop_shown_first_and_execution_ended_last(settled_type: str) -> None:
    types = _event_types()
    cancelled = next(e for e in _published if e["event_type"] == "task.cancelled")
    # The stop is final, and the live feed open, before the run waits on the call.
    assert cancelled["data"]["execution_status"] == "settling"
    assert types.index("task.cancelled") < len(types) - 1 - types[::-1].index(settled_type)
    assert types[-1] == "execution.finished"
    assert types.count("execution.finished") == 1


@pytest.mark.asyncio
async def test_stop_cancels_the_running_tool_and_records_it_stopped():
    _tool_behaviour["on_stop"] = "stop"
    _llm_script.append(_tool_turn)
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                handle = await _start(env, task_queue, _request(uuid.uuid4()))
                await _stop_while_the_tool_runs(handle)
                history = await handle.fetch_history()

    assert _tool_runs == ["started", "told to stop"]
    assert len(_model_windows) == 1
    [result] = _tool_results()
    assert result["cancelled"] is True
    assert result["success"] is False
    assert result["error"] == "Stopped before the call finished."
    _assert_stop_shown_first_and_execution_ended_last("tool.result")

    closing = _status_requests[0]
    assert closing.status == "cancelled"
    assert closing.conversation_resume is not None
    assert closing.conversation_resume.next_seq == len(_log)
    assert _log[max(_log)].role == "tool"
    assert _log[max(_log)].tool_call_id == "call_report"
    assert _log[max(_log)].content == STOPPED_WHILE_RUNNING
    # Nothing was billed after the stop, so the closing total stands.
    assert len(_status_requests) == 1
    await _replay(history)


@pytest.mark.asyncio
async def test_a_call_that_finishes_after_the_stop_is_billed_and_flagged():
    _llm_script.append(_tool_turn)
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                handle = await _start(env, task_queue, _request(uuid.uuid4()))
                await _stop_while_the_tool_runs(handle)
                history = await handle.fetch_history()

    assert _tool_runs == ["started", "told to stop"]
    [result] = _tool_results()
    assert result["cancelled"] is True
    assert result["success"] is True
    assert result["managed_by"] == MANAGED_BY_PLATFORM
    assert result["cost"] == "2.50"
    _assert_stop_shown_first_and_execution_ended_last("tool.result")

    closing, rebilled = _status_requests
    assert closing.status == rebilled.status == "cancelled"
    assert closing.total_cost == Decimal("0.01")
    assert rebilled.total_cost == Decimal("2.51")
    await _replay(history)


@pytest.mark.asyncio
async def test_a_message_after_the_stop_continues_the_same_conversation():
    _tool_behaviour["on_stop"] = "stop"
    _llm_script.extend([_tool_turn, _completion_turn])
    task_id = uuid.uuid4()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                stopped = await _start(env, task_queue, _request(task_id))
                await _stop_while_the_tool_runs(stopped)
                closing = _status_requests[-1]
                assert closing.conversation_resume is not None
                resumed = await _start(
                    env,
                    task_queue,
                    _request(
                        task_id,
                        AgentExecutionResume(
                            snapshot=closing.conversation_resume,
                            total_cost=closing.total_cost,
                            own_cost=closing.own_cost,
                        ),
                    ),
                    message="Skip the report, just summarise",
                )
                result = await resumed.result()
                history = await resumed.fetch_history()

    assert result.success is True
    first_window, resumed_window = _model_windows
    assert resumed_window[: len(first_window)] == first_window
    assert resumed_window[len(first_window) :] == [
        _log[len(first_window)].as_message(),
        {
            "role": "tool",
            "content": STOPPED_WHILE_RUNNING,
            "tool_call_id": "call_report",
            "name": "build_report",
        },
        {"role": "user", "content": "Skip the report, just summarise"},
    ]
    assert resumed_window[len(first_window)]["tool_calls"][0]["id"] == "call_report"
    assert _status_requests[-1].status == "completed"
    assert _status_requests[-1].total_cost == Decimal("0.02")
    await _replay(history)


@pytest.mark.asyncio
async def test_retry_reruns_the_failed_turn_on_the_same_conversation():
    _llm_script.extend([_provider_down, _completion_turn])
    task_id = uuid.uuid4()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                failed = await _start(env, task_queue, _request(task_id))
                with pytest.raises(WorkflowFailureError):
                    await failed.result()
                failed_history = await failed.fetch_history()
                closing = _status_requests[-1]
                assert closing.status == "failed"
                assert closing.conversation_resume is not None
                published_before_retry = len(_published)

                retried = await _start(
                    env,
                    task_queue,
                    _request(
                        task_id,
                        AgentExecutionResume(
                            snapshot=closing.conversation_resume,
                            total_cost=closing.total_cost or Decimal(0),
                            retry=True,
                        ),
                    ),
                )
                result = await retried.result()
                retried_history = await retried.fetch_history()

    assert result.success is True
    failed_window, retried_window = _model_windows
    # The same input again: the user's message is not sent a second time.
    assert retried_window == failed_window
    assert [m["role"] for m in retried_window] == ["system", "user"]
    retry_events = [
        event
        for event in _published[published_before_retry:]
        if event["event_type"] == "task.retried"
    ]
    assert len(retry_events) == 1
    assert [e.role for e in _log.values()].count("user") == 1
    await _replay(failed_history)
    await _replay(retried_history)


@pytest.mark.asyncio
async def test_a_model_call_cut_off_by_the_stop_is_recorded_with_its_cost_unknown():
    _llm_script.append(_model_reply_cut_off)
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                handle = await _start(env, task_queue, _request(uuid.uuid4()))
                await _stop_once(handle, _model_runs)
                history = await handle.fetch_history()

    assert _model_runs == ["started", "told to stop"]
    assert [e for e in _published if e["event_type"] == "llm.call.failed"] == []
    [cut_off] = [e["data"] for e in _published if e["event_type"] == "llm.call.completed"]
    assert cut_off["cancelled"] is True
    assert cut_off["cost_known"] is False
    assert cut_off["cost"] is None
    _assert_stop_shown_first_and_execution_ended_last("llm.call.completed")
    assert len(_status_requests) == 1
    assert _tool_runs == []
    await _replay(history)


@pytest.mark.asyncio
async def test_a_model_reply_billed_before_the_stop_is_recorded_and_not_acted_on():
    _llm_script.append(_model_reply_billed_before_the_stop)
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"stop-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with _worker(env, task_queue, executor):
                handle = await _start(env, task_queue, _request(uuid.uuid4()))
                await _stop_once(handle, _model_runs)
                history = await handle.fetch_history()

    [billed] = [e["data"] for e in _published if e["event_type"] == "llm.call.completed"]
    assert billed["cancelled"] is True
    assert billed["interrupted"] is True
    assert billed["cost"] == "0.50"
    assert billed["tool_calls"] == []
    _assert_stop_shown_first_and_execution_ended_last("llm.call.completed")
    # The reply named a tool; the stop came first, so it never ran.
    assert _tool_runs == []
    closing, rebilled = _status_requests
    assert closing.total_cost == Decimal("0")
    assert rebilled.total_cost == Decimal("0.50")
    await _replay(history)
