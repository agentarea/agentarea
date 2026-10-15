"""A model call billing held runs through the workflow with its charge (ADR-0038 rev 2).

The activity returns what the call costs as billing says it, and the hold the
settlement worker captures, inside ``usage``. The workflow carries both onto the
``llm.call.completed`` event unchanged, and counts the billed amount against the
run budget. No workflow command changes: the history this records replays like the
ones before holds.
"""

import concurrent.futures
import json
import uuid
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
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.testing import make_record_activity
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

published: list[dict] = []
BILLING = {
    "amount": "2.85",
    "currency": "RUB",
    "vendor_cost": "0.02",
    "vendor_currency": "USD",
    "estimate": True,
    "settle": "capture",
    "hold_id": "hold-1",
}


@activity.defn(name="build_agent_config_activity")
async def build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Held Agent",
        "model_id": "model-1",
        "description": "",
        "instruction": "You are a helpful assistant.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "kimi-k2.6",
        "api_key_secret": None,
        "managed_by": "platform",
        "endpoint_url": None,
        "context_window": 128000,
        "resolved_at": "2026-10-14T00:00:00+00:00",
    }


@activity.defn(name="call_llm_activity")
async def call_llm(request: LLMCallRequest) -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": "done", "artifacts": []}),
                },
            }
        ],
        "cost": "2.85",
        "provider_cost_usd": "0.02",
        "currency": "RUB",
        "managed_by": "platform",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cached_prompt_tokens": 80,
            "billing": BILLING,
        },
    }


@activity.defn(name="publish_workflow_events_activity")
async def publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    published.extend(json.loads(raw) for raw in request.events_json if raw and raw.strip())
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def update_task_status(request: UpdateTaskStatusRequest) -> bool:
    return True


@activity.defn(name="validate_artifacts_activity")
async def validate_artifacts(request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


_RECORD = make_record_activity(publish=publish_events, update_status=update_task_status)


@pytest.mark.asyncio
async def test_a_held_model_call_reaches_its_event_with_the_charge_and_the_hold():
    published.clear()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=[
                    build_config,
                    discover_tools,
                    resolve_model,
                    call_llm,
                    publish_events,
                    _RECORD,
                    update_task_status,
                    validate_artifacts,
                ],
                activity_executor=executor,
                workflow_runner=create_workflow_runner(),
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="test_user",
                        workspace_id="test-workspace",
                        task_query="Hi",
                        timeout_seconds=30,
                        effective_policy={
                            "budget": {"run_budget_usd": "100.00"},
                            "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
                            "execution": {
                                "max_model_turns": 5,
                                "max_tool_calls_per_turn": 10,
                                "max_tool_calls_total": 100,
                            },
                        },
                    ),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )
                result = await handle.result()

    assert result.success is True
    [completed] = [e for e in published if e.get("event_type") == "llm.call.completed"]
    data = completed["data"]
    assert data["cost"] in ("2.85", 2.85)
    assert data["usage"]["usage"]["billing"] == BILLING
