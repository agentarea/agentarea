"""Workflow-level deterministic tests for the task control plane.

The HTTP e2e suite (``tests/e2e/api/test_task_control.py``) can only
verify that the API layer doesn't 500 — it can't directly assert that
a pause signal actually paused the workflow, because Temporal's
external execution status stays "running" for signal-based pause.

These tests use ``WorkflowEnvironment.start_time_skipping()`` plus a
mock LLM that blocks on a ``threading.Event``, so we can interleave
signal/query/cancel operations against a live workflow handle and
assert the underlying state changes the API control plane depends on.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.testing.flows import MainFlow
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    LLMCallRequest,
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# ---------------------------------------------------------------------------
# Shared mock activities
# ---------------------------------------------------------------------------
#
# The LLM mock blocks on ``_llm_release`` so the test can land signals
# while the workflow is suspended in the LLM activity. ``_published``
# captures every event the workflow emitted, so tests can assert the
# control-plane events without poking workflow internals.

_llm_release = threading.Event()
_published: list[dict[str, Any]] = []
_status_updates: list[str] = []
_request_input_llm_calls = 0


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
    """Block on the test's release event, then return a completion call.

    Sync ``def`` so the thread-pool executor runs it — blocking on
    ``threading.Event.wait`` here would deadlock an async activity's
    event loop.
    """
    _llm_release.wait(timeout=30)
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_test_1",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": "done"}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@activity.defn(name="call_llm_activity")
def _mock_call_llm_request_input(request: LLMCallRequest) -> dict[str, Any]:
    """First ask for user input, then complete after the queued reply."""
    global _request_input_llm_calls
    _request_input_llm_calls += 1
    if _request_input_llm_calls == 1:
        return {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_input_1",
                    "type": "function",
                    "function": {
                        "name": "request_user_input",
                        "arguments": json.dumps(
                            {
                                "question": "Which environment should I use?",
                                "questions": [
                                    {
                                        "id": "environment",
                                        "question": "Which environment should I use?",
                                        "type": "select",
                                        "options": ["dev", "prod"],
                                        "required": True,
                                    },
                                    {
                                        "id": "api_token",
                                        "question": "API token",
                                        "type": "secret",
                                        "secret_name": "service/api_token",
                                        "required": True,
                                    },
                                ],
                            }
                        ),
                    },
                }
            ],
            "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    tool_payload = None
    for message in request.messages:
        if message.get("name") == "request_user_input":
            tool_payload = json.loads(message["content"])
            break
    assert tool_payload is not None
    assert tool_payload["answers"] == {"environment": "dev"}
    assert tool_payload["secret_refs"]["api_token"]["secret_ref"] == "secret:service/api_token"
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_done_1",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": "continued with input"}),
                },
            }
        ],
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


_ALL_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_call_llm,
    _mock_execute_mcp,
    _mock_publish_events,
    _mock_update_status,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="signal test",
        timeout_seconds=30,
        max_reasoning_iterations=5,
        budget_usd=1.0,
    )


async def _wait_until_initialized(handle, attempts: int = 100) -> None:
    """Block until the workflow has reached the main execution loop.

    Signals fire in their own coroutine and can race the workflow's
    own initialization — if a signal handler that touches
    ``self.event_manager`` lands before ``_initialize_workflow``
    finishes, the event silently drops. The workflow flips
    ``state.status`` to ``"executing"`` at the top of
    ``_execute_main_loop``, after ``event_manager`` is created and
    after ``WORKFLOW_STARTED`` has been published (which clears the
    in-memory event list, so we can't probe by event presence). So
    we poll ``get_current_state`` for that status transition.
    """
    import asyncio

    for _ in range(attempts):
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        if state.get("status") == "executing":
            return
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"workflow never reached executing status; last state={state!r}"
    )


async def _wait_for_status(handle, status: str, attempts: int = 100) -> None:
    import asyncio

    for _ in range(attempts):
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        if state.get("status") == status:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"workflow never reached {status!r}; last state={state!r}")


@pytest.fixture(autouse=True)
def _reset_globals():
    global _request_input_llm_calls
    _llm_release.clear()
    _published.clear()
    _status_updates.clear()
    _request_input_llm_calls = 0
    yield
    # Always release on teardown so a failing test doesn't strand a worker.
    _llm_release.set()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.flow(MainFlow.SIGNALS_HITL)
@pytest.mark.asyncio
async def test_request_user_input_waits_for_queued_reply_then_continues():
    """The built-in request_user_input tool pauses until structured input resumes it."""
    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    )
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        activities = [
            _mock_build_config,
            _mock_discover_tools,
            _mock_resolve_model,
            _mock_call_llm_request_input,
            _mock_execute_mcp,
            _mock_publish_events,
            _mock_update_status,
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=activities,
                activity_executor=executor,
            )
            async with worker:
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _make_request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                await _wait_for_status(handle, "waiting_for_input")
                assert "waiting_for_input" in _status_updates
                state = await handle.query(AgentExecutionWorkflow.get_current_state)
                pending = state["pending_input_requests"]
                assert len(pending) == 1
                input_request_id = next(iter(pending))
                questions = pending[input_request_id]["questions"]
                assert questions[0]["id"] == "environment"
                assert questions[1]["type"] == "secret"

                published_types = {e.get("event_type") for e in _published}
                assert "HumanInputRequested" in published_types, published_types
                assert "WorkflowCompleted" not in published_types, published_types

                await handle.signal(
                    AgentExecutionWorkflow.workflow_command,
                    args=[
                        "submit_user_input",
                        {
                            "input_request_id": input_request_id,
                            "answers": {"environment": "dev"},
                            "secret_refs": {
                                "api_token": {
                                    "secret_name": "service/api_token",
                                    "secret_ref": "secret:service/api_token",
                                }
                            },
                        },
                    ],
                )

                result = await handle.result()

                assert result.success is True
                assert result.final_response == "continued with input"
                assert _request_input_llm_calls == 2
                published_types = {e.get("event_type") for e in _published}
                assert "HumanInputReceived" in published_types, published_types
                assert "WorkflowCompleted" in published_types, published_types
                assert "running" in _status_updates
                assert "completed" in _status_updates


@pytest.mark.asyncio
async def test_pause_resume_signals_flip_queryable_state():
    """``pause_execution`` and ``resume_execution`` flip ``paused`` in the
    state returned by ``get_current_state`` query.

    This is the deterministic ground truth the API control plane reads
    against — e2e tests can only assert "no 500", not the actual flag.
    """
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
                    _make_request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                # The LLM activity is blocked on _llm_release; the workflow
                # is alive but stuck waiting for the LLM. Signals land on
                # the signal handler immediately, independent of the
                # blocking activity.
                await _wait_until_initialized(handle)
                await handle.signal(
                    AgentExecutionWorkflow.pause_execution, "test pause"
                )
                state = await handle.query(AgentExecutionWorkflow.get_current_state)
                assert state["paused"] is True, state
                assert state["pause_reason"] == "test pause", state

                await handle.signal(
                    AgentExecutionWorkflow.resume_execution, "test resume"
                )
                state = await handle.query(AgentExecutionWorkflow.get_current_state)
                assert state["paused"] is False, state
                assert state["pause_reason"] == "", state

                # Let the workflow drain so we don't strand resources.
                _llm_release.set()
                await handle.result()


@pytest.mark.asyncio
async def test_workflow_command_queue_message_publishes_event():
    """``workflow_command("queue_message", ...)`` causes the workflow to
    publish a ``MessageQueued`` event and a ``WorkflowCommandReceived``
    event.

    Signal-recorded events go through ``EventManager.add_event`` with
    ``publish_immediately=True``, so they live in ``_pending_events``
    and never appear in the in-memory ``get_workflow_events`` query —
    instead they get flushed to ``publish_workflow_events_activity``
    on the next workflow yield. Our mock activity captures every
    flushed event into ``_published``, which is what we assert on.

    The API ``/command`` endpoint is a thin signal forwarder — this
    test proves the command actually has the side effect we expect.
    """
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
                    _make_request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                await _wait_until_initialized(handle)
                await handle.signal(
                    AgentExecutionWorkflow.workflow_command,
                    args=["queue_message", {"message": "follow up"}],
                )

                # Release the LLM so the workflow can run iterations
                # and flush its pending events. With time-skipping the
                # 30-min ``_await_follow_up`` timer is skipped instantly.
                _llm_release.set()
                await handle.result()

                published_types = {e.get("event_type") for e in _published}
                assert "MessageQueued" in published_types, published_types
                assert "WorkflowCommandReceived" in published_types, (
                    published_types
                )


@pytest.mark.asyncio
async def test_workflow_command_change_model_swaps_model_and_publishes_event():
    """``workflow_command("change_model", ...)`` swaps the workflow's cached
    resolved model on the fly and publishes a ``ModelChanged`` event.

    This is the mechanism behind the per-task "switch model on the fly" UI:
    the API ``/command`` endpoint resolves a model_instance into this payload
    and forwards it as a signal; the running workflow updates
    ``state.resolved_model`` so the next LLM call uses the new model — no
    workflow restart, no new task.
    """
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
                    _make_request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                await _wait_until_initialized(handle)

                new_model_id = "11111111-1111-1111-1111-111111111111"
                new_model_name = "nvidia/nemotron-3-ultra-550b-a55b:free"
                await handle.signal(
                    AgentExecutionWorkflow.workflow_command,
                    args=[
                        "change_model",
                        {
                            "model_id": new_model_id,
                            "provider_type": "openrouter",
                            "model_name": new_model_name,
                            "endpoint_url": "https://openrouter.ai/api/v1",
                            "context_window": 1000000,
                        },
                    ],
                )

                # Release the LLM so the workflow finishes and flushes its
                # pending events (ModelChanged rides along the same batch).
                _llm_release.set()
                await handle.result()

                published_types = {e.get("event_type") for e in _published}
                assert "ModelChanged" in published_types, published_types
                assert "WorkflowCommandReceived" in published_types, published_types

                # The ModelChanged event carries the new model identity.
                changed = next(
                    e for e in _published if e.get("event_type") == "ModelChanged"
                )
                serialized = json.dumps(changed)
                assert new_model_name in serialized, changed
                assert new_model_id in serialized, changed


@pytest.mark.asyncio
async def test_unknown_workflow_command_is_ignored_no_event():
    """Unknown commands don't emit ``WORKFLOW_COMMAND_RECEIVED``.

    Mirrors the API contract that ``/command`` with an unknown command
    returns 400 and never reaches the workflow with a side effect.
    """
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
                    _make_request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                await _wait_until_initialized(handle)
                await handle.signal(
                    AgentExecutionWorkflow.workflow_command,
                    args=["make_tea", {"sugar": 0}],
                )

                _llm_release.set()
                await handle.result()

                published_types = {e.get("event_type") for e in _published}
                assert "WorkflowCommandReceived" not in published_types, (
                    published_types
                )
