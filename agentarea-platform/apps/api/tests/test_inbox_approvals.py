"""The inbox reads approvals from the running workflow and the audit trail.

A task waiting for approval shows the escalation its workflow still holds open,
read through the workflow's ``get_pending_escalations`` query. The decisions list
reads the ``approval.approved``/``approval.denied`` rows the tool audit writes to
``audit_events`` (wiki ADR-0042). Neither reads the old ``task_events``.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.execution_service import WorkflowNotFoundError
from agentarea_api.api.deps.services import (
    get_read_agent_service,
    get_read_task_service,
    get_temporal_workflow_service,
)
from agentarea_api.main import app
from agentarea_common.audit import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base import get_read_repository_factory
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_execution.activities.agent.tool_audit import APPROVAL_APPROVED, APPROVAL_DENIED
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

WORKSPACE = "ws-inbox"
OTHER_WORKSPACE = "ws-elsewhere"
APPROVER = "user-approver"
START = datetime(2026, 10, 1, tzinfo=UTC)
AGENT_ID = uuid4()


class FakeWorkflows:
    """Pending escalations per workflow id; a missing id is a workflow that is gone."""

    def __init__(self):
        self.pending: dict[str, list[dict] | Exception] = {}
        self.queried: list[str] = []

    async def get_pending_escalations(self, execution_id: str) -> list[dict]:
        self.queried.append(execution_id)
        pending = self.pending.get(execution_id)
        if pending is None:
            raise WorkflowNotFoundError(execution_id)
        if isinstance(pending, Exception):
            raise pending
        return pending


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: TaskORM.metadata.create_all(
                sync_conn,
                tables=[
                    Table(TaskORM.__tablename__, TaskORM.metadata),
                    Table(AuditEventORM.__tablename__, AuditEventORM.metadata),
                ],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def workflows() -> FakeWorkflows:
    return FakeWorkflows()


@pytest_asyncio.fixture
async def client(session, workflows):
    context = UserContext(user_id=APPROVER, workspace_id=WORKSPACE)
    agent = SimpleNamespace(id=AGENT_ID, name="Ops agent")
    app.dependency_overrides[get_user_context] = lambda: context
    app.dependency_overrides[get_read_repository_factory] = lambda: RepositoryFactory(
        session, context
    )
    app.dependency_overrides[get_read_task_service] = lambda: SimpleNamespace(
        task_repository=TaskRepository(session, context)
    )
    app.dependency_overrides[get_read_agent_service] = lambda: SimpleNamespace(
        list=AsyncMock(return_value=[agent])
    )
    app.dependency_overrides[get_temporal_workflow_service] = lambda: workflows
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        for dep in (
            get_user_context,
            get_read_repository_factory,
            get_read_task_service,
            get_read_agent_service,
            get_temporal_workflow_service,
        ):
            app.dependency_overrides.pop(dep, None)


def _task(session: AsyncSession, status: str, description: str, workspace: str = WORKSPACE):
    task = TaskORM(
        id=uuid4(),
        agent_id=AGENT_ID,
        description=description,
        status=status,
        parameters={},
        workspace_id=workspace,
        created_by=APPROVER,
        created_at=START,
        updated_at=START,
    )
    session.add(task)
    return task


def _escalation(escalation_id: str, tool_name: str) -> dict:
    return {
        "escalation_id": escalation_id,
        "tool_name": tool_name,
        "tool_call_id": f"call-{escalation_id}",
        "tool_args": {"path": "/srv"},
        "approvers": [APPROVER],
    }


def _decision(
    session: AsyncSession,
    task: TaskORM,
    minute: int,
    *,
    approved: bool,
    workspace: str = WORKSPACE,
    **metadata,
):
    session.add(
        AuditEventORM(
            id=uuid4(),
            actor_id=APPROVER,
            actor_type="user",
            workspace_id=workspace,
            action=APPROVAL_APPROVED if approved else APPROVAL_DENIED,
            resource_type="task",
            resource_id=str(task.id),
            event_metadata={
                "task_id": str(task.id),
                "agent_id": str(AGENT_ID),
                "decision": "approved" if approved else "denied",
                "requested_by": APPROVER,
                **metadata,
            },
            created_at=START + timedelta(minutes=minute),
            updated_at=START + timedelta(minutes=minute),
        )
    )


@pytest.mark.asyncio
async def test_a_waiting_task_carries_the_escalation_its_workflow_holds_open(
    client, session, workflows
):
    task = _task(session, "waiting_for_approval", "Clean the build dir")
    _task(session, "completed", "Already done")
    await session.commit()
    workflows.pending[f"task-{task.id}"] = [_escalation("esc-2", "web_fetch")]

    response = await client.get("/v1/workspaces/acme/inbox/")

    assert response.status_code == 200, response.text
    items = {item["description"]: item for item in response.json()["items"]}
    assert (
        items["Clean the build dir"]["escalation_id"],
        items["Clean the build dir"]["escalation_tool_name"],
    ) == ("esc-2", "web_fetch")
    assert items["Already done"]["escalation_id"] is None
    assert workflows.queried == [f"task-{task.id}"]


@pytest.mark.asyncio
async def test_with_several_open_the_latest_escalation_is_surfaced(client, session, workflows):
    task = _task(session, "waiting_for_approval", "Deploy")
    await session.commit()
    workflows.pending[f"task-{task.id}"] = [
        _escalation("esc-1", "build"),
        _escalation("esc-2", "deploy"),
    ]

    response = await client.get("/v1/workspaces/acme/inbox/?status=waiting_for_approval")

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert (item["escalation_id"], item["escalation_tool_name"]) == ("esc-2", "deploy")


@pytest.mark.asyncio
async def test_nothing_open_or_a_workflow_gone_leaves_the_task_without_an_escalation(
    client, session, workflows
):
    answered = _task(session, "waiting_for_approval", "Answered")
    gone = _task(session, "waiting_for_approval", "Gone")
    failing = _task(session, "waiting_for_approval", "Unreachable")
    await session.commit()
    workflows.pending[f"task-{answered.id}"] = []
    workflows.pending[f"task-{failing.id}"] = RuntimeError("temporal unavailable")

    response = await client.get("/v1/workspaces/acme/inbox/?status=waiting_for_approval")

    assert response.status_code == 200, response.text
    assert {item["description"]: item["escalation_id"] for item in response.json()["items"]} == {
        "Answered": None,
        "Gone": None,
        "Unreachable": None,
    }
    assert sorted(workflows.queried) == sorted(
        f"task-{task.id}" for task in (answered, gone, failing)
    )


@pytest.mark.asyncio
async def test_decisions_list_the_audited_outcome_newest_first_within_the_workspace(
    client, session
):
    deploy = _task(session, "completed", "Deploy the preview")
    purge = _task(session, "running", "Purge the cache")
    foreign = _task(session, "completed", "Not yours", workspace=OTHER_WORKSPACE)
    _decision(
        session,
        deploy,
        1,
        approved=True,
        tool="deploy",
        escalation_id="esc-a",
        comment="ship it",
    )
    _decision(
        session,
        purge,
        2,
        approved=False,
        tool="purge",
        escalation_id="esc-b",
        comment="not today",
    )
    _decision(
        session,
        foreign,
        3,
        approved=True,
        workspace=OTHER_WORKSPACE,
        tool="leak",
        escalation_id="esc-x",
    )
    session.add(
        AuditEventORM(
            id=uuid4(),
            actor_id=str(AGENT_ID),
            actor_type="agent",
            workspace_id=WORKSPACE,
            action="tool.call.approval_required",
            resource_type="task",
            resource_id=str(purge.id),
            event_metadata={"escalation_id": "esc-c", "tool": "purge"},
            created_at=START + timedelta(minutes=4),
            updated_at=START + timedelta(minutes=4),
        )
    )
    await session.commit()

    response = await client.get("/v1/workspaces/acme/inbox/decisions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert [
        (
            d["escalation_id"],
            d["task_id"],
            d["tool_name"],
            d["approved"],
            d["decided_by"],
            d["comment"],
            d["task_description"],
            d["decided_at"],
        )
        for d in body["items"]
    ] == [
        (
            "esc-b",
            str(purge.id),
            "purge",
            False,
            APPROVER,
            "not today",
            "Purge the cache",
            "2026-10-01T00:02:00Z",
        ),
        (
            "esc-a",
            str(deploy.id),
            "deploy",
            True,
            APPROVER,
            "ship it",
            "Deploy the preview",
            "2026-10-01T00:01:00Z",
        ),
    ]
    assert {(d["agent_id"], d["agent_name"]) for d in body["items"]} == {
        (str(AGENT_ID), "Ops agent")
    }


@pytest.mark.asyncio
async def test_decisions_page_and_a_system_decision_names_no_person(client, session):
    task = _task(session, "completed", "Rotate keys")
    for minute in range(3):
        _decision(session, task, minute, approved=True, escalation_id=f"esc-{minute}")
    session.add(
        AuditEventORM(
            id=uuid4(),
            actor_id=APPROVER,
            actor_type="system",
            workspace_id=WORKSPACE,
            action=APPROVAL_DENIED,
            resource_type="task",
            resource_id=str(task.id),
            event_metadata={"escalation_id": "esc-timeout", "decision": "denied"},
            created_at=START + timedelta(minutes=10),
            updated_at=START + timedelta(minutes=10),
        )
    )
    await session.commit()

    first = await client.get("/v1/workspaces/acme/inbox/decisions?page=1&page_size=2")
    second = await client.get("/v1/workspaces/acme/inbox/decisions?page=2&page_size=2")

    assert first.status_code == 200, first.text
    assert first.json()["total"] == 4
    assert [(d["escalation_id"], d["decided_by"]) for d in first.json()["items"]] == [
        ("esc-timeout", None),
        ("esc-2", APPROVER),
    ]
    assert [d["escalation_id"] for d in second.json()["items"]] == ["esc-1", "esc-0"]
