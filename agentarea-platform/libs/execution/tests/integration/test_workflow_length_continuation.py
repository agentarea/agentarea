"""A reply cut off at the output limit is continued, and the answer is the whole of it."""

import concurrent.futures
import uuid
from datetime import timedelta

import pytest
from agentarea_execution.models import AgentExecutionRequest, LLMCallRequest
from agentarea_execution.testing import (
    EventCapture,
    llm_response_text,
    make_sequenced_llm_activity,
    mock_build_agent_config,
    mock_discover_tools,
    mock_execute_mcp_tool,
    mock_resolve_model,
    mock_update_task_status,
    mock_validate_artifacts,
    runtime_policy,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


def _cut_off(content: str) -> dict:
    return {**llm_response_text(content), "finish_reason": "length"}


async def _run(
    responses: list[dict], max_iterations: int = 5, llm_activity=None, task_parameters=None
):
    capture = EventCapture()
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        task_queue = f"test-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_build_agent_config,
                    mock_discover_tools,
                    mock_resolve_model,
                    llm_activity or make_sequenced_llm_activity(responses),
                    mock_execute_mcp_tool,
                    capture.make_activity(),
                    capture.make_record_activity(),
                    mock_update_task_status,
                    mock_validate_artifacts,
                ],
                activity_executor=executor,
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="test_user",
                        workspace_id="test-workspace",
                        task_query="Write the report",
                        task_parameters=task_parameters or {},
                        timeout_seconds=30,
                        effective_policy=runtime_policy(max_model_turns=max_iterations),
                    ),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )
                return await handle.result(), capture


@pytest.mark.asyncio
async def test_a_cut_off_reply_is_continued_and_joined():
    result, capture = await _run([_cut_off("First half, "), llm_response_text("second half.")])

    assert result.success is True
    assert result.final_response == "First half, second half."
    assert capture.event_types.count("llm.call.completed") == 2


@pytest.mark.asyncio
async def test_a_reply_that_finished_is_the_answer_at_once():
    result, capture = await _run([llm_response_text("All of it.")])

    assert result.final_response == "All of it."
    assert capture.event_types.count("llm.call.completed") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "sent"),
    [
        ({"reasoning_effort": "low"}, ("low", None)),
        ({"reasoning_max_tokens": 2048}, (None, 2048)),
    ],
)
async def test_a_runs_reasoning_reaches_the_model_call(parameters, sent):
    seen: list = []

    @activity.defn(name="call_llm_activity")
    async def call_llm(request: LLMCallRequest):
        seen.append((request.reasoning_effort, request.reasoning_max_tokens))
        return llm_response_text("Done.")

    await _run([], llm_activity=call_llm, task_parameters=parameters)

    assert seen == [sent]
