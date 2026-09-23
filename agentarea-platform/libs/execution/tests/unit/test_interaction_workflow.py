import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from agentarea_execution.interaction import resolve_interaction_capabilities
from agentarea_execution.models import ArtifactValidationResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager
from agentarea_execution.workflows.models import AgentGoal, Message, PendingEscalation, ToolCall

MODULE = "agentarea_execution.workflows.agent_execution_workflow.workflow"


def call(name, **arguments):
    return ToolCall(id=str(uuid4()), function={"name": name, "arguments": json.dumps(arguments)})


@pytest.fixture
def instance():
    workflow = AgentExecutionWorkflow()
    workflow.state.task_id = str(uuid4())
    workflow.state.agent_id = str(uuid4())
    workflow.state.workspace_id = "workspace-1"
    workflow.state.user_id = "user-1"
    workflow.state.execution_id = "task-1"
    workflow.state.user_context_data = {"user_id": "user-1", "workspace_id": "workspace-1"}
    workflow.state.context_window = 128000
    workflow.state.budget_usd = 1
    workflow.state.agent_config = {"a2ui_enabled": True}
    workflow.state.goal = AgentGoal(
        id="goal",
        description="deliver",
        success_criteria=[],
        max_iterations=5,
        requires_human_approval=False,
        context={},
    )
    workflow.state.effective_policy = {
        "execution": {"max_tool_calls_per_turn": 10, "max_tool_calls_total": 100},
        "tokens": {"max_tokens": 20000},
    }
    workflow.state.interaction_capabilities = resolve_interaction_capabilities({}, {}, True)
    workflow.event_manager = EventManager(
        task_id=workflow.state.task_id,
        agent_id=workflow.state.agent_id,
        execution_id=workflow.state.execution_id,
    )
    workflow.budget_tracker = BudgetTracker(1)
    workflow._publish_events_immediately = AsyncMock()
    with (
        patch(f"{MODULE}.logger", new=Mock()),
        patch(f"{MODULE}.uuid4", side_effect=uuid4),
        patch(f"{MODULE}.execute_activity", new=AsyncMock()),
    ):
        yield workflow


@pytest.mark.parametrize(
    ("parameters", "metadata", "web"),
    [
        ({}, {}, True),
        ({}, {"source": "api"}, True),
        ({"trigger_id": "trigger"}, {}, False),
        ({}, {"source": "agent_delegation"}, False),
        ({}, {"source": "mcp"}, False),
        ({}, {"created_via": "mcp"}, False),
        ({}, {"created_via": "api", "scheduled_at": "2026-09-21T00:00:00Z"}, False),
        ({"interaction": {"channel": "web"}}, {"scheduled_at": "2026-09-21T00:00:00Z"}, True),
        ({"channel_origin": {"type": "github"}}, {}, False),
        ({"channel_origin": {"type": "telegram"}}, {}, False),
        ({"trigger_id": "trigger", "interaction": {"channel": "web"}}, {}, True),
        ({"trigger_id": "trigger", "channel_origin": {"type": "web"}}, {}, True),
        ({"channel_origin": {"type": "web"}, "interaction": {"channel": "none"}}, {}, False),
    ],
)
def test_capabilities_require_a_supported_return_route(parameters, metadata, web):
    capabilities = resolve_interaction_capabilities(parameters, metadata, True)
    assert capabilities.allow_questions is web
    assert capabilities.allow_approvals is web
    assert capabilities.allow_a2ui is web


def test_restrictions_cannot_grant_a_missing_channel_or_agent_feature():
    absent = resolve_interaction_capabilities(
        {"trigger_id": "trigger", "interaction": {"allow_questions": True}}, {}, True
    )
    assert absent.allow_questions is False
    restricted = resolve_interaction_capabilities(
        {"interaction": {"allow_questions": False, "allow_approvals": False}}, {}, False
    )
    assert restricted.allow_questions is False
    assert restricted.allow_approvals is False
    assert restricted.allow_a2ui is False


