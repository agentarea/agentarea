"""Real migrated PostgreSQL coverage for tenant-scoped raw usage reads.

Set USAGE_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database. No runtime resources are required for historical facts.
"""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.usage.models import ResourceUsageEvent
from agentarea_common.usage.repository import UsageRepository
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("USAGE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="USAGE_TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def insert_fact(session, workspace_id, **fields):
    event = ResourceUsageEvent(
        event_id=str(uuid4()),
        schema_version=1,
        source="usage-test",
        kind="runtime.sample",
        workspace_id=workspace_id,
        resource_kind="mcp_runtime",
        resource_id=str(uuid4()),
        incarnation_id=str(uuid4()),
        task_id="",
        occurred_at=datetime(2026, 9, 18, microsecond=123456, tzinfo=UTC),
        occurred_at_source="2026-09-18T00:00:00.123456789Z",
        data={"cpu_usage_ns": 18446744073709551615},
    )
    for name, value in fields.items():
        setattr(event, name, value)
    session.add(event)
    await session.flush()
    return event


async def test_cursor_and_filters_never_cross_workspace(session):
    first_ws, other_ws = str(uuid4()), str(uuid4())
    first = await insert_fact(session, first_ws)
    foreign = await insert_fact(session, other_ws)
    last = await insert_fact(session, first_ws)
    await insert_fact(session, "", resource_kind="platform_runtime")
    repo = UsageRepository(session, UserContext(user_id="usage-reader", workspace_id=first_ws))

    page = await repo.query(limit=1)
    assert [row.event_id for row in page] == [last.event_id]
    page = await repo.query(cursor=last.sequence, limit=1)
    assert [row.event_id for row in page] == [first.event_id]
    # Foreign cursors are never loaded without workspace scope: they are just
    # sequence boundaries on a query already constrained to the caller's tenant.
    page = await repo.query(cursor=foreign.sequence)
    assert [row.event_id for row in page] == [first.event_id]
    assert await repo.query(resource_id=foreign.resource_id) == []
    page = await repo.query(resource_id=first.resource_id)
    assert [row.event_id for row in page] == [first.event_id]
    assert page[0].data["cpu_usage_ns"] == 18446744073709551615
    assert page[0].occurred_at_source == "2026-09-18T00:00:00.123456789Z"


async def test_raw_facts_cannot_be_rewritten_or_deleted(session):
    event = await insert_fact(session, str(uuid4()))
    sequence = event.sequence
    # Savepoints keep this test's insertion available after each rejected write.
    for statement in (
        "UPDATE resource_usage_events SET data='{}' WHERE sequence=:sequence",
        "DELETE FROM resource_usage_events WHERE sequence=:sequence",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with session.begin_nested():
                await session.execute(text(statement), {"sequence": sequence})
    result = await session.execute(
        text("SELECT data->>'cpu_usage_ns' FROM resource_usage_events WHERE sequence=:sequence"),
        {"sequence": sequence},
    )
    assert result.scalar_one() == "18446744073709551615"


async def test_usage_endpoint_paginates_raw_facts_without_tenant_override(session):
    from agentarea_api.api.v1.usage import router
    from agentarea_common.auth.dependencies import get_user_context
    from agentarea_common.config.database import get_db_session
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    workspace, foreign_workspace = str(uuid4()), str(uuid4())
    first = await insert_fact(session, workspace)
    foreign = await insert_fact(session, foreign_workspace)
    last = await insert_fact(session, workspace)
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="usage-reader", workspace_id=workspace
    )
    app.dependency_overrides[get_db_session] = lambda: session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/usage/events", params={"limit": 1, "workspace_id": foreign_workspace}
        )
        assert response.status_code == 200
        page = response.json()
        assert [event["id"] for event in page["events"]] == [last.event_id]
        raw_data = page["events"][0]["data_json"]
        assert isinstance(raw_data, str)
        assert json.loads(raw_data)["cpu_usage_ns"] == 18446744073709551615
        assert page["events"][0]["occurred_at"] == "2026-09-18T00:00:00.123456789Z"
        assert page["events"][0]["schema_version"] == 1
        response = await client.get(
            "/v1/usage/events", params={"limit": 1, "cursor": page["next_cursor"]}
        )
        assert response.status_code == 200
        assert [event["id"] for event in response.json()["events"]] == [first.event_id]
        assert response.json()["next_cursor"] is None
        response = await client.get("/v1/usage/events", params={"resource_id": foreign.resource_id})
        assert response.json() == {"events": [], "next_cursor": None}
        response = await client.get("/v1/usage/events", params={"limit": 101})
        assert response.status_code == 422
        await insert_fact(session, workspace, occurred_at_source="2026-09-18T00:00:00.123456788Z")
        await insert_fact(session, workspace, occurred_at_source="2026-09-18T00:00:00.123456790Z")
        response = await client.get(
            "/v1/usage/events",
            params={
                "from": "2026-09-18T05:30:00.123456789+05:30",
                "until": "2026-09-18T00:00:00.123456789Z",
            },
        )
        assert response.status_code == 200
        assert [event["id"] for event in response.json()["events"]] == [
            last.event_id,
            first.event_id,
        ]
