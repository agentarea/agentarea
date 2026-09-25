"""Tool approval, governance escalation and agent delegation, end to end.

A tool that policy puts behind approval pauses the run until a designated
approver resolves the escalation; a denial reaches the model as a tool result.
A governance gate that escalates a call from inside the tool activity goes
through the same human flow and, once approved, the call is re-issued. An
agent tool runs the target agent as a child workflow on the parent's queue.
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
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
    LLMCallRequest,
    MCPToolRequest,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

_APPROVER = "approver-1"
_GATED_TOOL = "deploy_service"
_HELPER_AGENT = "Helper"
_DELEGATE_TOOL = f"delegate_to_{_HELPER_AGENT}"
_CHILD_QUERY = "child: summarise the deployment"

_published: list[dict[str, Any]] = []
_status_updates: list[str] = []
_tool_requests: list[MCPToolRequest] = []
_llm_script: list[str] = []
_llm_calls = 0
_llm_lock = threading.Lock()
_governance_escalates = False


def _policy(approval: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "budget": {"run_budget_usd": "1.00"},
        "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
        "execution": {
            "max_model_turns": 5,
            "max_tool_calls_per_turn": 10,
            "max_tool_calls_total": 100,
        },
        **({"approval": approval} if approval else {}),
    }


@activity.defn(name="build_agent_config_activity")
async def _mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "description": "Test agent",
        "instruction": "Be helpful.",
        "tools_config": {"mcp_servers": []},
        "tools": [{"type": "agent", "name": _HELPER_AGENT}],
        "context_window": 128000,
        "events_config": {},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    def tool(name: str) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    return {"tools": [tool(_GATED_TOOL), tool(_DELEGATE_TOOL)], "context_strategy": "STATIC"}


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


@activity.defn(name="resolve_agent_tools_activity")
async def _mock_resolve_agent_tools(request: ResolveAgentToolsRequest) -> ResolveAgentToolsResult:
    return ResolveAgentToolsResult(agent_map={_HELPER_AGENT: str(uuid.uuid4())})


@activity.defn(name="create_delegation_task_activity")
async def _mock_create_delegation_task(
    request: CreateDelegationTaskRequest,
) -> CreateDelegationTaskResult:
    return CreateDelegationTaskResult(
        task_id=uuid.uuid4(),
        status="created",
        effective_policy=request.parent_effective_policy,
    )


def _reply(tool_name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@activity.defn(name="call_llm_activity")
async def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Follow ``_llm_script`` for the parent run; a delegated child just completes."""
    global _llm_calls
    if any(_CHILD_QUERY in str(m.get("content")) for m in request.messages):
        return _reply("completion", {"result": "child done", "artifacts": []}, "child_done")
    with _llm_lock:
        _llm_calls += 1
        call = _llm_calls
    step = _llm_script[call - 1] if call <= len(_llm_script) else "complete"
    if step == "gated":
        return _reply(_GATED_TOOL, {"target": "prod"}, f"call_gated_{call}")
    if step == "delegate":
        return _reply(_DELEGATE_TOOL, {"message": _CHILD_QUERY}, f"call_delegate_{call}")
    return _reply("completion", {"result": "done", "artifacts": []}, f"call_done_{call}")


@activity.defn(name="execute_mcp_tool_activity")
async def _mock_execute_mcp(request: MCPToolRequest) -> dict[str, Any]:
    _tool_requests.append(request)
    if _governance_escalates and not request.escalation_approved:
        raise ApplicationError(
            "EscalationRequiredError by SemanticGuard: production deploy",
            {
                "interceptor_name": "SemanticGuard",
                "reason": "production deploy",
                "metadata": None,
                "phase": "pre_tool_call",
            },
            type="EscalationRequiredError",
            non_retryable=True,
        )
    return {"success": True, "result": "deployed", "tool_name": request.tool_name}


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


_ALL_ACTIVITIES = [
    _mock_build_config,
    _mock_discover_tools,
    _mock_resolve_model,
    _mock_resolve_agent_tools,
    _mock_create_delegation_task,
    _mock_call_llm,
    _mock_execute_mcp,
    _mock_publish_events,
    _mock_update_status,
    _mock_validate_artifacts,
]


