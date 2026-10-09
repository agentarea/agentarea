"""Which of the workspace's connections came from a catalog item, against the real schema.

An MCP instance names its catalog item only through its spec, whose id is a
uuid while the instance stores it as text, so the join is the cast the migrated
schema decides. Set CATALOG_TEST_DATABASE_URL (``make check-db`` does).
"""

from __future__ import annotations

import os
from importlib import import_module
from uuid import uuid4

import pytest
from agentarea_api.repositories.catalog_connection_repository import CatalogConnectionRepository
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.transport import MCPTransport
from agentarea_openapi.domain.models import OpenAPIConnection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# The OpenAPI connection row references registry_items.
import_module("agentarea_registry.domain.models")

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")


async def catalog_connections(session, workspace_id, item_ids, readable):
    repository = CatalogConnectionRepository(
        session, UserContext(user_id="u", workspace_id=workspace_id)
    )
    return await repository.by_catalog_item(item_ids, readable)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


async def _catalog_item(session, registry_type: str = "mcp_servers") -> str:
    registry_id, item_id = str(uuid4()), str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, :type, 'managed', 'x', true, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}", "type": registry_type},
    )
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, created_at, updated_at) "
            "SELECT :id, r.id, :external_id, 'item', 'desc', CAST(:spec AS jsonb), "
            "CAST('[]' AS jsonb), 'item', false, r.registry_type, "
            "r.recommendation_priority, r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {"id": item_id, "external_id": item_id, "registry_id": registry_id, "spec": "{}"},
    )
    return item_id


async def _mcp_instance(session, workspace_id: str, name: str, item_id: str | None):
    spec = MCPServer(
        name=f"spec-{name}",
        slug=f"spec-{uuid4().hex[:8]}",
        description="",
        status="active",
        registry_item_id=item_id,
        workspace_id=workspace_id,
        created_by="u",
    )
    session.add(spec)
    await session.flush()
    instance = MCPServerInstance(
        name=name,
        server_spec_id=str(spec.id),
        transport=MCPTransport.URL,
        json_spec={"endpoint_url": "https://mcp.example"},
        workspace_id=workspace_id,
        created_by="u",
    )
    session.add(instance)
    await session.flush()
    return instance


async def _openapi(session, workspace_id: str, name: str, item_id: str | None):
    connection = OpenAPIConnection(
        name=name,
        base_url="https://api.example",
        registry_item_id=item_id,
        workspace_id=workspace_id,
        created_by="u",
    )
    session.add(connection)
    await session.flush()
    return connection


async def test_each_item_lists_its_mcp_and_openapi_connections(session):
    ws = f"ws-{uuid4()}"
    github, stripe, unused = (
        await _catalog_item(session),
        await _catalog_item(session),
        await _catalog_item(session),
    )
    with workspace_scope(ws):
        first = await _mcp_instance(session, ws, "GitHub", github)
        second = await _openapi(session, ws, "GitHub API", github)
        payments = await _openapi(session, ws, "Stripe", stripe)
        await _openapi(session, ws, "Manual", None)
        readable = {str(first.id), str(second.id), str(payments.id)}

        found = await catalog_connections(session, ws, [github, stripe, unused], readable)

    assert {key: [(c.kind, c.name) for c in value] for key, value in found.items()} == {
        github: [("mcp", "GitHub"), ("openapi", "GitHub API")],
        stripe: [("openapi", "Stripe")],
    }
    assert found[github][0].id == first.id


async def test_a_connection_the_graph_hides_is_not_counted(session):
    ws = f"ws-{uuid4()}"
    item = await _catalog_item(session)
    with workspace_scope(ws):
        mine = await _mcp_instance(session, ws, "Mine", item)
        await _mcp_instance(session, ws, "Theirs", item)

        found = await catalog_connections(session, ws, [item], {str(mine.id)})

    assert [c.name for c in found[item]] == ["Mine"]


async def test_another_workspace_connections_are_not_counted(session):
    ws, other = f"ws-{uuid4()}", f"ws-{uuid4()}"
    item = await _catalog_item(session)
    with workspace_scope(other):
        foreign = await _openapi(session, other, "Foreign", item)
    with workspace_scope(ws):
        found = await catalog_connections(session, ws, [item], {str(foreign.id)})

    assert found == {}


async def test_nothing_readable_reads_nothing(session):
    ws = f"ws-{uuid4()}"
    item = await _catalog_item(session)
    with workspace_scope(ws):
        await _openapi(session, ws, "Hidden", item)
        found = await catalog_connections(session, ws, [item], set())

    assert found == {}