@pytest.mark.asyncio
async def test_required_form_pairs_same_turn_completion_but_never_completes_before_answer(instance):
    request = call("request_user_input", question="Which environment?")
    completion = call("completion", result="premature", artifacts=[])
    side_effect = call("shell", command="deploy")
    instance.state.messages.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": tool.id, "type": "function", "function": tool.function}
                for tool in (request, completion, side_effect)
            ],
        )
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def wait(predicate, **kwargs):
        entered.set()
        await release.wait()
        assert predicate()

    with patch(f"{MODULE}.wait_condition", side_effect=wait):
        task = asyncio.create_task(instance._execute_tool_calls([request, completion, side_effect]))
        await entered.wait()
        assert instance.state.status == "waiting_for_input"
        assert instance.state.success is False
        pending_id = next(iter(instance._pending_input_requests))
        instance._handle_submit_user_input(
            {"input_request_id": "unrelated", "answers": {"answer": "prod"}}
        )
        assert not instance._pending_input_requests[pending_id]["resolved"]
        instance._handle_submit_user_input(
            {"input_request_id": pending_id, "answers": {"answer": "dev"}}
        )
        release.set()
        await task

    assert instance.state.success is False
    results = [m for m in instance.state.messages if m.role == "tool"]
    assert {m.tool_call_id for m in results} == {request.id, completion.id, side_effect.id}
    assert len(results) == 3
    assert json.loads(next(m.content for m in results if m.tool_call_id == request.id))[
        "answers"
    ] == {"answer": "dev"}


@pytest.mark.asyncio
async def test_input_timeout_stops_main_loop_without_second_model_turn(instance):
    request = call("request_user_input", question="Required account ID?")
    calls = 0

    async def iteration():
        nonlocal calls
        calls += 1
        await instance._execute_tool_calls([request])

    instance._execute_iteration = iteration
    with patch(f"{MODULE}.wait_condition", new=AsyncMock(side_effect=TimeoutError)):
        await instance._execute_main_loop()
    assert calls == 1
    assert instance.state.status == "blocked"
    assert instance.state.failure_reason == "input_timeout"
    assert instance.state.success is False
    assert instance._pending_input_requests == {}


@pytest.mark.asyncio
async def test_unavailable_questions_return_feedback_and_allow_autonomous_completion(instance):
    instance.state.interaction_capabilities = resolve_interaction_capabilities(
        {"trigger_id": "t"}, {}, True
    )
    with patch(f"{MODULE}.wait_condition", new=AsyncMock()) as wait:
        await instance._execute_request_user_input(
            call("request_user_input", question="Preference?")
        )
    wait.assert_not_awaited()
    assert not instance._pending_input_requests
    assert "autonomously" in instance.state.messages[-1].content
    assert "input.request" not in [e["event_type"] for e in instance._events.get_pending_events()]
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=0)
    )
    await instance._handle_task_completion(
        call("completion", result="Completed using available data", artifacts=[])
    )
    assert instance.state.success is True
    assert instance._awaiting_input is False


@pytest.mark.asyncio
async def test_policy_denied_questions_do_not_wait(instance):
    instance.state.effective_policy["tools"] = {"denied": ["request_user_*"]}
    assert instance._questions_available is False
    with patch(f"{MODULE}.wait_condition", new=AsyncMock()) as wait:
        await instance._execute_request_user_input(call("request_user_input", question="Ask?"))
    wait.assert_not_awaited()
    assert not instance._pending_input_requests


@pytest.mark.asyncio
async def test_bound_a2ui_action_answers_only_matching_request(instance):
    instance.state.a2ui_surfaces = {"form": {"submit": "submit"}, "other": {"button": "click"}}
    instance._pending_input_requests = {
        "request": {
            "surface_id": "form",
            "resolved": False,
            "questions": [{"id": "answer", "type": "text", "required": True}],
        }
    }
    await instance.handle_a2ui_action(
        {"surface_id": "other", "name": "click", "context": {"answer": "wrong"}}
    )
    assert not instance._pending_input_requests["request"]["resolved"]
    await instance.handle_a2ui_action(
        {"surface_id": "form", "name": "undeclared", "context": {"answer": "wrong"}}
    )
    assert not instance._pending_input_requests["request"]["resolved"]
    await instance.handle_a2ui_action(
        {"surface_id": "form", "name": "submit", "context": {"answer": "right"}}
    )
    assert instance._pending_input_requests["request"]["submission"] == {
        "answers": {"answer": "right"},
        "secret_refs": {},
    }
    assert instance._a2ui_action_queue == []


@pytest.mark.asyncio
async def test_a2ui_cannot_supply_secrets_or_skip_required_fields(instance):
    instance.state.a2ui_surfaces = {"form": {"submit": "submit"}}
    pending = {
        "surface_id": "form",
        "resolved": False,
        "questions": [{"id": "token", "type": "secret", "required": True}],
    }
    instance._pending_input_requests["request"] = pending
    await instance.handle_a2ui_action(
        {"surface_id": "form", "name": "submit", "context": {"token": "raw-secret"}}
    )
    assert pending["resolved"] is False
    assert instance._a2ui_action_queue == []
    instance._handle_submit_user_input({"input_request_id": "request", "answers": {}})
    assert pending["resolved"] is False
    instance._handle_submit_user_input(
        {"input_request_id": "request", "secret_refs": {"token": {"secret_ref": "secret:token"}}}
    )
    assert pending["resolved"] is True


