import concurrent.futures
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_execution.models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    MCPToolRequest,
    ToolDiscoveryRequest,
)
from agentarea_execution.testing import (
    EventCapture,
    llm_response_text,
    llm_response_tool_call,
    make_sequenced_llm_activity,
    mock_build_agent_config,
    mock_discover_tools,
    mock_execute_mcp_tool,
    mock_resolve_model,
    mock_update_task_status,
    mock_validate_artifacts,
    runtime_policy,
)
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

tool_calls: list[MCPToolRequest] = []


@activity.defn(name="discover_available_tools_activity")
async def discover_calculator(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Calculate mathematical expressions",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Math expression to calculate",
                            }
                        },
                        "required": ["expression"],
                    },
                },
            }
        ],
        "context_strategy": "STATIC",
    }


@activity.defn(name="execute_mcp_tool_activity")
async def calculator(request: MCPToolRequest) -> dict[str, Any]:
    tool_calls.append(request)
    return {"success": True, "result": "4", "tool_name": request.tool_name}


async def _run(
    responses: list[dict[str, Any]],
    *,
    discover=mock_discover_tools,
    execute_tool=mock_execute_mcp_tool,
    policy: dict[str, Any] | None = None,
    while_running=None,
) -> tuple[AgentExecutionRequest, AgentExecutionResult, EventCapture]:
    capture = EventCapture()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = str(uuid.uuid4())
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_build_agent_config,
                    discover,
                    mock_resolve_model,
                    make_sequenced_llm_activity(responses),
                    execute_tool,
                    capture.make_activity(),
                    mock_update_task_status,
                    mock_validate_artifacts,
                ],
                activity_executor=executor,
            ):
                request = AgentExecutionRequest(
                    task_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    user_id="integration_test_user",
                    workspace_id="test-workspace",
                    task_query="What is 2 + 2?",
                    timeout_seconds=30,
                    effective_policy=policy or runtime_policy(),
                )
                handle: WorkflowHandle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )
                if while_running is not None:
                    await while_running(handle)
                result = await handle.result()
    return request, result, capture


class TestAgentExecutionWorkflowIntegration:
    @pytest.mark.asyncio
    async def test_workflow_with_tool_calls(self):
        """A tool call runs the tool, and the model's next turn answers with its result."""
        tool_calls.clear()

        async def inspect(handle: WorkflowHandle) -> None:
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
            assert "status" in await handle.query("get_current_state")

        request, result, _ = await _run(
            [
                llm_response_tool_call("calculator", {"expression": "2 + 2"}),
                llm_response_text("Based on my calculation, 2 + 2 equals 4."),
            ],
            discover=discover_calculator,
            execute_tool=calculator,
            policy={**runtime_policy(), "tools": {"allowed": ["*"]}},
            while_running=inspect,
        )

        assert result.success is True
        assert result.agent_id == request.agent_id
        assert result.task_id == request.task_id
        assert result.final_response is not None
        assert "4" in result.final_response
        assert result.total_tool_calls == 1
        assert [(c.tool_name, c.tool_args) for c in tool_calls] == [
            ("calculator", {"expression": "2 + 2"})
        ]

    @pytest.mark.asyncio
    async def test_workflow_without_tool_calls(self):
        """A text-only reply completes the task in one turn."""
        request, result, _ = await _run(
            [llm_response_text("Hello! I'm here to help you with your questions.")]
        )

        assert result.success is True
        assert result.agent_id == request.agent_id
        assert result.task_id == request.task_id
        assert result.final_response == "Hello! I'm here to help you with your questions."
        assert result.total_tool_calls == 0
        assert result.reasoning_iterations_used == 1

    @pytest.mark.asyncio
    async def test_workflow_event_publishing(self):
        """Every published event carries the run's ids, from task.started to execution.finished."""
        request, result, capture = await _run([llm_response_text("I can help you with your task.")])

        assert result.success is True
        assert capture.events
        for event in capture.events:
            assert {"event_id", "event_type", "timestamp", "data"} <= event.keys()
            assert event["data"]["task_id"] == str(request.task_id)
            assert event["data"]["agent_id"] == str(request.agent_id)

        types = capture.event_types
        assert types[0] == "task.started"
        assert "task.completed" in types
        assert types[-1] == "execution.finished"
