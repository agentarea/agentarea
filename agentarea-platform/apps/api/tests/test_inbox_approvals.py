"""The inbox reads approvals in the vocabulary the workflow persists.

The inbox looked for ``HumanApprovalRequested``/``HumanApprovalReceived`` events,
but the workflow writes ``approval.request``/``approval.response``. Every pending
approval therefore came back without an escalation id, so the inbox could not
approve or reject anything. These tests persist events with the workflow's own
constants and read them back through GET /inbox and GET /inbox/decisions.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base import get_read_repository_factory
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_execution.workflows.constants import EventTypes
from agentarea_tasks.infrastructure.orm import TaskEventORM, TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

WORKSPACE = "ws-inbox"
OTHER_WORKSPACE = "ws-elsewhere"
APPROVER = "user-approver"
START = datetime(2026, 10, 1, tzinfo=UTC)
AGENT_ID = uuid4()


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: TaskORM.metadata.create_all(
                sync_conn,
                tables=[
                    Table(TaskORM.__tablename__, TaskORM.metadata),
                    Table(TaskEventORM.__tablename__, TaskEventORM.metadata),
                ],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session):
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
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        for dep in (
            get_user_context,
            get_read_repository_factory,
            get_read_task_service,
            get_read_agent_service,
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


def _event(
    session: AsyncSession,
    task: TaskORM,
    event_type: str,
    minute: int,
    workspace: str = WORKSPACE,
    **data,
):
    session.add(
        TaskEventORM(
            id=uuid4(),
            task_id=task.id,
            event_type=event_type,
            timestamp=START + timedelta(minutes=minute),
            data={"task_id": str(task.id), "agent_id": str(AGENT_ID), **data},
            event_metadata={},
            workspace_id=workspace,
            created_by=APPROVER,
        )
    )


@pytest.mark.asyncio
async def test_a_waiting_task_carries_its_unanswered_escalation(client, session):
    task = _task(session, "waiting_for_approval", "Clean the build dir")
    _event(
        session,
        task,
        EventTypes.HUMAN_APPROVAL_REQUESTED,
        1,
        escalation_id="esc-1",
        tool_name="shell",
    )
    _event(
        session,
        task,
        EventTypes.HUMAN_APPROVAL_RECEIVED,
        2,
        escalation_id="esc-1",
        tool_name="shell",
        approved=True,
        approved_by=APPROVER,
    )
    _event(
        session,
        task,
        EventTypes.HUMAN_APPROVAL_REQUESTED,
        3,
        escalation_id="esc-2",
        tool_name="web_fetch",
    )
    await session.commit()

    response = await client.get("/v1/workspaces/acme/inbox/?status=waiting_for_approval")

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["escalation_id"] == "esc-2"
    assert item["escalation_tool_name"] == "web_fetch"


@pytest.mark.asyncio
async def test_an_answered_request_is_no_longer_pending(client, session):
    task = _task(session, "waiting_for_approval", "Deploy")
    _event(
        session,
        task,
        EventTypes.HUMAN_APPROVAL_REQUESTED,
        1,
        escalation_id="esc-1",
        tool_name="deploy",
    )
    _event(
        session,
        task,
        EventTypes.HUMAN_APPROVAL_DENIED,
        2,
        escalation_id="esc-1",
        tool_name="deploy",
        approved=False,
        approved_by=APPROVER,
    )
    await session.commit()

    response = await client.get("/v1/workspaces/acme/inbox/?status=waiting_for_approval")

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["escalation_id"] is None


@pytest.mark.asyncio
async def test_decisions_list_the_outcome_newest_first_within_the_workspace(client, session):
    deploy = _task(session, "completed", "Deploy the preview")
    purge = _task(session, "running", "Purge the cache")
    foreign = _task(session, "completed", "Not yours", workspace=OTHER_WORKSPACE)
    _event(
        session,
        deploy,
        EventTypes.HUMAN_APPROVAL_RECEIVED,
        1,
        escalation_id="esc-a",
        tool_name="deploy",
        approved=True,
        approved_by=APPROVER,
        comment="ship it",
    )
    _event(
        session,
        purge,
        EventTypes.HUMAN_APPROVAL_DENIED,
        2,
        escalation_id="esc-b",
        tool_name="purge",
        approved=False,
        approved_by=APPROVER,
        comment="not today",
    )
    _event(
        session,
        purge,
        EventTypes.HUMAN_APPROVAL_REQUESTED,
        3,
        escalation_id="esc-c",
        tool_name="purge",
    )
    _event(
        session,
        foreign,
        EventTypes.HUMAN_APPROVAL_RECEIVED,
        4,
        workspace=OTHER_WORKSPACE,
        escalation_id="esc-x",
        tool_name="leak",
        approved=True,
        approved_by="someone",
    )
    await session.commit()

    response = await client.get("/v1/workspaces/acme/inbox/decisions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert [
        (d["escalation_id"], d["approved"], d["decided_by"], d["comment"], d["task_description"])
        for d in body["items"]
    ] == [
        ("esc-b", False, APPROVER, "not today", "Purge the cache"),
        ("esc-a", True, APPROVER, "ship it", "Deploy the preview"),
    ]
    assert {d["agent_name"] for d in body["items"]} == {"Ops agent"}
