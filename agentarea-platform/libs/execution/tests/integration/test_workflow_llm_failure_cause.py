"""A failed model call ends the run with its classified cause, reported once.

The activity classifies the provider's failure; the transcript's llm.call.failed
and the run's task.failed both say that cause in words the workspace can act on,
keep the provider's raw words in ``error_detail``, and each is published once.
"""

from __future__ import annotations

import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_agents_sdk.models.llm_model import LLMProviderHTTPError
from agentarea_execution.activities.agent.llm import _model_call_failure
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    LLMCallRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.testing import make_record_activity
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_published: list[dict[str, Any]] = []
_status_updates: list[UpdateTaskStatusRequest] = []
_provider_error: Exception | None = None


@activity.defn(name="build_agent_config_activity")
async def _mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "platform-model",
        "description": "Test agent",
        "instruction": "Be helpful.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def _mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "platform-model",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "managed_by": "platform",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="call_llm_activity")
async def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Fails exactly as call_llm_activity fails on the provider's error."""
    if _provider_error is None:
        raise AssertionError("test did not set a provider error")
    raise _model_call_failure(f"LLM call failed: {_provider_error}", _provider_error)


@activity.defn(name="publish_workflow_events_activity")
async def _mock_publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    for raw in request.events_json:
        if raw and raw.strip():
            _published.append(json.loads(raw))
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _mock_update_status(request: UpdateTaskStatusRequest) -> bool:
    _status_updates.append(request)
    return True


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="llm failure test",
        timeout_seconds=30,
        effective_policy={
            "budget": {"run_budget_usd": "1.00"},
            "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
            "execution": {
                "max_model_turns": 5,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 100,
            },
        },
    )


@pytest.fixture(autouse=True)
def _reset_globals():
    _published.clear()
    _status_updates.clear()


def _of_type(event_type: str) -> list[dict[str, Any]]:
    return [e["data"] for e in _published if e.get("event_type") == event_type]


_RECORD = make_record_activity(publish=_mock_publish_events, update_status=_mock_update_status)


async def _run() -> None:
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=[
                    _mock_build_config,
                    _mock_discover_tools,
                    _mock_resolve_model,
                    _mock_call_llm,
                    _mock_publish_events,
                    _RECORD,
                    _mock_update_status,
                ],
                activity_executor=executor,
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                with pytest.raises(WorkflowFailureError):
                    await handle.result()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "cause", "says", "raw"),
    [
        (
            RuntimeError(
                "LLM usage accounting unavailable; token and cost policy cannot be enforced"
            ),
            "usage_unavailable",
            "did not report token usage",
            "usage accounting unavailable",
        ),
        (
            ValueError("Failed to decrypt secret. Key may have changed."),
            "credentials_undecryptable",
            "re-enter the key",
            "Failed to decrypt secret",
        ),
        (
            LLMProviderHTTPError(400, "Invalid schema for function 'search'"),
            "provider_bad_request",
            "invalid schema for function 'search'",
            "HTTP 400",
        ),
    ],
    ids=["no_usage", "decrypt", "provider_400"],
)
async def test_a_failed_model_call_reports_its_cause_once(
    error: Exception, cause: str, says: str, raw: str
):
    global _provider_error
    _provider_error = error

    await _run()

    llm_failed = _of_type("llm.call.failed")
    assert len(llm_failed) == 1
    assert llm_failed[0]["failure_reason"] == cause
    assert says in llm_failed[0]["error"].lower()
    assert raw in llm_failed[0]["error_detail"]

    task_failed = _of_type("task.failed")
    assert len(task_failed) == 1
    assert task_failed[0]["failure_reason"] == cause
    assert task_failed[0]["error"] == llm_failed[0]["error"]
    assert "Failed to get a response" not in task_failed[0]["error"]
    assert raw in task_failed[0]["error_detail"]


@pytest.mark.asyncio
async def test_a_provider_out_of_credits_blocks_the_run_with_one_failure_event():
    global _provider_error
    _provider_error = LLMProviderHTTPError(402, "Insufficient credits")

    await _run()

    task_failed = _of_type("task.failed")
    assert len(task_failed) == 1
    assert task_failed[0]["failure_reason"] == "provider_out_of_credits"
    assert task_failed[0]["blocked"] is True
    assert "out of credits" in task_failed[0]["blocked_reason"]
    assert len(_of_type("llm.call.failed")) == 1
    assert _status_updates[-1].status == "blocked"
