"""A failed task's API record must surface a legible terminal cause."""

from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import (
    TaskResponse,
    TaskWithAgent,
    _failure_reason_from_result,
)
from agentarea_tasks.domain.models import AgentTask


def _failed_agent_task(*, error_message: str, failure_reason: str) -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="failed",
        error_message=error_message,
        result={
            "response": None,
            "conversation_history": [{"role": "user", "content": "hi"}],
            "failure_reason": failure_reason,
            "status": "failed",
        },
    )


def test_validation_terminal_surfaces_error_and_failure_reason() -> None:
    task = _failed_agent_task(
        error_message="Artifact validation failed after two repair attempts",
        failure_reason="validation_failed",
    )

    response = TaskResponse.from_agent_task(task)

    assert response.status == "failed"
    assert response.error == "Artifact validation failed after two repair attempts"
    assert response.failure_reason == "validation_failed"
    # Partial work context must not be dropped when surfacing the cause.
    assert response.result["conversation_history"]


@pytest.mark.parametrize(
    ("error_message", "failure_reason"),
    [
        ("Maximum iterations reached (10)", "iteration_limit"),
        ("Budget exceeded ($1.00/$1.00)", "budget_exceeded"),
    ],
)
def test_iteration_and_budget_terminals_surface_cause(
    error_message: str, failure_reason: str
) -> None:
    task = _failed_agent_task(error_message=error_message, failure_reason=failure_reason)

    response = TaskResponse.from_agent_task(task)

    assert response.error == error_message
    assert response.failure_reason == failure_reason


def test_task_with_agent_carries_failure_cause_through() -> None:
    task = _failed_agent_task(
        error_message="Artifact validation failed after two repair attempts",
        failure_reason="validation_failed",
    )
    response = TaskResponse.from_agent_task(task)

    with_agent = TaskWithAgent.from_task_response(response, "agent-name")

    assert with_agent.error == response.error
    assert with_agent.failure_reason == "validation_failed"


def test_failure_reason_helper_ignores_missing_or_non_dict_result() -> None:
    assert _failure_reason_from_result(None) is None
    assert _failure_reason_from_result("done") is None
    assert _failure_reason_from_result({}) is None
    assert _failure_reason_from_result({"failure_reason": "iteration_limit"}) == "iteration_limit"