@pytest.fixture(autouse=True)
def _reset_globals():
    global _llm_calls, _governance_escalates
    _published.clear()
    _status_updates.clear()
    _tool_requests.clear()
    _llm_script.clear()
    _llm_calls = 0
    _governance_escalates = False
    return


def _request(policy: dict[str, Any]) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        workspace_id="test-workspace",
        task_query="deploy the service",
        timeout_seconds=30,
        effective_policy=policy,
    )


async def _pending_escalation(handle) -> dict[str, Any]:
    for _ in range(200):
        pending = await handle.query(AgentExecutionWorkflow.get_pending_escalations)
        if pending:
            return pending[0]
        await asyncio.sleep(0.05)
    raise AssertionError("workflow never asked for approval")


async def _run(request: AgentExecutionRequest, drive=None):
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
                )
                if drive is not None:
                    await drive(handle)
                result = await asyncio.wait_for(handle.result(), timeout=60)
                await Replayer(
                    workflows=[AgentExecutionWorkflow],
                    data_converter=pydantic_data_converter,
                    workflow_runner=create_workflow_runner(),
                ).replay_workflow(await handle.fetch_history())
                return result


def _events(event_type: str) -> list[dict[str, Any]]:
    return [e for e in _published if e.get("event_type") == event_type]


def _approval_policy() -> dict[str, Any]:
    return _policy({"escalation_rules": [_GATED_TOOL], "approvers": [f"user:{_APPROVER}"]})


@pytest.mark.asyncio
async def test_approved_tool_runs_after_the_designated_approver_signs_off():
    _llm_script.extend(["gated", "complete"])

    async def drive(handle):
        escalation = await _pending_escalation(handle)
        assert escalation["tool_name"] == _GATED_TOOL
        assert "waiting_for_approval" in _status_updates
        await handle.signal(
            AgentExecutionWorkflow.resolve_escalation,
            args=[escalation["escalation_id"], False, "not you", "someone-else"],
        )
        await handle.signal(
            AgentExecutionWorkflow.resolve_escalation,
            args=[escalation["escalation_id"], True, "ship it", _APPROVER],
        )

    result = await _run(_request(_approval_policy()), drive)

    assert result.success is True
    assert [r.tool_name for r in _tool_requests] == [_GATED_TOOL]
    responses = _events("approval.response")
    assert len(responses) == 1
    assert responses[0]["data"]["approved"] is True


@pytest.mark.asyncio
async def test_denied_tool_never_runs_and_the_model_hears_why():
    _llm_script.extend(["gated", "complete"])

    async def drive(handle):
        escalation = await _pending_escalation(handle)
        await handle.signal(
            AgentExecutionWorkflow.resolve_escalation,
            args=[escalation["escalation_id"], False, "not today", _APPROVER],
        )

    result = await _run(_request(_approval_policy()), drive)

    assert result.success is True
    assert _tool_requests == []
    denied = [e for e in _events("tool.result") if e["data"].get("denied_by_human")]
    assert len(denied) == 1
    assert "not today" in denied[0]["data"]["error"]


@pytest.mark.asyncio
async def test_governance_escalation_reissues_the_call_once_approved():
    global _governance_escalates
    _governance_escalates = True
    _llm_script.extend(["gated", "complete"])

    async def drive(handle):
        escalation = await _pending_escalation(handle)
        await handle.signal(
            AgentExecutionWorkflow.resolve_escalation,
            args=[escalation["escalation_id"], True, "", "anyone"],
        )

    result = await _run(_request(_policy()), drive)

    assert result.success is True
    assert [r.escalation_approved for r in _tool_requests] == [False, True]


@pytest.mark.asyncio
async def test_agent_tool_runs_the_target_agent_as_a_child_workflow():
    _llm_script.extend(["delegate", "complete"])

    result = await _run(_request(_policy()))

    assert result.success is True
    completed = _events("AgentDelegationCompleted")
    assert len(completed) == 1
    assert completed[0]["data"]["success"] is True
