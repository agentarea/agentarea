"""The workspace monthly spend cap is re-checked when a run actually executes.

Submission rejects a run once the cap is reached, but a run scheduled, paused
or waiting for a follow-up executes later. The workflow reads the current
month-to-date spend before its first model call and again whenever it wakes,
and ends the run as ``monthly_spend_cap_exceeded`` instead of executing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.money import to_money
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    MCPToolRequest,
    MonthlySpendCapRequest,
    MonthlySpendCapResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent.patches import MONTHLY_CAP_AT_START_PATCH
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity, workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

_llm_release = threading.Event()
_published: list[dict[str, Any]] = []
_status_updates: list[str] = []
_cap_checks: list[MonthlySpendCapRequest] = []
_cap_reached = False
_llm_calls = 0
_llm_script: list[str] = []


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
        "events_config": {},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


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
def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Follow ``_llm_script`` ("probe" or "complete"), blocking until released."""
    global _llm_calls
    _llm_release.wait(timeout=30)
    _llm_calls += 1
    step = _llm_script[_llm_calls - 1] if _llm_calls <= len(_llm_script) else "complete"
    if step == "probe":
        tool_call = {
            "id": f"call_probe_{_llm_calls}",
            "type": "function",
            "function": {"name": "probe_tool", "arguments": "{}"},
        }
    else:
        tool_call = {
            "id": f"call_done_{_llm_calls}",
            "type": "function",
            "function": {
                "name": "completion",
                "arguments": json.dumps({"result": "done", "artifacts": []}),
            },
        }
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [tool_call],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@activity.defn(name="execute_mcp_tool_activity")
async def _mock_execute_mcp(request: MCPToolRequest) -> dict[str, Any]:
    return {"success": True, "result": "Mock", "tool_name": request.tool_name}


@activity.defn(name="publish_workflow_events_activity")
async def _mock_publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    for raw in request.events_json:
        if raw and raw.strip():
            _published.append(json.loads(raw))
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _mock_update_status(request: UpdateTaskStatusRequest) -> bool:
    _status_updates.append(request.status)
    return True


@activity.defn(name="validate_artifacts_activity")
async def _mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


@activity.defn(name="check_monthly_spend_cap_activity")
async def _mock_check_monthly_cap(request: MonthlySpendCapRequest) -> MonthlySpendCapResult:
    _cap_checks.append(request)
    spent = request.cap_usd if _cap_reached else to_money("0")
    return MonthlySpendCapResult(
        exceeded=_cap_reached,
        month_to_date_usd=spent,
        cap_usd=request.cap_usd,
    )


_ALL_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_call_llm,
    _mock_execute_mcp,
    _mock_publish_events,
    _mock_update_status,
    _mock_validate_artifacts,
    _mock_check_monthly_cap,
]


def _make_request(monthly_cap_usd: str | None = "10.00") -> AgentExecutionRequest:
    budget: dict[str, Any] = {"run_budget_usd": "1.00"}
    if monthly_cap_usd is not None:
        budget["monthly_spend_cap_usd"] = monthly_cap_usd
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="monthly cap test",
        timeout_seconds=30,
        effective_policy={
            "budget": budget,
            "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
            "execution": {
                "max_model_turns": 5,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 100,
            },
        },
    )


async def _wait_for(predicate, what: str, attempts: int = 200) -> None:
    for _ in range(attempts):
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"workflow never reached {what}")


def _failed_event() -> dict[str, Any]:
    return next(e for e in _published if e.get("event_type") == "task.failed")


async def _replay(history) -> None:
    await Replayer(
        workflows=[AgentExecutionWorkflow],
        data_converter=pydantic_data_converter,
        workflow_runner=create_workflow_runner(),
    ).replay_workflow(history)


async def _run(request: AgentExecutionRequest, drive, *, start_delay: timedelta | None = None):
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
                workflow_runner=create_workflow_runner(),
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(days=2),
                    start_delay=start_delay,
                )
                await drive(handle)
                result = await asyncio.wait_for(handle.result(), timeout=60)
                await _replay(await handle.fetch_history())
                return result


@pytest.fixture(autouse=True)
def _reset_globals():
    global _cap_reached, _llm_calls
    _llm_release.clear()
    _published.clear()
    _status_updates.clear()
    _cap_checks.clear()
    _llm_script.clear()
    _cap_reached = False
    _llm_calls = 0
    yield
    _llm_release.set()


