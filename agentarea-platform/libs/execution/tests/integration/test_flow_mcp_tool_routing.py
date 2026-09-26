"""The workflow routes an MCP call to the server it was offered from, and nothing else.

Discovery hands the workflow a model-facing name per MCP tool plus the server and
raw name behind it. A call to an offered tool must reach the activity carrying
that route; a call to a name the model was never offered must stop in the
workflow, before any server is contacted.
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
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

GITHUB_ID = str(uuid.uuid4())
OFFERED = "mcp__github__search"

_llm_calls: list[LLMCallRequest] = []
_tool_requests: list[MCPToolRequest] = []
_script: dict[str, str] = {}


@activity.defn(name="build_agent_config_activity")
async def _build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Routing Agent",
        "model_id": "gpt-4o-mini",
        "instruction": "You are a helpful assistant.",
        "tools": [{"type": "mcp", "name": GITHUB_ID, "settings": {"allowed_tools": None}}],
        "context_window": 128000,
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _discover(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": OFFERED,
                    "description": "Search GitHub.",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ],
        "mcp_tool_routes": {
            OFFERED: {"instance_id": GITHUB_ID, "raw_name": "search", "attachment_ref": GITHUB_ID}
        },
    }


@activity.defn(name="resolve_model_activity")
async def _resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "display_name": "GPT-4o Mini",
        "provider_display_name": "OpenAI",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }


@activity.defn(name="call_llm_activity")
async def _call_llm(request: LLMCallRequest) -> dict[str, Any]:
    _llm_calls.append(request)
    if len(_llm_calls) == 1:
        return _tool_call("call_1", _script["tool"], {"q": "agentarea"})
    return _tool_call("call_2", "completion", {"result": "done", "artifacts": []})


@activity.defn(name="execute_mcp_tool_activity")
async def _execute_tool(request: MCPToolRequest) -> dict[str, Any]:
    _tool_requests.append(request)
    return {"success": True, "result": "found", "tool_name": request.tool_name}


@activity.defn(name="publish_workflow_events_activity")
async def _publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _update_task_status(request: UpdateTaskStatusRequest) -> bool:
    return True


@activity.defn(name="validate_artifacts_activity")
async def _validate_artifacts(request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


async def _run(tool_name: str) -> None:
    _llm_calls.clear()
    _tool_requests.clear()
    _script["tool"] = tool_name

    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-mcp-routing-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=[
                    _build_config,
                    _discover,
                    _resolve_model,
                    _call_llm,
                    _execute_tool,
                    _publish_events,
                    _update_task_status,
                    _validate_artifacts,
                ],
                activity_executor=executor,
                workflow_runner=create_workflow_runner(),
            )
            async with worker:
                request = AgentExecutionRequest(
                    task_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    user_id="test_user",
                    workspace_id="test-workspace",
                    task_query="Search GitHub for agentarea",
                    timeout_seconds=30,
                    effective_policy={
                        "budget": {"run_budget_usd": "1.00"},
                        "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 2_000},
                        "execution": {
                            "max_model_turns": 5,
                            "max_tool_calls_per_turn": 1,
                            "max_tool_calls_total": 1,
                        },
                    },
                )
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=f"test-mcp-routing-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )
                await handle.result()


@pytest.mark.asyncio
async def test_offered_mcp_tool_reaches_the_activity_with_its_route():
    await _run(OFFERED)

    assert len(_tool_requests) == 1
    sent = _tool_requests[0]
    assert sent.tool_name == OFFERED
    assert str(sent.server_instance_id) == GITHUB_ID
    assert sent.mcp_route is not None
    assert sent.mcp_route.raw_name == "search"
    # The activity runs as the task's principal; without it every tool call fails.
    assert sent.user_context_data == {"user_id": "test_user", "workspace_id": "test-workspace"}


@pytest.mark.asyncio
async def test_tool_the_model_was_not_offered_never_reaches_a_server():
    await _run("mcp__github__delete_repo")

    assert _tool_requests == []
    tool_replies = [m for m in _llm_calls[1].messages if m.get("role") == "tool"]
    assert any("not available to this agent" in (m.get("content") or "") for m in tool_replies)
