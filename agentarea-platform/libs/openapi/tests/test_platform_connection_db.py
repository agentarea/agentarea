"""A platform-managed OpenAPI connection, against a real schema.

The operator writes it in the platform workspace; every workspace reads and calls it,
none edits or deletes it. Both are decided by the SQL the ORM scope and the repository
emit, which a mocked session cannot see.

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
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("OPENAPI_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="OPENAPI_TEST_DATABASE_URL not set; skipping schema-backed OpenAPI tests",
)

TENANT = "openapi-platform-tenant"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.execute(text("DELETE FROM openapi_connections WHERE name LIKE 'platform-proof-%'"))
        await s.commit()
    await engine.dispose()


async def _insert(s: AsyncSession, workspace_id: str, managed_by: str | None) -> uuid.UUID:
    connection_id = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO openapi_connections (id, name, base_url, workspace_id, created_by, "
            "available_tools, status, managed_by, created_at, updated_at) VALUES "
            "(:id, :name, 'https://example.com', :ws, 'operator', '[]', 'active', :mb, now(), now())"
        ),
        {
            "id": connection_id,
            "name": f"platform-proof-{connection_id}",
            "ws": workspace_id,
            "mb": managed_by,
        },
    )
    await s.commit()
    return connection_id


def _repo(s: AsyncSession) -> OpenAPIConnectionRepository:
    return OpenAPIConnectionRepository(s, UserContext(user_id="member", workspace_id=TENANT))


async def test_every_workspace_reads_a_platform_connection_and_no_other_workspaces(session):
    platform = await _insert(session, PLATFORM_WORKSPACE_ID, "platform")
    foreign = await _insert(session, "openapi-platform-other", None)

    with workspace_scope(TENANT):
        listed, _ = await _repo(session).list_connections(limit=0)
        found = await _repo(session).get_by_id(str(platform))
        hidden = await _repo(session).get_by_id(str(foreign))

    assert platform in {c.id for c in listed} and foreign not in {c.id for c in listed}
    assert found is not None and found.managed_by == "platform"
    assert hidden is None


async def test_no_tenant_edits_or_deletes_a_platform_connection(session):
    platform = await _insert(session, PLATFORM_WORKSPACE_ID, "platform")

    with workspace_scope(TENANT):
        updated = await _repo(session).update(str(platform), name="hijacked")
        deleted = await _repo(session).delete(str(platform))
        await session.commit()

    row = (
        await session.execute(
            text("SELECT name FROM openapi_connections WHERE id = :id"), {"id": platform}
        )
    ).one()
    assert updated is None and deleted is False
    assert row.name.startswith("platform-proof-")
