"""A governance gate that refuses the model call ends the run with its reason.

The gate denies before the provider is called (no credits, a model the plan does
not price, billing unreachable). The run cannot make progress until someone acts
on that reason, so it ends blocked with the gate's code as ``failure_reason`` and
a sentence the user can act on, not a generic model error.
"""

from __future__ import annotations

import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
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
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_governance.bridges.temporal_bridge import _verdict_failure
from agentarea_governance.domain.enums import InterceptorAction, Phase
from agentarea_governance.domain.exceptions import GovernanceDeniedError
from agentarea_governance.domain.models import InterceptorResult
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_published: list[dict[str, Any]] = []
_status_updates: list[UpdateTaskStatusRequest] = []
_verdict: InterceptorResult | None = None


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
    """Refused by the gate exactly as the governance activity interceptor refuses it."""
    if _verdict is None:
        raise AssertionError("test did not set a verdict")
    raise _verdict_failure(GovernanceDeniedError, _verdict, Phase.PRE_LLM_CALL)


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


_ALL_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_call_llm,
    _mock_publish_events,
    _mock_update_status,
]


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="governance denial test",
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


def _deny(interceptor: str, reason: str, code: str | None) -> InterceptorResult:
    return InterceptorResult(
        action=InterceptorAction.DENY,
        interceptor_name=interceptor,
        reason=reason,
        metadata={"entitlement_code": code} if code else {},
    )


@pytest.fixture(autouse=True)
def _reset_globals():
    _published.clear()
    _status_updates.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "failure_reason", "says"),
    [
        (_deny("entitlement_guard", "no credits remaining", "no_credits"), "no_credits", "top up"),
        (
            _deny(
                "entitlement_guard", "this model is not available on your plan", "model_unpriced"
            ),
            "model_unpriced",
            "not available on your plan",
        ),
        (
            _deny("entitlement_guard", "billing temporarily unavailable", "billing_unavailable"),
            "billing_unavailable",
            "temporarily unavailable",
        ),
        (
            _deny("prompt_injection_detector", "prompt injection detected", None),
            "governance_denied",
            "prompt injection detected",
        ),
    ],
    ids=["no_credits", "model_unpriced", "billing_unavailable", "policy"],
)
async def test_gate_denial_blocks_the_run_with_its_reason(
    verdict: InterceptorResult, failure_reason: str, says: str
):
    global _verdict
    _verdict = verdict

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
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _request(),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(minutes=10),
                )
                result = await handle.result()

    assert result.success is False
    assert result.status == "blocked"
    assert result.failure_reason == failure_reason
    message = result.error_message or ""
    assert says in message.lower()
    assert "Failed to get a response" not in message

    failed = next(e for e in _published if e.get("event_type") == "task.failed")
    assert failed["data"]["failure_reason"] == failure_reason
    assert failed["data"]["error"] == message
    # The transcript's model part says why, not a raw Temporal failure.
    llm_failed = [e for e in _published if e.get("event_type") == "llm.call.failed"]
    assert [e["data"]["error"] for e in llm_failed] == [message]

    final = _status_updates[-1]
    assert final.status == "blocked"
    assert final.error_message == message