def _assert_ended_on_monthly_cap(result) -> None:
    assert result.success is False
    assert result.status == "failed"
    assert result.failure_reason == "monthly_spend_cap_exceeded"
    assert "monthly spend cap" in (result.error_message or "").lower()
    assert _status_updates[-1] == "failed"
    failed = _failed_event()
    assert failed["data"]["failure_reason"] == "monthly_spend_cap_exceeded"


@pytest.mark.asyncio
async def test_scheduled_run_that_starts_after_the_cap_was_reached_does_not_execute():
    global _cap_reached
    _cap_reached = True
    _llm_release.set()

    async def drive(_handle) -> None:
        return None

    result = await _run(_make_request(), drive, start_delay=timedelta(hours=6))

    _assert_ended_on_monthly_cap(result)
    assert _llm_calls == 0
    assert [str(check.cap_usd) for check in _cap_checks] == ["10.00"]
    assert _cap_checks[0].workspace_id == "test-workspace"


@pytest.mark.asyncio
async def test_run_under_the_cap_executes():
    _llm_release.set()

    async def drive(_handle) -> None:
        return None

    result = await _run(_make_request(), drive)

    assert result.success is True
    assert _llm_calls == 1
    assert len(_cap_checks) == 1


@pytest.mark.asyncio
async def test_run_without_a_monthly_cap_does_not_check_spend():
    _llm_release.set()

    async def drive(_handle) -> None:
        return None

    result = await _run(_make_request(monthly_cap_usd=None), drive)

    assert result.success is True
    assert _cap_checks == []


@pytest.mark.asyncio
async def test_resume_after_pause_is_refused_once_the_cap_is_reached():
    _llm_script.extend(["probe", "complete"])

    async def drive(handle) -> None:
        global _cap_reached

        async def executing() -> bool:
            state = await handle.query(AgentExecutionWorkflow.get_current_state)
            return state.get("status") == "executing"

        await _wait_for(executing, "executing")
        await handle.signal(AgentExecutionWorkflow.pause_execution, "hold")
        _cap_reached = True
        _llm_release.set()

        async def parked_on_pause() -> bool:
            if not any(e.get("event_type") == "IterationCompleted" for e in _published):
                return False
            description = await handle.describe()
            return not description.raw_description.pending_activities

        await _wait_for(parked_on_pause, "the pause after the first iteration")
        # A query is answered only after the pending workflow task, so the loop
        # is parked on the pause before the resume signal lands.
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["paused"] is True
        await handle.signal(AgentExecutionWorkflow.resume_execution, "go")

    result = await _run(_make_request(), drive)

    _assert_ended_on_monthly_cap(result)
    assert _llm_calls == 1
    assert len(_cap_checks) == 2


@pytest.mark.asyncio
async def test_follow_up_after_the_cap_is_reached_is_refused():
    _llm_release.set()

    async def drive(handle) -> None:
        global _cap_reached

        async def completed_turn() -> bool:
            return any(e.get("event_type") == "task.completed" for e in _published)

        await _wait_for(completed_turn, "the first completed turn")
        _cap_reached = True
        await handle.signal(
            AgentExecutionWorkflow.workflow_command,
            args=["queue_message", {"message": "one more thing"}],
        )

    result = await _run(_make_request(), drive)

    _assert_ended_on_monthly_cap(result)
    assert _llm_calls == 1
    assert len(_cap_checks) == 2


@pytest.mark.asyncio
async def test_history_recorded_before_the_cap_check_still_replays(monkeypatch):
    """A run recorded by a worker without the check replays on one that has it.

    The recording worker answers ``monthly-cap-at-start`` as a pre-patch worker
    would, so its history has neither the patch marker nor the cap activity.
    """
    _llm_script.extend(["probe", "complete"])
    _llm_release.set()
    patched = workflow.patched

    def without_monthly_cap_patch(patch_id: str) -> bool:
        return False if patch_id == MONTHLY_CAP_AT_START_PATCH else patched(patch_id)

    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            with monkeypatch.context() as recording:
                recording.setattr(workflow, "patched", without_monthly_cap_patch)
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AgentExecutionWorkflow],
                    activities=_ALL_ACTIVITIES,
                    activity_executor=executor,
                    workflow_runner=create_workflow_runner(),
                    max_cached_workflows=0,
                ):
                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        _make_request(),
                        id=f"test-{uuid.uuid4()}",
                        task_queue=task_queue,
                        execution_timeout=timedelta(days=2),
                    )
                    result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()

    assert result.success is True
    assert _cap_checks == []
    await _replay(history)
