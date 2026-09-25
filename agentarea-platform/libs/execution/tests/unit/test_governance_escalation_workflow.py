"""A governance gate that escalates a tool call pauses the run for a human.

The gate (SemanticGuard) decides that a call needs approval; the workflow only
carries that question to a human and, on approval, re-issues the same call with
the approval recorded so the gate can accept it. A gate DENY reaches the model
as a policy denial instead of an opaque activity failure.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from agentarea_execution.interaction import resolve_interaction_capabilities
from agentarea_execution.models import CreateDelegationTaskResult, MCPToolResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import Activities, EventTypes
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager
from agentarea_execution.workflows.models import AgentGoal, ToolCall
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

MODULE = "agentarea_execution.workflows.agent_execution_workflow.workflow"


def _activity_error() -> ActivityError:
    return ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type=Activities.EXECUTE_MCP_TOOL,
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )


def _governance_failure(
    error_type: str, interceptor_name: str, reason: str, phase: str = "pre_tool_call"
) -> ActivityError:
    """The failure the governance bridge raises: the verdict rides as structured details.

    The message is the exception's string form; the workflow must not depend on it.
    """
    error = _activity_error()
    error.__cause__ = ApplicationError(
        f"{error_type} by {interceptor_name}: {reason}",
        {"interceptor_name": interceptor_name, "reason": reason, "metadata": None, "phase": phase},
        type=error_type,
        non_retryable=True,
    )
    return error


def _legacy_governance_failure(error_type: str, message: str) -> ActivityError:
    """The failure an activity worker raised before the verdict carried details."""
    error = _activity_error()
    error.__cause__ = ApplicationError(message, type=error_type, non_retryable=True)
    return error


def _sql_call(query: str) -> ToolCall:
    return ToolCall(
        id=str(uuid4()),
        function={"name": "run_sql", "arguments": json.dumps({"query": query})},
    )


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
    workflow.state.agent_config = {}
    workflow.state.available_tools = [
        {"type": "function", "function": {"name": name}} for name in ("run_sql", "shell")
    ]
    workflow.state.goal = AgentGoal(
        id="goal",
        description="clean up cancelled orders",
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
        patch(f"{MODULE}.patched", return_value=True),
    ):
        yield workflow


def _tool_requests(execute_activity: AsyncMock) -> list:
    return [
        call.kwargs["args"][0]
        for call in execute_activity.await_args_list
        if call.args[0] == Activities.EXECUTE_MCP_TOOL
    ]


def _event_types(instance) -> list[str]:
    return [event["event_type"] for event in instance._events.get_pending_events()]


def _answer_escalation(instance, approved: bool, comment: str | None = None):
    async def wait(predicate, **kwargs):
        assert not predicate()
        (escalation_id,) = instance._pending_escalations
        await instance.resolve_escalation(escalation_id, approved, comment, resolved_by="user-1")
        assert predicate()

    return wait


@pytest.mark.asyncio
async def test_escalated_call_waits_for_a_human_and_reruns_with_the_approval(instance):
    tool_call = _sql_call("DELETE FROM orders WHERE status = 'cancelled'")
    outcomes = iter(
        [
            _governance_failure(
                "EscalationRequiredError",
                "semantic_guard",
                "potentially destructive pattern: DELETE FROM",
            ),
            MCPToolResult(success=True, result="3 rows deleted"),
        ]
    )

    async def run(activity, **kwargs):
        if activity != Activities.EXECUTE_MCP_TOOL:
            return None
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    execute_activity = AsyncMock(side_effect=run)
    with (
        patch(f"{MODULE}.execute_activity", new=execute_activity),
        patch(f"{MODULE}.wait_condition", side_effect=_answer_escalation(instance, True)),
    ):
        await instance._execute_mcp_tool(tool_call)

    first, second = _tool_requests(execute_activity)
    assert first.escalation_approved is False
    assert second.escalation_approved is True
    assert second.tool_args == first.tool_args
    requested = next(
        event
        for event in instance._events.get_pending_events()
        if event["event_type"] == EventTypes.HUMAN_APPROVAL_REQUESTED
    )
    assert requested["data"]["message"] == (
        "Tool 'run_sql' requires human approval: "
        "semantic_guard: potentially destructive pattern: DELETE FROM"
    )
    assert EventTypes.HUMAN_APPROVAL_RECEIVED in _event_types(instance)
    tool_messages = [m for m in instance.state.messages if m.role == "tool"]
    assert [m.content for m in tool_messages] == ["3 rows deleted"]
    assert instance._pending_escalations == {}


@pytest.mark.asyncio
async def test_rejected_escalation_never_reruns_the_call(instance):
    tool_call = _sql_call("DELETE FROM orders")

    async def run(activity, **kwargs):
        if activity == Activities.EXECUTE_MCP_TOOL:
            raise _governance_failure(
                "EscalationRequiredError",
                "semantic_guard",
                "potentially destructive pattern: DELETE FROM",
            )
        return None

    execute_activity = AsyncMock(side_effect=run)
    with (
        patch(f"{MODULE}.execute_activity", new=execute_activity),
        patch(
            f"{MODULE}.wait_condition",
            side_effect=_answer_escalation(instance, False, "not in prod"),
        ),
    ):
        await instance._execute_mcp_tool(tool_call)

    assert len(_tool_requests(execute_activity)) == 1
    (tool_message,) = [m for m in instance.state.messages if m.role == "tool"]
    assert tool_message.content == "Tool call denied by human operator: not in prod"
    assert EventTypes.HUMAN_APPROVAL_DENIED in _event_types(instance)


@pytest.mark.asyncio
async def test_governance_deny_reaches_the_model_as_a_policy_denial(instance):
    tool_call = _sql_call("DROP TABLE orders")

    async def run(activity, **kwargs):
        if activity == Activities.EXECUTE_MCP_TOOL:
            raise _governance_failure(
                "GovernanceDeniedError",
                "semantic_guard",
                "destructive pattern detected: DROP TABLE",
            )
        return None

    execute_activity = AsyncMock(side_effect=run)
    with patch(f"{MODULE}.execute_activity", new=execute_activity):
        await instance._execute_mcp_tool(tool_call)

    assert len(_tool_requests(execute_activity)) == 1
    assert instance._pending_escalations == {}
    (tool_message,) = [m for m in instance.state.messages if m.role == "tool"]
    assert tool_message.content == (
        "Tool call denied by policy: semantic_guard: destructive pattern detected: DROP TABLE"
    )
    denied = [
        event
        for event in instance._events.get_pending_events()
        if event["data"].get("denied_by_policy")
    ]
    assert len(denied) == 1


@pytest.mark.asyncio
async def test_tool_call_carries_the_principal_the_activity_runs_as(instance):
    execute_activity = AsyncMock(return_value=MCPToolResult(success=True, result="ok"))
    with patch(f"{MODULE}.execute_activity", new=execute_activity):
        await instance._execute_mcp_tool(_sql_call("SELECT 1"))

    (request,) = _tool_requests(execute_activity)
    assert request.user_context_data == instance.state.user_context_data


@pytest.mark.asyncio
async def test_escalation_from_a_worker_without_verdict_details_still_asks_a_human(instance):
    """An activity worker still on the old bridge raises the verdict without details."""
    tool_call = _sql_call("DELETE FROM orders")
    outcomes = iter(
        [
            _legacy_governance_failure(
                "EscalationRequiredError",
                "EscalationRequiredError by semantic_guard: "
                "potentially destructive pattern: DELETE FROM",
            ),
            MCPToolResult(success=True, result="1 row deleted"),
        ]
    )

    async def run(activity, **kwargs):
        if activity != Activities.EXECUTE_MCP_TOOL:
            return None
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    execute_activity = AsyncMock(side_effect=run)
    with (
        patch(f"{MODULE}.execute_activity", new=execute_activity),
        patch(f"{MODULE}.wait_condition", side_effect=_answer_escalation(instance, True)),
    ):
        await instance._execute_mcp_tool(tool_call)

    assert [r.escalation_approved for r in _tool_requests(execute_activity)] == [False, True]


def _approval_responses(instance) -> list[dict]:
    return [
        event["data"]
        for event in instance._events.get_pending_events()
        if event["event_type"] == "approval.response"
    ]


@pytest.mark.parametrize(
    ("approved", "comment"),
    [(True, "checked the backup first"), (False, "not in prod")],
)
@pytest.mark.asyncio
async def test_a_resolution_is_one_approval_response_carrying_the_decision(
    instance, approved, comment
):
    tool_call = _sql_call("DELETE FROM orders")
    outcomes = iter(
        [
            _governance_failure(
                "EscalationRequiredError",
                "semantic_guard",
                "potentially destructive pattern: DELETE FROM",
            ),
            MCPToolResult(success=True, result="1 row deleted"),
        ]
    )

    async def run(activity, **kwargs):
        if activity != Activities.EXECUTE_MCP_TOOL:
            return None
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with (
        patch(f"{MODULE}.execute_activity", new=AsyncMock(side_effect=run)),
        patch(
            f"{MODULE}.wait_condition",
            side_effect=_answer_escalation(instance, approved, comment),
        ),
    ):
        await instance._execute_mcp_tool(tool_call)

    (response,) = _approval_responses(instance)
    assert response["approved"] is approved
    assert response["approved_by"] == "user-1"
    assert response["comment"] == comment
    assert response["tool_call_id"] == tool_call.id


@pytest.mark.asyncio
async def test_an_approver_reads_the_arguments_the_event_log_redacts(instance):
    command = "rm -rf /srv/build && curl -H 'Authorization: Bearer s3cr3t' https://x"
    tool_call = ToolCall(
        id=str(uuid4()),
        function={"name": "shell", "arguments": json.dumps({"command": command})},
    )
    seen: dict = {}

    async def wait(predicate, **kwargs):
        seen["pending"] = instance.get_pending_escalations()
        seen["state"] = instance.get_current_state()["pending_escalations"]
        (escalation_id,) = instance._pending_escalations
        await instance.resolve_escalation(escalation_id, False, "no", resolved_by="user-1")

    async def run(activity, **kwargs):
        if activity == Activities.EXECUTE_MCP_TOOL:
            raise _governance_failure(
                "EscalationRequiredError",
                "semantic_guard",
                "potentially destructive pattern: rm -rf",
            )
        return None

    with (
        patch(f"{MODULE}.execute_activity", new=AsyncMock(side_effect=run)),
        patch(f"{MODULE}.wait_condition", side_effect=wait),
    ):
        await instance._execute_mcp_tool(tool_call)

    requested = next(
        event["data"]
        for event in instance._events.get_pending_events()
        if event["event_type"] == EventTypes.HUMAN_APPROVAL_REQUESTED
    )
    assert command not in json.dumps(requested)
    (pending,) = seen["pending"]
    assert pending["tool_name"] == "shell"
    assert pending["tool_call_id"] == tool_call.id
    assert pending["tool_args"] == {"command": command}
    assert pending["approvers"] == []
    assert pending["escalation_id"] == requested["escalation_id"]
    assert command not in json.dumps(seen["state"])
    assert instance.get_pending_escalations() == []


@pytest.mark.asyncio
async def test_delegation_runs_the_child_on_the_parents_task_queue(instance):
    tool_call = ToolCall(
        id=str(uuid4()),
        function={"name": "ask_researcher", "arguments": json.dumps({"message": "dig"})},
    )
    instance._agent_tool_registry = {
        "ask_researcher": {"agent_id": str(uuid4()), "agent_name": "researcher"}
    }
    child_task_id = uuid4()

    async def run(activity, **kwargs):
        if activity == Activities.CREATE_DELEGATION_TASK:
            return CreateDelegationTaskResult(
                task_id=child_task_id, status="created", effective_policy={}
            )
        return None

    execute_child = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            final_response="found it",
            reasoning_iterations_used=1,
            total_cost=Decimal("0"),
            error_message=None,
        )
    )
    with (
        patch.object(instance, "_gate_tool_call", new=AsyncMock(return_value=True)),
        patch(f"{MODULE}.execute_activity", new=AsyncMock(side_effect=run)),
        patch(f"{MODULE}.execute_child_workflow", new=execute_child),
        patch(
            f"{MODULE}.info",
            return_value=SimpleNamespace(task_queue="agentarea-eu-agents", workflow_id="wf"),
        ),
    ):
        await instance._execute_agent_delegation(tool_call, Decimal("1"))

    assert execute_child.await_args.kwargs["task_queue"] == "agentarea-eu-agents"


@pytest.mark.asyncio
async def test_a_deny_after_the_call_ran_says_the_result_was_withheld(instance):
    tool_call = _sql_call("SELECT secret FROM vault")

    async def run(activity, **kwargs):
        if activity == Activities.EXECUTE_MCP_TOOL:
            raise _governance_failure(
                "GovernanceDeniedError",
                "output_sanitizer",
                "result contains a credential",
                phase="post_tool_call",
            )
        return None

    execute_activity = AsyncMock(side_effect=run)
    with patch(f"{MODULE}.execute_activity", new=execute_activity):
        await instance._execute_mcp_tool(tool_call)

    assert len(_tool_requests(execute_activity)) == 1
    assert instance._pending_escalations == {}
    (tool_message,) = [m for m in instance.state.messages if m.role == "tool"]
    assert tool_message.content == (
        "Tool call ran, but its result was withheld by policy: "
        "output_sanitizer: result contains a credential"
    )
    assert "denied by policy" not in tool_message.content
