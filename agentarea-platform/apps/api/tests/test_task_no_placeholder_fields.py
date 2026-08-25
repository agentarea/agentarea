"""A task record must never invent values for fields it could not resolve.

`agent_name="Unknown"` and `execution_id="unknown"` used to be substituted when
the lookup came up empty. Both are indistinguishable from real values, so the
UI rendered a confident "Unknown" breadcrumb over what was actually a missing
agent — and callers had no way to detect the difference. Absent means null.
"""

from datetime import UTC, datetime
from uuid import uuid4

from agentarea_api.api.v1.agents_tasks import TaskEvent, TaskResponse, TaskWithAgent
from agentarea_tasks.domain.models import AgentTask


def _agent_task() -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="completed",
    )


def test_agent_name_is_null_when_the_agent_does_not_resolve() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    with_agent = TaskWithAgent.from_task_response(response, None)

    assert with_agent.agent_name is None
    assert with_agent.model_dump()["agent_name"] is None


def test_agent_name_is_carried_through_when_it_does_resolve() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    with_agent = TaskWithAgent.from_task_response(response, "neuresearch")

    assert with_agent.agent_name == "neuresearch"


def test_task_event_execution_id_is_null_rather_than_a_placeholder() -> None:
    event = TaskEvent(
        id=str(uuid4()),
        task_id=str(uuid4()),
        agent_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        event_type="task.started",
        message="started",
    )

    assert event.execution_id is None
