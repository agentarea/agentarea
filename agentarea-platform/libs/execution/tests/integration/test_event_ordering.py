"""Tests for correct event ordering in agent execution workflow."""

import concurrent.futures
import uuid
from datetime import timedelta

import pytest
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentarea_execution.testing import (
    EventCapture,
    llm_response_completion,
    llm_response_text,
    llm_response_tool_call,
    make_sequenced_llm_activity,
    mock_build_agent_config,
    mock_discover_tools,
    mock_execute_mcp_tool,
    mock_resolve_model,
    mock_update_task_status,
)


async def _run_workflow(
    responses,
    max_iterations: int = 5,
    budget_usd: float = 1.0,
) -> tuple[object, EventCapture]:
    """Helper: run workflow with sequenced LLM responses and capture events."""
    event_capture = EventCapture()
    llm_activity = make_sequenced_llm_activity(responses)
    publish_activity = event_capture.make_activity()

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
                activities=[
                    mock_build_agent_config,
                    mock_discover_tools,
                    mock_resolve_model,
                    llm_activity,
                    mock_execute_mcp_tool,
                    publish_activity,
                    mock_update_task_status,
                ],
                activity_executor=executor,
            )

            async with worker:
                request = AgentExecutionRequest(
                    task_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    user_id="test_user",
                    workspace_id="test-workspace",
                    task_query="Test event ordering",
                    timeout_seconds=30,
                    max_reasoning_iterations=max_iterations,
                    budget_usd=budget_usd,
                )

                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )

                result = await handle.result()

    return result, event_capture


class TestEventOrdering:
    @pytest.mark.asyncio
    async def test_iteration_completed_before_workflow_completed(self):
        """When LLM calls completion, IterationCompleted must precede task.completed.

        The emit-side canonicalizes ``WorkflowCompleted`` to ``task.completed``;
        ``IterationCompleted`` is a timeline event and passes through unchanged.
        """
        result, capture = await _run_workflow([llm_response_completion()])

        assert result.success is True

        types = capture.event_types
        assert "IterationCompleted" in types, f"Missing IterationCompleted in {types}"
        assert "task.completed" in types, f"Missing task.completed in {types}"

        iter_idx = types.index("IterationCompleted")
        wf_idx = types.index("task.completed")
        assert iter_idx < wf_idx, (
            f"IterationCompleted (idx={iter_idx}) must come before "
            f"task.completed (idx={wf_idx}). Sequence: {types}"
        )

    @pytest.mark.asyncio
    async def test_normal_iteration_emits_iteration_completed(self):
        """Plain text response (no completion tool) still emits IterationCompleted."""
        result, capture = await _run_workflow(
            [llm_response_text()], max_iterations=1
        )

        types = capture.event_types
        assert "IterationCompleted" in types, f"Missing IterationCompleted in {types}"

    @pytest.mark.asyncio
    async def test_multi_iteration_event_ordering(self):
        """Tool call then completion: two IterationCompleted, task.completed last."""
        result, capture = await _run_workflow([
            llm_response_tool_call("search"),
            llm_response_completion(),
        ])

        assert result.success is True

        types = capture.event_types
        iter_completed = [i for i, t in enumerate(types) if t == "IterationCompleted"]
        wf_completed = [i for i, t in enumerate(types) if t == "task.completed"]

        assert len(iter_completed) == 2, (
            f"Expected 2 IterationCompleted events, got {len(iter_completed)}. Sequence: {types}"
        )
        assert len(wf_completed) >= 1, f"Missing task.completed in {types}"

        # task.completed must come after the last IterationCompleted
        assert wf_completed[0] > iter_completed[-1], (
            f"task.completed (idx={wf_completed[0]}) must come after last "
            f"IterationCompleted (idx={iter_completed[-1]}). Sequence: {types}"
        )
