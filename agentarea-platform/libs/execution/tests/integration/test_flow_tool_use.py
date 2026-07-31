"""Flow test: AGENT_TOOL_USE — LLM calls a tool, result feeds back, agent completes."""

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
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Capture LLM invocations so assertions can inspect them
_llm_calls: list[dict] = []
# Capture MCP tool invocations
_mcp_calls: list[dict] = []

_FAKE_TOOL_NAME = "get_weather"
_FAKE_TOOL_RESULT = "Sunny, 22°C"


@activity.defn(name="build_agent_config_activity")
async def _mock_build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Tool-Use Test Agent",
        "model_id": "gpt-4o-mini",
        "description": "Agent that calls a tool",
        "instruction": "You are a helpful assistant.",
        "tools_config": {"mcp_servers": []},
        "context_window": 128000,
        "events_config": {},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def _mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    # Expose the fake tool so it appears in available_tools and the LLM can call it
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": _FAKE_TOOL_NAME,
                    "description": "Get the current weather for a city.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "City name"},
                        },
                        "required": ["city"],
                    },
                },
            }
        ],
        "context_strategy": "STATIC",
    }


@activity.defn(name="resolve_model_activity")
async def _mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
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
async def _mock_call_llm(request: LLMCallRequest) -> dict[str, Any]:
    """On the first call return a tool call; on the second call complete the task."""
    call_index = len(_llm_calls)
    _llm_calls.append(
        {
            "messages": request.messages,
            "tools": request.tools,
            "model_id": request.model_id,
        }
    )

    if call_index == 0:
        # First call: instruct the workflow to run the fake tool
        return {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_tool_001",
                    "type": "function",
                    "function": {
                        "name": _FAKE_TOOL_NAME,
                        "arguments": json.dumps({"city": "Berlin"}),
                    },
                }
            ],
            "finish_reason": "tool_calls",
            "cost": 0.001,
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 20,
                "total_tokens": 100,
            },
        }
    else:
        # Second call: complete the task, incorporating the tool result
        tool_result_in_messages = any(
            msg.get("role") == "tool" for msg in request.messages
        )
        final_text = (
            f"The weather in Berlin is: {_FAKE_TOOL_RESULT}"
            if tool_result_in_messages
            else "Done"
        )
        return {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_complete_001",
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "arguments": json.dumps({"result": final_text}),
                    },
                }
            ],
            "finish_reason": "tool_calls",
            "cost": 0.001,
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
        }


@activity.defn(name="execute_mcp_tool_activity")
async def _mock_execute_mcp_tool(request: MCPToolRequest) -> dict[str, Any]:
    _mcp_calls.append({"tool_name": request.tool_name, "tool_args": request.tool_args})
    return {"success": True, "result": _FAKE_TOOL_RESULT, "tool_name": request.tool_name}


@activity.defn(name="publish_workflow_events_activity")
async def _mock_publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _mock_update_task_status(request: UpdateTaskStatusRequest) -> bool:
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
    _mock_call_llm,
    _mock_execute_mcp_tool,
    _mock_publish_events,
    _mock_update_task_status,
    _mock_validate_artifacts,
]


@pytest.mark.flow(MainFlow.AGENT_TOOL_USE)
class TestAgentToolUseFlow:
    @pytest.mark.asyncio
    async def test_tool_call_round_trip(self):
        """LLM calls a tool, result feeds back, LLM completes — workflow succeeds."""
        _llm_calls.clear()
        _mcp_calls.clear()

        env = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter,
        )
        async with env:
            task_queue = f"test-tool-use-{uuid.uuid4()}"

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AgentExecutionWorkflow],
                    activities=_ALL_ACTIVITIES,
                    activity_executor=executor,
                    workflow_runner=create_workflow_runner(),
                )

                async with worker:
                    request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="test_user",
                        workspace_id="test-workspace",
                        task_query="What is the weather in Berlin?",
                        timeout_seconds=30,
                        # Tool authorization is zero-trust/default-deny: the task
                        # policy must explicitly grant tools for this round-trip.
                        effective_policy={
                            "budget": {"run_budget_usd": "1.00"},
                            "tokens": {
                                "max_tokens": 20_000,
                                "max_tokens_per_call": 2_000,
                            },
                            "execution": {
                                "max_model_turns": 5,
                                "max_tool_calls_per_turn": 1,
                                "max_tool_calls_total": 1,
                            },
                            "tools": {"allowed": ["*"]},
                        },
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        request,
                        id=f"test-tool-use-{uuid.uuid4()}",
                        task_queue=task_queue,
                        execution_timeout=timedelta(hours=1),
                    )

                    result = await handle.result()

                    # (1) Workflow succeeded
                    assert result.success is True, f"Expected success=True, got: {result}"

                    # (2) The tool-exec activity was actually invoked
                    assert len(_mcp_calls) == 1, (
                        f"Expected exactly 1 MCP tool call, got {len(_mcp_calls)}: {_mcp_calls}"
                    )
                    assert _mcp_calls[0]["tool_name"] == _FAKE_TOOL_NAME
                    assert _mcp_calls[0]["tool_args"] == {"city": "Berlin"}

                    # (3) A second LLM call happened with the tool result in messages
                    assert len(_llm_calls) >= 2, (
                        f"Expected at least 2 LLM calls (tool + completion), got {len(_llm_calls)}"
                    )
                    second_call_messages = _llm_calls[1]["messages"]
                    tool_messages = [
                        m for m in second_call_messages if m.get("role") == "tool"
                    ]
                    assert tool_messages, (
                        "Second LLM call must include a tool-role message with the tool result"
                    )
                    tool_content = tool_messages[0].get("content", "")
                    assert _FAKE_TOOL_RESULT in tool_content, (
                        f"Tool result '{_FAKE_TOOL_RESULT}' not found in tool message: {tool_content!r}"
                    )

                    # Final response should reference the tool result
                    assert result.final_response is not None
                    assert _FAKE_TOOL_RESULT in result.final_response, (
                        f"Final response should contain tool result. Got: {result.final_response!r}"
                    )
                    assert result.total_tool_calls == 1