@pytest.mark.asyncio
async def test_ordinary_a2ui_action_wakes_follow_up(instance):
    instance._awaiting_input = True
    instance.state.a2ui_surfaces = {"card": {"button": "refresh"}}
    await instance.handle_a2ui_action({"surface_id": "card", "name": "refresh", "context": {}})

    async def wait(predicate, **kwargs):
        assert predicate()

    with patch(f"{MODULE}.wait_condition", side_effect=wait):
        await instance._await_follow_up()
    assert instance._awaiting_input is False
    assert instance._a2ui_action_queue[0]["name"] == "refresh"


@pytest.mark.asyncio
async def test_unavailable_approval_denies_tool_without_escalation(instance):
    instance.state.interaction_capabilities = resolve_interaction_capabilities(
        {"interaction": {"allow_approvals": False}}, {}, True
    )
    instance.state.effective_policy["approval"] = {
        "requires_human_approval": True,
        "approvers": ["user:owner"],
    }
    with patch(f"{MODULE}.wait_condition", new=AsyncMock()) as wait:
        allowed = await instance._gate_tool_call(call("shell", command="deploy"))
    assert allowed is False
    wait.assert_not_awaited()
    assert instance._pending_escalations == {}
    assert "approval" in instance.state.messages[-1].content


@pytest.mark.asyncio
async def test_a2ui_action_never_approves_escalation(instance):
    instance.state.a2ui_surfaces = {"approval": {"button": "approve"}}
    escalation = PendingEscalation(
        escalation_id="escalation",
        tool_call_id="tool",
        tool_name="shell",
        tool_args={},
        approvers=["user:owner"],
    )
    instance._pending_escalations["escalation"] = escalation
    await instance.handle_a2ui_action(
        {
            "surface_id": "approval",
            "name": "approve",
            "context": {"escalation_id": "escalation", "approved": True},
        }
    )
    assert escalation.resolved is False
    await instance.resolve_escalation("escalation", True, resolved_by="intruder")
    assert escalation.resolved is False


@pytest.mark.asyncio
async def test_blocked_completion_is_truthful_and_still_validates_artifacts(instance):
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=0)
    )
    await instance._handle_task_completion(
        call("completion", result="No credentials are available", outcome="blocked", artifacts=[])
    )
    instance._validate_completion_artifacts.assert_awaited_once_with([])
    assert instance.state.status == "blocked"
    assert instance.state.success is False
    assert instance._awaiting_input is False


