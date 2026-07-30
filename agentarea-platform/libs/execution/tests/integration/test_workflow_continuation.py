"""Workflow-level tests for iteration-limit continuation semantics.

When the agent exhausts max_iterations (or budget), the workflow must not
fail immediately: it enters ``waiting_for_continuation`` (DB status +
``task.awaiting_continuation`` event) and idles on a Temporal timer until
either a ``continue_execution`` workflow command grants more iterations /
budget, or the continuation window expires and the run finalizes with the
original failure_reason. Delegation children never wait — their parent owns
the conversation.

Uses ``WorkflowEnvironment.start_time_skipping()`` like
``test_workflow_signals.py``: queries/signals land in real time, and
awaiting the workflow result fast-forwards timers (the 24h continuation
window, the 30-min follow-up wait).
"""

from __future__ import annotations

import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.money import serialize_money, to_money
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskGovernanceSnapshotRequest,
    UpdateTaskGovernanceSnapshotResult,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from agentarea_governance.domain.policies import effective_policy_from_json
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_published: list[dict[str, Any]] = []
_status_updates: list[str] = []
_llm_calls = 0
_complete_on_call: int | None = None
_governance_snapshots: list[dict[str, Any]] = []


@activity.defn(name="build_agent_config_activity")
async def _mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "description": "Test agent",
        "instruction": "Be helpful.",
        "tools_config": {"mcp_servers": []},
        "events_config": {},
        "planning": False,
        "context_window": 128000,
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
async def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Call a throwaway tool each turn; call completion on ``_complete_on_call``."""
    global _llm_calls
    _llm_calls += 1
    if _complete_on_call is not None and _llm_calls >= _complete_on_call:
        tool_call = {
            "id": f"call_done_{_llm_calls}",
            "type": "function",
            "function": {
                "name": "completion",
                "arguments": json.dumps({"result": "finished after continuation"}),
            },
        }
    else:
        tool_call = {
            "id": f"call_probe_{_llm_calls}",
            "type": "function",
            "function": {"name": "probe_tool", "arguments": json.dumps({})},
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
        if not raw or not raw.strip():
            continue
        try:
            _published.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _mock_update_status(request: UpdateTaskStatusRequest) -> bool:
    _status_updates.append(request.status)
    return True


@activity.defn(name="update_task_governance_snapshot_activity")
async def _mock_update_governance_snapshot(
    request: UpdateTaskGovernanceSnapshotRequest,
) -> UpdateTaskGovernanceSnapshotResult:
    _governance_snapshots.append(request.governance_snapshot)
    return UpdateTaskGovernanceSnapshotResult(success=True)


@activity.defn(name="validate_artifacts_activity")
async def _mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


_ALL_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_call_llm,
    _mock_execute_mcp,
    _mock_publish_events,
    _mock_update_status,
    _mock_update_governance_snapshot,
    _mock_validate_artifacts,
]


def _policy(*, max_model_turns: int, run_budget_usd: str) -> dict[str, Any]:
    return effective_policy_from_json(
        {
            "budget": {"run_budget_usd": run_budget_usd},
            "tokens": {
                "max_tokens": 20_000,
                "max_tokens_per_call": 2_000,
            },
            "execution": {
                "max_model_turns": max_model_turns,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 100,
            },
        }
    ).to_json_dict()


def _continuation_payload(
    *,
    current_iterations: int,
    current_budget_usd: str,
    additional_iterations: int = 0,
    additional_budget_usd: str | None = None,
) -> dict[str, Any]:
    next_budget = to_money(current_budget_usd) + to_money(additional_budget_usd or "0")
    policy = _policy(
        max_model_turns=current_iterations + additional_iterations,
        run_budget_usd=serialize_money(next_budget),
    )
    payload: dict[str, Any] = {
        "additional_iterations": additional_iterations,
        "effective_policy": policy,
        "governance_snapshot": {
            "effective_policy": policy,
            "revision": 2,
        },
    }
    if additional_budget_usd is not None:
        payload["additional_budget_usd"] = additional_budget_usd
    return payload


def _make_request(
    max_iterations: int = 1,
    budget_usd: float = 1.0,
    workflow_metadata: dict[str, Any] | None = None,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="continuation test",
        timeout_seconds=30,
        max_reasoning_iterations=max_iterations,
        budget_usd=budget_usd,
        workflow_metadata=workflow_metadata or {},
        effective_policy=_policy(
            max_model_turns=max_iterations,
            run_budget_usd=str(budget_usd),
        ),
    )


async def _wait_for_status(handle, status: str, attempts: int = 200) -> None:
    import asyncio

    state: dict[str, Any] = {}
    for _ in range(attempts):
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        if state.get("status") == status:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"workflow never reached {status!r}; last state={state!r}")


async def _wait_for_event(event_type: str, attempts: int = 200) -> None:
    import asyncio

    for _ in range(attempts):
        if event_type in _published_types():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"workflow never published {event_type!r}")


@pytest.fixture(autouse=True)
def _reset_globals():
    global _llm_calls, _complete_on_call
    _published.clear()
    _status_updates.clear()
    _governance_snapshots.clear()
    _llm_calls = 0
    _complete_on_call = None
    return


def _published_types() -> set[str]:
    return {e.get("event_type") for e in _published}


@pytest.mark.asyncio
async def test_iteration_limit_waits_then_continuation_update_completes_task():
    """Limit reached -> waiting_for_continuation; the update resumes to success."""
    global _complete_on_call
    _complete_on_call = 2

    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(max_iterations=1),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(days=2),
                )

                await _wait_for_status(handle, "waiting_for_continuation")
                await _wait_for_event("task.awaiting_continuation")
                assert "waiting_for_continuation" in _status_updates
                assert "task.awaiting_continuation" in _published_types()
                assert "task.failed" not in _published_types()
                assert "task.completed" not in _published_types()

                awaiting_event = next(
                    e for e in _published if e.get("event_type") == "task.awaiting_continuation"
                )
                assert awaiting_event["data"]["failure_reason"] == "iteration_limit"
                assert awaiting_event["data"]["iterations_used"] == 1

                update_result = await handle.execute_update(
                    AgentExecutionWorkflow.continue_execution,
                    _continuation_payload(
                        current_iterations=1,
                        current_budget_usd="1.0",
                        additional_iterations=2,
                    ),
                )
                assert update_result["accepted"] is True
                assert update_result["max_iterations"] == 3
                assert len(_governance_snapshots) == 1

                result = await handle.result()

                assert result.success is True
                assert result.final_response == "finished after continuation"
                assert result.reasoning_iterations_used == 2
                assert "running" in _status_updates
                assert "completed" in _status_updates
                assert _status_updates.index("waiting_for_continuation") < _status_updates.index(
                    "running"
                )


@pytest.mark.asyncio
async def test_continuation_window_timeout_finalizes_with_original_failure():
    """No continue signal -> after the wait window the task fails with iteration_limit."""
    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(max_iterations=1),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(days=2),
                )

                result = await handle.result()

                assert result.success is False
                assert result.failure_reason == "iteration_limit"
                assert "waiting_for_continuation" in _status_updates
                assert "failed" in _status_updates
                assert "task.failed" in _published_types()


@pytest.mark.asyncio
async def test_budget_exceeded_waits_and_budget_topup_resumes():
    """Budget exhaustion enters the same wait; additional budget resumes the loop."""
    global _complete_on_call
    _complete_on_call = 2

    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(max_iterations=5, budget_usd=0.0005),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(days=2),
                )

                await _wait_for_status(handle, "waiting_for_continuation")
                await _wait_for_event("task.awaiting_continuation")
                awaiting_event = next(
                    e for e in _published if e.get("event_type") == "task.awaiting_continuation"
                )
                assert awaiting_event["data"]["failure_reason"] == "budget_exceeded"

                update_result = await handle.execute_update(
                    AgentExecutionWorkflow.continue_execution,
                    _continuation_payload(
                        current_iterations=5,
                        current_budget_usd="0.0005",
                        additional_budget_usd="1.0",
                    ),
                )
                assert update_result["accepted"] is True

                result = await handle.result()

                assert result.success is True
                assert result.final_response == "finished after continuation"


@pytest.mark.asyncio
async def test_delegation_child_fails_fast_without_waiting():
    """Children spawned via agent delegation never enter waiting_for_continuation."""
    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(
                        max_iterations=1,
                        workflow_metadata={"source": "agent_delegation"},
                    ),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=10),
                )

                result = await handle.result()

                assert result.success is False
                assert result.failure_reason == "iteration_limit"
                assert "waiting_for_continuation" not in _status_updates
                assert "task.awaiting_continuation" not in _published_types()


@pytest.mark.asyncio
async def test_continue_signal_ignored_when_not_waiting():
    """continue_execution outside the wait must be a no-op, not a crash."""
    global _complete_on_call
    _complete_on_call = 1

    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=_ALL_ACTIVITIES,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(max_iterations=3),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                await handle.signal(
                    AgentExecutionWorkflow.workflow_command,
                    args=["continue_execution", {"additional_iterations": 5}],
                )

                result = await handle.result()

                assert result.success is True
                assert "waiting_for_continuation" not in _status_updates
