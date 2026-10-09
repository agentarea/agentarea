"""An MCP instance's last call, written by the stamp writer against a real schema.

The writer runs with no workspace bound, under the ENFORCE tenant scope prod
uses, and must still stamp instances of any workspace without moving their
``updated_at`` -- a call is not an edit.

Needs a PostgreSQL migrated to head; skips without one:

    MCP_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/agentarea_test  # pragma: allowlist secret
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_mcp import dispatch_stamps
from agentarea_mcp.dispatch_stamps import DispatchStampWriter, record_dispatch
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.transport import MCPTransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("MCP_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="MCP_TEST_DATABASE_URL not set; skipping schema-backed MCP dispatch stamp tests",
)

WORKSPACES = ("mcp-dispatch-a", "mcp-dispatch-b")


@pytest.fixture
async def maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    await _cleanup(factory)
    yield factory
    await _cleanup(factory)
    await engine.dispose()


@pytest.fixture(autouse=True)
def pending(monkeypatch):
    monkeypatch.setattr(dispatch_stamps, "_pending", asyncio.Queue(maxsize=10))


async def _cleanup(factory) -> None:
    async with factory() as s:
        await s.execute(
            text("DELETE FROM mcp_server_instances WHERE workspace_id IN (:a, :b)"),
            {"a": WORKSPACES[0], "b": WORKSPACES[1]},
        )
        await s.commit()


async def _instance(factory, workspace_id: str) -> uuid.UUID:
    instance_id = uuid.uuid4()
    async with factory() as s:
        with workspace_scope(workspace_id):
            s.add(
                MCPServerInstance(
                    id=instance_id,
                    name="Google Analytics",
                    server_spec_id="ga",
                    transport=MCPTransport.URL,
                    json_spec={"endpoint_url": "https://mcp.example.com/mcp"},
                    workspace_id=workspace_id,
                    created_by="user-1",
                )
            )
            await s.commit()
    return instance_id


async def _row(factory, instance_id: uuid.UUID):
    async with factory() as s:
        result = await s.execute(
            text("SELECT last_dispatch, updated_at FROM mcp_server_instances WHERE id = :id"),
            {"id": instance_id},
        )
        return result.one()


@pytest.mark.asyncio
async def test_stamps_reach_instances_of_every_workspace_and_leave_updated_at(maker) -> None:
    first = await _instance(maker, WORKSPACES[0])
    second = await _instance(maker, WORKSPACES[1])
    before = (await _row(maker, first)).updated_at

    record_dispatch(first)
    record_dispatch(second, error="401 Unauthorized")
    await DispatchStampWriter(maker).flush()

    row = await _row(maker, first)
    assert row.last_dispatch["status"] == "succeeded"
    assert row.updated_at == before
    failed = (await _row(maker, second)).last_dispatch
    assert failed["status"] == "failed"
    assert failed["error"] == "401 Unauthorized"
