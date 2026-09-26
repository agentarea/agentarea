"""The MCP spec list against the real migrated schema.

The list is tenant specs first, then read-only catalog projections. The catalog
holds tens of thousands of items, so both halves are filtered and paged in SQL;
the list used to project every catalog item per request (~2.6 s on RU prod).
Filtering by id resolves tenant rows and catalog items in the same SQL, which
is how a page that shows instances finds their specs.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")


@pytest.fixture
def marker() -> str:
    """A name fragment only this test's rows carry, so the shared catalog cannot leak in."""
    return f"probe{uuid4().hex[:10]}"


@pytest.fixture
def context() -> UserContext:
    return UserContext(user_id="user-a", workspace_id=f"ws-{uuid4()}")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


async def _registry(session, *, active: bool = True) -> str:
    registry_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'mcp_servers', 'managed', 'x', :active, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}", "active": active},
    )
    return registry_id


async def _catalog_item(session, registry_id: str, name: str, *, tags=("url",)) -> str:
    item_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, created_at, updated_at) "
            "SELECT :id, r.id, :external_id, :name, 'desc', CAST(:spec AS jsonb), "
            "CAST(:tags AS jsonb), :sort_key, false, r.registry_type, "
            "r.recommendation_priority, r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": item_id,
            "registry_id": registry_id,
            "external_id": f"{name}-{item_id}",
            "name": name,
            "sort_key": name.lower(),
            "spec": json.dumps({"connection_type": "url", "url": "https://x"}),
            "tags": json.dumps(list(tags)),
        },
    )
    return item_id


async def _tenant_spec(session, context, name: str, **fields) -> str:
    server = MCPServer(
        name=name,
        slug=f"{name}-{uuid4().hex[:6]}",
        description="tenant",
        status="active",
        workspace_id=context.workspace_id,
        created_by=context.user_id,
        **fields,
    )
    session.add(server)
    await session.flush()
    return str(server.id)


def _names(servers) -> list[str]:
    return [s.name for s in servers]


async def test_the_catalog_half_is_paged_in_sql(session, context, marker):
    registry = await _registry(session)
    for n in range(8):
        await _catalog_item(session, registry, f"{marker}-cat-{n}")
    await _tenant_spec(session, context, f"{marker}-mine")
    repo = MCPServerRepository(session, context)

    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context_, executemany):
        statements.append(statement)

    engine = session.bind.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first, total = await repo.list_servers(search=marker, limit=3, offset=0)
        second, _ = await repo.list_servers(search=marker, limit=3, offset=3)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert total == 9
    assert _names(first) == [f"{marker}-mine", f"{marker}-cat-0", f"{marker}-cat-1"]
    assert _names(second) == [f"{marker}-cat-2", f"{marker}-cat-3", f"{marker}-cat-4"]
    catalog_reads = [s for s in statements if "FROM registry_items" in s and "SELECT ri.id" in s]
    assert catalog_reads
    assert all("LIMIT" in s for s in catalog_reads)


async def test_ids_resolve_tenant_specs_and_catalog_items_alike(session, context, marker):
    registry = await _registry(session)
    wanted_item = await _catalog_item(session, registry, f"{marker}-wanted-item")
    await _catalog_item(session, registry, f"{marker}-other-item")
    wanted_spec = await _tenant_spec(session, context, f"{marker}-wanted-spec")
    await _tenant_spec(session, context, f"{marker}-other-spec")

    servers, total = await MCPServerRepository(session, context).list_servers(
        spec_ids={wanted_item, wanted_spec}, limit=100
    )

    assert total == 2
    assert {str(s.id) for s in servers} == {wanted_item, wanted_spec}
    assert [getattr(s, "is_catalog", False) for s in servers] == [False, True]


async def test_an_instantiated_catalog_item_is_shadowed_by_its_tenant_row(
    session, context, marker
):
    registry = await _registry(session)
    item = await _catalog_item(session, registry, f"{marker}-installed")
    await _catalog_item(session, registry, f"{marker}-available")
    await _tenant_spec(session, context, f"{marker}-my-install", registry_item_id=item)

    servers, total = await MCPServerRepository(session, context).list_servers(search=marker)

    assert total == 2
    assert _names(servers) == [f"{marker}-my-install", f"{marker}-available"]


async def test_filters_reach_the_catalog_half(session, context, marker):
    registry = await _registry(session)
    await _catalog_item(session, registry, f"{marker}-docker", tags=("docker",))
    await _catalog_item(session, registry, f"{marker}-url", tags=("url",))
    repo = MCPServerRepository(session, context)

    tagged, tagged_total = await repo.list_servers(search=marker, tag="docker")
    drafts, drafts_total = await repo.list_servers(search=marker, status="draft")
    public, public_total = await repo.list_servers(search=marker, is_public=True)

    assert (_names(tagged), tagged_total) == ([f"{marker}-docker"], 1)
    assert (drafts, drafts_total) == ([], 0)
    assert (public, public_total) == ([], 0)


async def test_an_inactive_registry_contributes_nothing(session, context, marker):
    await _catalog_item(session, await _registry(session, active=False), f"{marker}-hidden")

    servers, total = await MCPServerRepository(session, context).list_servers(search=marker)

    assert (servers, total) == ([], 0)


async def test_another_workspaces_spec_never_appears(session, context, marker):
    stranger = UserContext(user_id="user-b", workspace_id=f"ws-{uuid4()}")
    await _tenant_spec(session, stranger, f"{marker}-theirs")
    item = await _catalog_item(session, await _registry(session), f"{marker}-builtin")

    servers, total = await MCPServerRepository(session, context).list_servers(search=marker)

    assert total == 1
    assert [str(s.id) for s in servers] == [item]
