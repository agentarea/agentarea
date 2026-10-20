"""Activating a skill: its SKILL.md reaches the model through the task log, never history.

The activation activity writes the skill's entry into the task log at the
position the run reserved and returns only its size, so workflow history stays
the same size whatever the SKILL.md weighs. When the skill's storage is down the
activity retries; past its retry window the run waits for the service, says so,
and goes on by itself when it answers, failing only after the outage deadline.

Uses ``WorkflowEnvironment.start_time_skipping()``: awaiting the result, or
``env.sleep``, fast-forwards the retry backoff and the waits.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.models import (
    ActivateSkillRequest,
    ActivateSkillResult,
    AgentConfigRequest,
    AgentExecutionRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    LogRow,
    MaterializeSkillFilesRequest,
    MaterializeSkillFilesResult,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from agentarea_execution.testing import TaskLogFake, make_record_activity
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

SKILL_ID = str(uuid.uuid4())


class Scenario:
    def __init__(self) -> None:
        self.body = "# PDF skill\nUse pdfplumber.\n"
        self.outage: timedelta | None = None
        self.outage_started: datetime | None = None
        self.refusal: str | None = None
        # What the service answers once the outage is over, instead of the body.
        self.after_outage: str | None = None
        # Holds the model's second call until the test releases it.
        self.hold_second_call: asyncio.Event | None = None
        self.skills = ["pdf"]
        self.skills_window_share: float | None = None
        self.withheld: list[dict[str, str]] = []
        # Configs built before activation read the package carried the body.
        self.carry_body = False
        self.attempts = 0
        self.model_saw: list[list[dict[str, Any]]] = []
        self.published: list[dict[str, Any]] = []
        self.statuses: list[UpdateTaskStatusRequest] = []
        self.log = TaskLogFake()


S = Scenario()


@activity.defn(name="build_agent_config_activity")
async def _build_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Skill agent",
        "model_id": "gpt-4o-mini",
        "description": "",
        "instruction": "You help with PDFs.",
        "context_window": 1_000_000,
        "planning": False,
        "skills": [
            {
                "id": SKILL_ID if name == "pdf" else str(uuid.uuid5(uuid.NAMESPACE_DNS, name)),
                "name": name,
                "description": name.upper(),
                **({"content": S.body} if S.carry_body else {}),
            }
            for name in S.skills
        ],
        **({"skills_window_share": S.skills_window_share} if S.skills_window_share else {}),
        "withheld_skills": S.withheld,
    }


@activity.defn(name="discover_available_tools_activity")
async def _discover(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def _resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "context_window": 1_000_000,
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


def _call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
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
        "cost": 0.0001,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@activity.defn(name="call_llm_activity")
async def _call_llm(request: LLMCallRequest) -> dict[str, Any]:
    S.model_saw.append(S.log.messages(request))
    if len(S.model_saw) == 2 and S.hold_second_call is not None:
        await S.hold_second_call.wait()
    if len(S.model_saw) <= len(S.skills):
        name = S.skills[len(S.model_saw) - 1]
        return _call("activate_skill", {"skill_name": name}, f"call_skill_{name}")
    return _call("completion", {"result": "done", "artifacts": []}, f"call_done_{len(S.model_saw)}")


@activity.defn(name="activate_skill_activity")
async def _activate_skill(request: ActivateSkillRequest) -> ActivateSkillResult:
    S.attempts += 1
    if S.refusal is not None:
        raise ApplicationError(S.refusal, type="SkillActivationRefused", non_retryable=True)
    now = activity.info().current_attempt_scheduled_time
    if S.outage is not None:
        if S.outage_started is None:
            S.outage_started = now
        if now - S.outage_started < S.outage:
            raise ApplicationError(
                "Object storage is unreachable: Could not connect to the endpoint URL: "
                "http://s3:9000",
                {"service": "Object storage"},
                type="ServiceUnreachable",
            )
        if S.after_outage is not None:
            raise ApplicationError(S.after_outage, type="SkillNotFound", non_retryable=True)
    content = f'<skill_content name="{request.skill_name}">\n{S.body}</skill_content>'
    S.log.rows.setdefault(request.task_id, {})[request.seq] = LogRow(
        seq=request.seq,
        event_id=request.event_id,
        role="tool",
        content=content,
        tool_call_id=request.tool_call_id,
        name="activate_skill",
    )
    return ActivateSkillResult(chars=len(content), est_tokens=len(content) // 4)


@activity.defn(name="materialize_skill_files_activity")
async def _materialize(request: MaterializeSkillFilesRequest) -> MaterializeSkillFilesResult:
    return MaterializeSkillFilesResult(success=False, error="no sandbox in this test")


@activity.defn(name="publish_workflow_events_activity")
async def _publish(request: WorkflowEventsRequest) -> WorkflowEventsResult:
    S.published.extend(json.loads(event) for event in request.events_json)
    return WorkflowEventsResult(success=True, events_published=len(request.events_json))


@activity.defn(name="update_task_status_activity")
async def _update_status(request: UpdateTaskStatusRequest) -> bool:
    S.statuses.append(request)
    return True


@activity.defn(name="validate_artifacts_activity")
async def _validate(request: ArtifactValidationRequest) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="passed", generation=0)


def _activities() -> list[Any]:
    return [
        _build_config,
        _discover,
        _resolve_model,
        _call_llm,
        _activate_skill,
        _materialize,
        _publish,
        make_record_activity(publish=_publish, update_status=_update_status, log=S.log),
        _update_status,
        _validate,
    ]


@pytest.fixture(autouse=True)
def _fresh_scenario():
    global S
    S = Scenario()
    return


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test_user",
        workspace_id="test-workspace",
        task_query="Read the PDF",
        effective_policy={
            "budget": {"run_budget_usd": "1.00"},
            "tokens": {"max_tokens": 10_000_000, "max_tokens_per_call": 2_000_000},
            "execution": {
                "max_model_turns": 5,
                "max_tool_calls_per_turn": 1,
                "max_tool_calls_total": 3,
            },
            "tools": {"allowed": ["*"]},
        },
    )


def _skill_messages(index: int) -> list[str]:
    return [m["content"] for m in S.model_saw[index] if m.get("role") == "tool"]


def _event_types() -> list[str]:
    return [event["event_type"] for event in S.published]


def _status_values() -> list[str]:
    return [request.status for request in S.statuses]


async def _run(body_size: int | None = None, *, during=None, execution_timeout=timedelta(days=3)):
    if body_size is not None:
        S.body = "# PDF skill\n" + ("Use pdfplumber. " * (body_size // 16 + 1))[:body_size]
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    async with env:
        queue = f"test-skill-activation-{uuid.uuid4()}"
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[AgentExecutionWorkflow],
                activities=_activities(),
                activity_executor=executor,
                workflow_runner=create_workflow_runner(),
            ):
                handle = await env.client.start_workflow(
                    AgentExecutionWorkflow.run,
                    _request(),
                    id=f"test-skill-activation-{uuid.uuid4()}",
                    task_queue=queue,
                    execution_timeout=execution_timeout,
                )
                if during is not None:
                    await during(env, handle)
                try:
                    result: Any = await handle.result()
                except WorkflowFailureError as failure:
                    result = failure
                history = await handle.fetch_history()
    return result, history


async def test_the_skill_reaches_the_model_from_the_log():
    # Also the scenario recorded for replay on the code before the change.
    S.carry_body = True

    result, _ = await _run()

    assert result.success is True
    [entry] = _skill_messages(1)
    assert entry.startswith('<skill_content name="pdf">\n# PDF skill')
    assert S.attempts == 1


@pytest.mark.parametrize("body_size", [10 * 1024, 256 * 1024, 2 * 1024 * 1024])
async def test_history_does_not_grow_with_the_skill_body(body_size):
    result, history = await _run(body_size)

    assert result.success is True
    assert len(_skill_messages(1)[0]) > body_size
    assert max(event.ByteSize() for event in history.events) < 64 * 1024
    assert sum(event.ByteSize() for event in history.events) < 256 * 1024


async def test_a_short_outage_is_ridden_out_without_the_run_noticing():
    S.outage = timedelta(seconds=30)

    result, _ = await _run()

    assert result.success is True
    assert S.attempts > 1
    assert "task.awaiting_infrastructure" not in _event_types()
    assert "waiting_for_infrastructure" not in _status_values()
    assert _skill_messages(1)[0].startswith('<skill_content name="pdf">')


async def test_a_long_outage_waits_for_the_service_and_goes_on_by_itself():
    S.outage = timedelta(minutes=10)

    result, _ = await _run()

    assert result.success is True
    types = _event_types()
    assert types.index("task.awaiting_infrastructure") < types.index(
        "task.infrastructure_recovered"
    )
    waiting = next(e for e in S.published if e["event_type"] == "task.awaiting_infrastructure")
    assert waiting["data"]["service"] == "Object storage"
    assert "while activating skill 'pdf'" in waiting["data"]["message"]
    statuses = _status_values()
    assert statuses.index("waiting_for_infrastructure") < statuses.index("running", 1)
    assert _skill_messages(1)[0].startswith('<skill_content name="pdf">')


async def test_an_outage_past_the_deadline_fails_the_run_with_the_service_named():
    S.outage = timedelta(hours=25)

    result, _ = await _run()

    assert isinstance(result, WorkflowFailureError)
    failed = [request for request in S.statuses if request.status == "failed"]
    assert failed, _status_values()
    message = failed[-1].error_message or ""
    assert "Object storage stayed unreachable for 24 h while activating skill 'pdf'" in message
    assert "AI model" not in message
    assert failed[-1].failure_reason == "dependency_unavailable"


async def test_a_run_waiting_for_the_service_can_be_cancelled():
    S.outage = timedelta(hours=25)

    async def cancel_while_waiting(env, handle):
        await env.sleep(timedelta(minutes=7))
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["status"] == "waiting_for_infrastructure"
        assert state["waiting_for_infrastructure"] is True
        await handle.cancel()

    result, _ = await _run(during=cancel_while_waiting)

    assert isinstance(result, WorkflowFailureError)
    assert _status_values()[-1] == "cancelled"


async def test_a_resume_while_waiting_retries_at_once():
    S.outage = timedelta(minutes=6)

    async def resume_while_waiting(env, handle):
        await env.sleep(timedelta(minutes=5, seconds=30))
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["waiting_for_infrastructure"] is True
        await env.sleep(timedelta(seconds=40))
        attempts = S.attempts
        await handle.signal(AgentExecutionWorkflow.resume_execution, "storage is back")
        for _ in range(100):
            if S.attempts > attempts:
                break
            await env.sleep(timedelta(milliseconds=50))
        assert S.attempts > attempts

    result, _ = await _run(during=resume_while_waiting)

    assert result.success is True
    assert "task.infrastructure_recovered" in _event_types()


async def test_a_skill_the_install_policy_refuses_is_a_tool_error_the_model_reads():
    S.refusal = (
        "Skill 'pdf' cannot be activated: Install refused by policy: "
        "denied by registry_trust:community for workspace test-workspace"
    )

    result, _ = await _run()

    assert result.success is True
    assert _skill_messages(1) == [
        "Tool failed: " + S.refusal,
    ]
    assert S.attempts == 1
    assert "task.awaiting_infrastructure" not in _event_types()


async def test_a_final_answer_after_an_outage_ends_the_wait_and_pause_still_works():
    # Storage comes back, but the skill was deleted meanwhile.
    S.outage = timedelta(minutes=8)
    S.after_outage = "Skill 'pdf' no longer exists"
    S.hold_second_call = asyncio.Event()

    async def after_the_wait(env, handle):
        for _ in range(400):
            if len(S.model_saw) >= 2:
                break
            await env.sleep(timedelta(seconds=5))
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["waiting_for_infrastructure"] is False
        assert state["status"] == "executing"
        await handle.signal(AgentExecutionWorkflow.pause_execution, "hold on")
        await handle.signal(AgentExecutionWorkflow.resume_execution, "go on")
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["paused"] is False
        S.hold_second_call.set()

    result, _ = await _run(during=after_the_wait)

    assert result.success is True
    statuses = _status_values()
    assert statuses.index("waiting_for_infrastructure") < statuses.index("running", 1)
    ended = next(e for e in S.published if e["event_type"] == "task.infrastructure_recovered")
    assert ended["data"]["error"] == "Skill 'pdf' no longer exists"
    assert _skill_messages(1) == ["Tool failed: Skill 'pdf' no longer exists"]


async def test_a_paused_run_does_not_retry_and_a_resume_lifts_the_pause_and_retries():
    S.outage = timedelta(minutes=8)

    async def pause_then_resume(env, handle):
        await env.sleep(timedelta(minutes=6))
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["waiting_for_infrastructure"] is True
        await handle.signal(AgentExecutionWorkflow.pause_execution, "hold on")
        attempts = S.attempts
        await env.sleep(timedelta(minutes=30))
        assert S.attempts == attempts
        await handle.signal(AgentExecutionWorkflow.resume_execution, "go on")
        for _ in range(100):
            if S.attempts > attempts:
                break
            await asyncio.sleep(0.05)
        state = await handle.query(AgentExecutionWorkflow.get_current_state)
        assert state["paused"] is False

    result, _ = await _run(during=pause_then_resume)

    assert result.success is True
    types = _event_types()
    assert "execution.paused" in types
    assert "execution.resumed" in types
    assert _skill_messages(1)[0].startswith('<skill_content name="pdf">')


async def test_a_run_with_less_time_left_than_the_deadline_fails_itself_in_time():
    # A delegated agent runs under a 6 h execution timeout, under the 24 h deadline.
    S.outage = timedelta(hours=25)

    result, _ = await _run(execution_timeout=timedelta(hours=3))

    assert isinstance(result, WorkflowFailureError)
    assert getattr(result.cause, "type", None) == "DependencyUnavailable"
    failed = [request for request in S.statuses if request.status == "failed"]
    assert failed and failed[-1].failure_reason == "dependency_unavailable"
    message = failed[-1].error_message or ""
    assert "Object storage stayed unreachable for" in message
    assert "while activating skill 'pdf'" in message


async def test_a_skill_past_the_skills_share_of_the_window_is_not_loaded():
    S.skills = ["pdf", "docx"]
    S.skills_window_share = 0.001  # 1,000 tokens of the 1,000,000 window
    S.body = "x" * 3200  # about 800 tokens

    result, _ = await _run()

    assert result.success is True
    assert S.attempts == 1
    [*_, refused] = _skill_messages(2)
    assert refused.startswith("Skill 'docx' was not loaded")


async def test_a_skill_the_policy_withholds_is_named_in_the_runs_feed():
    S.withheld = [
        {
            "id": str(uuid.uuid4()),
            "name": "community-pdf",
            "reason": "denied by registry_trust:community",
        }
    ]

    result, _ = await _run()

    assert result.success is True
    [withheld] = [e for e in S.published if e["event_type"] == "skill.withheld"]
    assert withheld["data"]["skill_name"] == "community-pdf"
    assert withheld["data"]["reason"] == "denied by registry_trust:community"
