"""Real Temporal integration tests for workflow start path and observable state transitions."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.models import AgentExecutionRequest, UpdateTaskStatusResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _poll_query_until(
    handle,
    predicate,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.1,
):
    """Poll workflow query until predicate passes or timeout is reached."""
    deadline = time.monotonic() + timeout_seconds
    last_state = None

    while time.monotonic() < deadline:
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        last_state = state
        if predicate(state):
            return state
        await asyncio.sleep(interval_seconds)

    raise AssertionError(f"Timed out waiting for workflow state condition. Last state: {last_state}")


@pytest.fixture
def execution_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="temporal-test-user",
        workspace_id="temporal-test-workspace",
        task_query="Complete deterministic test task",
        task_parameters={"success_criteria": ["Task completed"], "max_iterations": 3},
        budget_usd=2.0,
        requires_human_approval=False,
    )


@pytest.mark.smoke
async def test_workflow_start_path_and_state_query(execution_request: AgentExecutionRequest):
    """Start workflow via start_workflow and assert observable state + persisted completion status."""
    allow_llm_completion = asyncio.Event()
    status_updates: list[dict] = []

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        return {
            "id": str(execution_request.agent_id),
            "name": "Temporal Start Path Test Agent",
            "description": "Deterministic agent for integration testing",
            "instruction": "Complete task by calling completion",
            "model_id": str(uuid4()),
            "tools": [],
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "completion",
                    "description": "Mark task complete",
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        await allow_llm_completion.wait()
        return {
            "role": "assistant",
            "content": "Completing task",
            "tool_calls": [
                {
                    "id": "call_complete",
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "arguments": json.dumps({"result": "completed via start path"}),
                    },
                }
            ],
            "cost": 0.001,
            "usage": {"total_tokens": 25},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(request):
        tool_name = request.get("tool_name") if isinstance(request, dict) else request.tool_name
        tool_args = request.get("tool_args", {}) if isinstance(request, dict) else request.tool_args
        if tool_name == "completion":
            return {"success": True, "completed": True, "result": tool_args.get("result")}
        return {"success": True, "result": "noop"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        return True

    @activity.defn(name="update_task_status_activity")
    async def mock_update_task_status(request):
        payload = request if isinstance(request, dict) else request.model_dump()
        status_updates.append(
            {
                "task_id": payload["task_id"],
                "status": payload["status"],
                "result": payload.get("result"),
                "workspace_id": payload["workspace_id"],
                "total_cost": payload.get("total_cost", 0.0),
            }
        )
        return UpdateTaskStatusResult(success=True)

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="temporal-start-state-queue",
            workflows=[AgentExecutionWorkflow],
            activities=[
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_execute_tool,
                mock_evaluate_goal,
                mock_publish_events,
                mock_update_task_status,
            ],
        ):
            handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"temporal-start-state-{uuid4()}",
                task_queue="temporal-start-state-queue",
                execution_timeout=timedelta(seconds=30),
            )

            in_progress_state = await _poll_query_until(
                handle,
                lambda s: s["status"] == "executing" and s["current_iteration"] >= 1,
            )
            assert in_progress_state["paused"] is False

            allow_llm_completion.set()
            result = await handle.result()

            assert result.success is True
            assert result.reasoning_iterations_used >= 1
            assert status_updates, "Expected at least one persisted task status update"
            assert status_updates[-1]["status"] == "completed"
            assert status_updates[-1]["workspace_id"] == execution_request.workspace_id
    finally:
        await env.shutdown()


async def test_workflow_query_reflects_pause_resume_signal(execution_request: AgentExecutionRequest):
    """Assert pause/resume signals are reflected via workflow state query deterministically."""
    allow_llm_completion = asyncio.Event()

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        return {
            "id": str(execution_request.agent_id),
            "name": "Temporal Query Signal Agent",
            "description": "Deterministic signal/query test",
            "instruction": "Complete task by calling completion",
            "model_id": str(uuid4()),
            "tools": [],
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "completion",
                    "description": "Mark task complete",
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        await allow_llm_completion.wait()
        return {
            "role": "assistant",
            "content": "Completing task after signal checks",
            "tool_calls": [
                {
                    "id": "call_complete_signal",
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "arguments": json.dumps({"result": "completed after pause/resume"}),
                    },
                }
            ],
            "cost": 0.001,
            "usage": {"total_tokens": 30},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(request):
        tool_name = request.get("tool_name") if isinstance(request, dict) else request.tool_name
        tool_args = request.get("tool_args", {}) if isinstance(request, dict) else request.tool_args
        if tool_name == "completion":
            return {"success": True, "completed": True, "result": tool_args.get("result")}
        return {"success": True, "result": "noop"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        return True

    @activity.defn(name="update_task_status_activity")
    async def mock_update_task_status(request):
        return UpdateTaskStatusResult(success=True)

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="temporal-query-signal-queue",
            workflows=[AgentExecutionWorkflow],
            activities=[
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_execute_tool,
                mock_evaluate_goal,
                mock_publish_events,
                mock_update_task_status,
            ],
        ):
            handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"temporal-query-signal-{uuid4()}",
                task_queue="temporal-query-signal-queue",
                execution_timeout=timedelta(seconds=30),
            )

            await _poll_query_until(handle, lambda s: s["status"] == "executing")

            await handle.signal(AgentExecutionWorkflow.pause_execution, "integration test pause")
            paused_state = await _poll_query_until(handle, lambda s: s["paused"] is True)
            assert paused_state["pause_reason"] == "integration test pause"

            await handle.signal(AgentExecutionWorkflow.resume_execution, "integration test resume")
            resumed_state = await _poll_query_until(handle, lambda s: s["paused"] is False)
            assert resumed_state["pause_reason"] == ""

            allow_llm_completion.set()
            result = await handle.result()
            assert result.success is True
    finally:
        await env.shutdown()


async def test_workflow_surfaces_nested_llm_activity_error_details(
    execution_request: AgentExecutionRequest,
):
    """Fail CALL_LLM activity and assert workflow surfaces nested cause details in task status."""
    status_updates: list[dict] = []

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        return {
            "id": str(execution_request.agent_id),
            "name": "Temporal Error Detail Agent",
            "description": "Deterministic error-path test",
            "instruction": "Call LLM",
            "model_id": str(uuid4()),
            "tools": [],
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        return []

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        raise ValueError("invalid model_id: not-a-uuid")

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        return True

    @activity.defn(name="update_task_status_activity")
    async def mock_update_task_status(request):
        payload = request if isinstance(request, dict) else request.model_dump()
        status_updates.append(payload)
        return UpdateTaskStatusResult(success=True)

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="temporal-error-detail-queue",
            workflows=[AgentExecutionWorkflow],
            activities=[
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_publish_events,
                mock_update_task_status,
            ],
        ):
            handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"temporal-error-detail-{uuid4()}",
                task_queue="temporal-error-detail-queue",
                execution_timeout=timedelta(seconds=30),
            )

            with pytest.raises(WorkflowFailureError):
                await handle.result()

            assert status_updates, "Expected failed task status update with error message"
            failed = [u for u in status_updates if u.get("status") == "failed"]
            assert failed, f"Expected at least one failed status update, got: {status_updates}"
            error_message = failed[-1].get("error_message", "")
            assert "Activity task failed" in error_message
            assert "activity=call_llm_activity" in error_message
            assert "cause=ValueError: invalid model_id: not-a-uuid" in error_message
            assert "cause_type=ValueError" in error_message
    finally:
        await env.shutdown()
