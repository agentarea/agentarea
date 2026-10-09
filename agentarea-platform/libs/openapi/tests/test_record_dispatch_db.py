"""Recording an OpenAPI connection's last call, against a real schema.

The write is a bare UPDATE that must hit only the caller's workspace and must
not move ``updated_at`` -- a call is not an edit. Both are decided by the SQL
the repository emits, which a mocked session cannot see.

Needs a PostgreSQL migrated to head; skips without one:

    OPENAPI_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import os
import uuid
from collections.abc import AsyncGenerator

import agentarea_mcp.domain.auth_models  # noqa: F401  (openapi_connections.auth_config_id)
import agentarea_registry.domain.models  # noqa: F401  (openapi_connections.registry_item_id)
import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("OPENAPI_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="OPENAPI_TEST_DATABASE_URL not set; skipping schema-backed OpenAPI dispatch tests",
)

WORKSPACE = "openapi-dispatch-ws"
OTHER_WORKSPACE = "openapi-dispatch-other"
DISPATCH = {"status": "succeeded", "at": "2026-10-09T12:00:00+00:00", "error": None}


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        await _cleanup(s)
        yield s
        await _cleanup(s)
    await engine.dispose()


async def _cleanup(s: AsyncSession) -> None:
    await s.execute(
        text("DELETE FROM openapi_connections WHERE workspace_id IN (:a, :b)"),
        {"a": WORKSPACE, "b": OTHER_WORKSPACE},
    )
    await s.commit()


async def _connection(s: AsyncSession, workspace_id: str) -> uuid.UUID:
    connection_id = uuid.uuid4()
    with workspace_scope(workspace_id):
        conn = OpenAPIConnection(
            id=connection_id,
            name="Metrica",
            base_url="https://api-metrika.yandex.net",
            workspace_id=workspace_id,
            created_by="user-1",
        )
        s.add(conn)
        await s.commit()
    return connection_id


async def _row(s: AsyncSession, connection_id: uuid.UUID):
    s.expire_all()
    result = await s.execute(
        text("SELECT last_dispatch, updated_at FROM openapi_connections WHERE id = :id"),
        {"id": connection_id},
    )
    return result.one()


@pytest.mark.asyncio
async def test_a_call_is_recorded_without_touching_updated_at(session) -> None:
    conn_id = await _connection(session, WORKSPACE)
    before = (await _row(session, conn_id)).updated_at
    repo = OpenAPIConnectionRepository(
        session, UserContext(user_id="user-1", workspace_id=WORKSPACE)
    )

    with workspace_scope(WORKSPACE):
        await repo.record_dispatch(conn_id, DISPATCH)
        await session.commit()

    row = await _row(session, conn_id)
    assert row.last_dispatch == DISPATCH
    assert row.updated_at == before


@pytest.mark.asyncio
async def test_a_call_from_another_workspace_records_nothing(session) -> None:
    conn_id = await _connection(session, OTHER_WORKSPACE)
    repo = OpenAPIConnectionRepository(
        session, UserContext(user_id="user-1", workspace_id=WORKSPACE)
    )

    with workspace_scope(WORKSPACE):
        await repo.record_dispatch(conn_id, DISPATCH)
        await session.commit()

    assert (await _row(session, conn_id)).last_dispatch is None


@pytest.mark.asyncio
async def test_the_callers_own_work_still_commits_after_the_stamp(session) -> None:
    conn_id = await _connection(session, WORKSPACE)
    repo = OpenAPIConnectionRepository(
        session, UserContext(user_id="user-1", workspace_id=WORKSPACE)
    )

    with workspace_scope(WORKSPACE):
        loaded = (
            await session.execute(select(OpenAPIConnection).where(OpenAPIConnection.id == conn_id))
        ).scalar_one()
        loaded.description = "edited in the same transaction"
        await repo.record_dispatch(conn_id, DISPATCH)
        await session.commit()

    row = await session.execute(
        text("SELECT description, last_dispatch FROM openapi_connections WHERE id = :id"),
        {"id": conn_id},
    )
    description, last_dispatch = row.one()
    assert description == "edited in the same transaction"
    assert last_dispatch == DISPATCH
