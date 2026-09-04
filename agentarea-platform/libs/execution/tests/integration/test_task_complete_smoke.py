"""Smoke test: verify completion tool is injected and LLM can use it to finish."""

import concurrent.futures
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_common.testing.flows import MainFlow
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
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Capture what the LLM actually receives
captured_llm_requests: list[dict] = []


@activity.defn(name="build_agent_config_activity")
async def mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "description": "Test agent",
        "instruction": "You are a helpful assistant.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "events_config": {},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
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


@activity.defn(name="call_llm_activity")
async def mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """Mock LLM that captures the request and calls completion."""
    captured_llm_requests.append({
        "messages": request.messages,
        "tools": request.tools,
        "model_id": request.model_id,
    })

    # Check that completion is in the tools
    tool_names = []
    for tool in (request.tools or []):
        if tool.get("type") == "function" and "function" in tool:
            tool_names.append(tool["function"]["name"])
        elif "name" in tool:
            tool_names.append(tool["name"])

    print(f"[MOCK LLM] Received {len(request.messages)} messages, {len(request.tools or [])} tools")
    print(f"[MOCK LLM] Tool names: {tool_names}")
    print(f"[MOCK LLM] completion present: {'completion' in tool_names}")

    # Simulate LLM calling completion with a real response
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_test_123",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({
                        "result": "Привет! Я готов помочь. Чем могу быть полезен?",
                        "artifacts": [],
                    }),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }


@activity.defn(name="execute_mcp_tool_activity")
async def mock_execute_mcp_tool(request: MCPToolRequest) -> dict[str, Any]:
    return {"success": True, "result": "Mock result", "tool_name": request.tool_name}


@activity.defn(name="publish_workflow_events_activity")
async def mock_publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    for ej in request.events_json:
        if not ej or not ej.strip():
            continue
        try:
            data = json.loads(ej)
            print(f"[EVENT] {data.get('event_type', '?')}")
        except json.JSONDecodeError:
            pass
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def mock_update_task_status(request: UpdateTaskStatusRequest) -> bool:
    print(f"[STATUS] task={request.task_id} status={request.status}")
    return True


@activity.defn(name="validate_artifacts_activity")
async def mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


ALL_ACTIVITIES = [
    mock_build_config,
    mock_discover_tools,
    mock_resolve_model,
    mock_call_llm,
    mock_execute_mcp_tool,
    mock_publish_events,
    mock_update_task_status,
    mock_validate_artifacts,
]


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
class TestTaskCompleteSmokeTest:
    @pytest.mark.asyncio
    async def test_simple_hello_completes(self):
        """A simple 'привет' should result in one LLM call that calls completion."""
        captured_llm_requests.clear()

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
                    activities=ALL_ACTIVITIES,
                    activity_executor=executor,
                    workflow_runner=create_workflow_runner(),
                )

                async with worker:
                    request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="test_user",
                        workspace_id="test-workspace",
                        task_query="Привет",
                        timeout_seconds=30,
                        effective_policy={
                            "budget": {"run_budget_usd": "1.00"},
                            "tokens": {
                                "max_tokens": 20_000,
                                "max_tokens_per_call": 2_000,
                            },
                            "execution": {
                                "max_model_turns": 5,
                                "max_tool_calls_per_turn": 10,
                                "max_tool_calls_total": 100,
                            },
                        },
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        request,
                        id=f"test-{uuid.uuid4()}",
                        task_queue=task_queue,
                        execution_timeout=timedelta(hours=1),
                    )

                    result = await handle.result()

                    # Core assertions
                    assert result.success is True, f"Workflow should succeed, got: {result}"
                    assert result.final_response is not None, "Should have a final response"
                    assert "Привет" in result.final_response, (
                        f"Response should contain greeting, got: {result.final_response}"
                    )

                    # Verify completion was in tools
                    assert len(captured_llm_requests) >= 1, "LLM should have been called at least once"
                    first_request = captured_llm_requests[0]
                    tool_names = []
                    for tool in first_request["tools"]:
                        if tool.get("type") == "function" and "function" in tool:
                            tool_names.append(tool["function"]["name"])
                        elif "name" in tool:
                            tool_names.append(tool["name"])

                    assert "completion" in tool_names, (
                        f"completion MUST be in tools sent to LLM. Got: {tool_names}"
                    )

                    print("\n Workflow completed successfully")
                    print(f"   Response: {result.final_response}")
                    print(f"   Iterations: {result.reasoning_iterations_used}")
                    print(f"   Tools available to LLM: {tool_names}")
