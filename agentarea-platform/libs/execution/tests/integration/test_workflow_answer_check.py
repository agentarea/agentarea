"""A final answer that leaks is rewritten once by the same model, when the agent or a rule asks."""

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

LEAKY = "Готово: смета обновлена через edit_estimate, по этим же rooms 最需要."
CLEAN = "Готово: смета обновлена по тем же комнатам."
REWRITE_REPLY = (
    f"<changes>убрал edit_estimate, перевёл rooms</changes>\n<answer>\n{CLEAN}\n</answer>"
)

llm_requests: list[LLMCallRequest] = []
events: list[dict[str, Any]] = []
statuses: list[UpdateTaskStatusRequest] = []
agent_answer_check: dict[str, Any] | None = None
explicit_completion = False


@activity.defn(name="build_agent_config_activity")
async def build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Сметчик",
        "model_id": "model-1",
        "description": "",
        "instruction": "Отвечай по-русски.",
        "context_window": 128000,
        "planning": False,
        "answer_check": agent_answer_check,
    }


@activity.defn(name="discover_available_tools_activity")
async def discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "context_window": 128000,
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="call_llm_activity")
async def call_llm(request: LLMCallRequest) -> dict[str, Any]:
    llm_requests.append(request)
    usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    if request.tools is None:  # the rewrite call
        return {"content": REWRITE_REPLY, "role": "assistant", "cost": "0.001", "usage": usage}
    if explicit_completion:
        call = {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "completion",
                "arguments": json.dumps({"result": LEAKY, "artifacts": []}, ensure_ascii=False),
            },
        }
        return {
            "content": "",
            "role": "assistant",
            "tool_calls": [call],
            "cost": "0.002",
            "usage": usage,
        }
    return {"content": LEAKY, "role": "assistant", "cost": "0.002", "usage": usage}


@activity.defn(name="publish_workflow_events_activity")
async def publish_events(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    events.extend(json.loads(e) for e in request.events_json if e.strip())
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def update_task_status(request: UpdateTaskStatusRequest) -> bool:
    statuses.append(request)
    return True


@activity.defn(name="validate_artifacts_activity")
async def validate_artifacts(request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


async def _run(
    content_safety: dict[str, Any] | None,
    agent_setting: dict[str, Any] | None = None,
    *,
    explicit: bool = False,
):
    global agent_answer_check, explicit_completion
    agent_answer_check = agent_setting
    explicit_completion = explicit
    llm_requests.clear()
    events.clear()
    statuses.clear()
    policy: dict[str, Any] = {
        "budget": {"run_budget_usd": "1.00"},
        "tokens": {"max_tokens": 20_000, "max_tokens_per_call": 4_000},
        "execution": {
            "max_model_turns": 5,
            "max_tool_calls_per_turn": 10,
            "max_tool_calls_total": 100,
        },
    }
    if content_safety is not None:
        policy["content_safety"] = content_safety
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
                        user_id="u",
                        workspace_id="ws",
                        task_query="Обнови смету",
                        timeout_seconds=30,
                        effective_policy=policy,
                    ),
                    id=f"test-{uuid.uuid4()}",
                    task_queue=task_queue,
                    execution_timeout=timedelta(hours=1),
                )
                return await handle.result()


def _replies() -> list[str]:
    return [e["data"]["content"] for e in events if e["event_type"] == "llm.call.completed"]


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_a_leaky_answer_is_rewritten_once_and_the_rewrite_is_what_the_task_returns():
    result = await _run({"answer_check": {"language": "ru"}})

    assert result.final_response == CLEAN
    turn, rewrite = llm_requests
    # The reply text is withheld from the live stream until it is checked.
    assert turn.stream_text is False
    assert rewrite.tools is None and rewrite.task_id is None and rewrite.conversation is None
    assert "edit_estimate" in rewrite.messages[-1]["content"]

    # Nothing the person can see carries the unchecked answer or the critique.
    assert _replies() == [CLEAN, CLEAN]
    (checked,) = [e for e in events if e["event_type"] == "AnswerChecked"]
    assert checked["data"]["rewritten"] is True
    assert checked["data"]["changes"] == "убрал edit_estimate, перевёл rooms"
    assert {leak["kind"] for leak in checked["data"]["leaks"]} >= {"cjk", "english"}
    (reply,) = [
        e
        for e in events
        if e["event_type"] == "llm.call.completed" and e["data"].get("purpose") == "answer_check"
    ]
    assert reply["data"]["content"] == CLEAN
    # Both model calls are paid for.
    completed = next(s for s in statuses if s.status == "completed")
    assert str(completed.total_cost) == "0.003"
    assert completed.tokens_used == 300
    assert json.loads(completed.result or "{}")["response"] == CLEAN


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_without_the_policy_or_the_setting_the_answer_is_returned_as_the_model_wrote_it():
    result = await _run(None)

    assert result.final_response == LEAKY
    assert len(llm_requests) == 1
    assert llm_requests[0].stream_text is True
    assert not [e for e in events if e["event_type"] == "AnswerChecked"]


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_the_agents_own_setting_turns_the_check_on():
    result = await _run(None, {"enabled": True, "language": "ru"})

    assert result.final_response == CLEAN
    assert len(llm_requests) == 2
    assert _replies() == [CLEAN, CLEAN]


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_a_rule_that_turns_the_check_off_overrides_the_agents_setting():
    result = await _run({"answer_check": {"enabled": False}}, {"enabled": True, "language": "ru"})

    assert result.final_response == LEAKY
    assert len(llm_requests) == 1


@pytest.mark.flow(MainFlow.AGENT_LIFECYCLE)
@pytest.mark.asyncio
async def test_an_answer_given_through_the_completion_tool_is_checked_at_completion():
    result = await _run({"answer_check": {"language": "ru"}}, explicit=True)

    assert result.final_response == CLEAN
    assert len(llm_requests) == 2
    (checked,) = [e for e in events if e["event_type"] == "AnswerChecked"]
    assert checked["data"]["rewritten"] is True
    completed = next(s for s in statuses if s.status == "completed")
    assert json.loads(completed.result or "{}")["response"] == CLEAN