@pytest.mark.asyncio
async def test_unavailable_input_is_hidden_from_actual_model_request(instance):
    instance.state.interaction_capabilities = resolve_interaction_capabilities(
        {"interaction": {"allow_questions": False}},
        {},
        True,
    )
    instance.state.available_tools = [
        {"type": "function", "function": {"name": "request_user_input"}},
        {"type": "function", "function": {"name": "completion"}},
    ]

    async def model_activity(name, *, args, **kwargs):
        assert [tool["function"]["name"] for tool in args[0].tools] == ["completion"]
        return {
            "content": "Completed autonomously",
            "role": "assistant",
            "tool_calls": [],
            "cost": 0.001,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    with patch(f"{MODULE}.execute_activity", side_effect=model_activity):
        response = await instance._call_llm()
    assert response["content"] == "Completed autonomously"


@pytest.mark.asyncio
async def test_surface_bound_secret_request_is_rejected_before_emitting_input(instance):
    instance.state.a2ui_surfaces = {"form": {"submit": "submit"}}
    await instance._execute_request_user_input(
        call(
            "request_user_input",
            surface_id="form",
            questions=[{"id": "token", "type": "secret", "question": "API token"}],
        )
    )
    assert instance._pending_input_requests == {}
    assert "native input form" in instance.state.messages[-1].content
    assert "input.request" not in [e["event_type"] for e in instance._events.get_pending_events()]


@pytest.mark.asyncio
async def test_published_surface_action_resolves_bound_input_and_retires_its_actions(instance):
    request = call(
        "request_user_input",
        surface_id="form",
        questions=[
            {
                "id": "environment",
                "type": "select",
                "question": "Environment",
                "options": ["dev", "prod"],
            }
        ],
        allow_custom_response=False,
    )
    events = [
        {"type": "A2UICreateSurface", "surface_id": "form"},
        {
            "type": "A2UIUpdateComponents",
            "surface_id": "form",
            "components": [
                {"id": "submit", "component": "Button", "action": {"event": {"name": "submit"}}},
            ],
        },
    ]
    action = {
        "surface_id": "form",
        "source_component_id": "submit",
        "name": "submit",
        "context": {"environment": ["dev"]},
    }

    async def wait(predicate, **kwargs):
        assert not predicate()
        pending_id = next(iter(instance._pending_input_requests))
        assert instance._pending_input_requests[pending_id]["surface_id"] == "form"
        await instance.handle_a2ui_action({**action, "context": {"environment": ["invalid"]}})
        assert not predicate()
        await instance.handle_a2ui_action({**action, "context": {"environment": ["dev", "prod"]}})
        assert not predicate()
        await instance.handle_a2ui_action(action)
        assert predicate()

    with patch(f"{MODULE}.wait_condition", side_effect=wait):
        await instance._process_llm_response(
            {
                "content": "Choose an environment\n---a2ui_JSON---\n"
                + json.dumps({"events": events}),
                "tool_calls": [
                    {"id": request.id, "type": "function", "function": request.function}
                ],
            }
        )
    tool_result = next(message for message in instance.state.messages if message.role == "tool")
    assert json.loads(tool_result.content)["answers"] == {"environment": "dev"}
    interaction_events = [
        event
        for event in instance._events.get_pending_events()
        if event["event_type"] in {"input.request", "input.response"}
    ]
    assert [event["data"]["surface_id"] for event in interaction_events] == ["form", "form"]
    await instance.handle_a2ui_action(action)
    assert instance._a2ui_action_queue == []
    assert instance.state.success is False


@pytest.mark.asyncio
async def test_continue_as_new_preserves_capabilities_and_surface_request_identity(instance):
    instance.state.interaction_capabilities = resolve_interaction_capabilities(
        {"interaction": {"channel": "web", "allow_approvals": False}},
        {},
        True,
    )
    instance.state.a2ui_surfaces = {"form": {"submit": "submit"}}
    instance._pending_input_requests = {
        "pending": {
            "surface_id": "form",
            "resolved": False,
            "questions": [{"id": "answer", "type": "text", "required": True}],
        },
    }
    instance._compact_context_if_needed = AsyncMock()
    with (
        patch(f"{MODULE}.info", return_value=Mock(run_id="run-1")),
        patch(f"{MODULE}.continue_as_new") as rollover,
    ):
        await instance._continue_as_new()
    request = rollover.call_args.kwargs["args"][0]
    restored = AgentExecutionWorkflow()
    await restored._restore_from_continued_state(request.continued_state)
    assert restored.state.interaction_capabilities.allow_approvals is False
    assert restored._a2ui_available is True
    await restored.handle_a2ui_action(
        {
            "surface_id": "form",
            "source_component_id": "submit",
            "name": "submit",
            "context": {"answer": "restored"},
        }
    )
    assert restored._pending_input_requests["pending"]["submission"]["answers"] == {
        "answer": "restored"
    }


@pytest.mark.asyncio
async def test_completed_business_turn_waits_until_execution_finished_event(instance):
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="passed", generation=0)
    )

    async def iteration():
        await instance._handle_task_completion(call("completion", result="Delivered", artifacts=[]))

    instance._execute_traditional_iteration = iteration
    instance._check_budget_status = AsyncMock()
    await instance._execute_iteration()
    events = instance._events.get_pending_events()
    completed = next(event for event in events if event["event_type"] == "task.completed")
    assert completed["data"]["execution_status"] == "waiting"
    waiting = next(event for event in events if event["event_type"] == "task.awaiting_follow_up")
    assert waiting["data"]["final_response"] == "Delivered"
    assert "execution.finished" not in [event["event_type"] for event in events]
    result = await instance._finalize_execution({})
    assert result.status == "completed"
    finished = instance._events.get_pending_events()[-1]
    assert finished["event_type"] == "execution.finished"
    assert finished["data"]["execution_status"] == "completed"


@pytest.mark.asyncio
async def test_blocked_outcome_cannot_bypass_artifact_validation_failure(instance):
    instance._validate_completion_artifacts = AsyncMock(
        return_value=ArtifactValidationResult(state="failed", generation=1)
    )
    await instance._handle_task_completion(
        call(
            "completion",
            result="Credentials missing; partial report attached",
            outcome="blocked",
            artifacts=["missing.pdf"],
        )
    )
    assert instance.state.success is False
    assert instance.state.final_response is None
    assert instance.state.validation_repair_attempts == 1
    assert instance.state.status != "blocked"
    assert json.loads(instance.state.messages[-1].content)["status"] == "validation_failed"
