"""Egress exits against the real migrated schema.

Which exits a workspace sees and may change, and which instances leave through
one, are decided by the SQL the tenant scope and the repository emit; a mocked
session cannot see either.

Set MCP_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import agentarea_mcp.domain.auth_models  # noqa: F401  (mcp_server_instances.auth_config_id)
import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_mcp.infrastructure.egress_exit_repository import EgressExitRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("MCP_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="MCP_TEST_DATABASE_URL not set")

TENANT = "egress-exit-tenant"
OTHER = "egress-exit-other"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.execute(text("DELETE FROM mcp_server_instances WHERE name LIKE 'egress-proof-%'"))
        await s.execute(text("DELETE FROM egress_exits WHERE name LIKE 'egress-proof-%'"))
        await s.commit()
    await engine.dispose()


async def _exit(
    s: AsyncSession,
    workspace_id: str,
    *,
    managed_by: str | None = None,
    upstream_url: str | None = "https://proxy.example.com:443",
    via: str | None = None,
) -> uuid.UUID:
    exit_id = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO egress_exits (id, name, workspace_id, created_by, upstream_url, via, "
            "managed_by, created_at, updated_at) VALUES "
            "(:id, :name, :ws, 'operator', :upstream, :via, :mb, now(), now())"
        ),
        {
            "id": exit_id,
            "name": f"egress-proof-{exit_id}",
            "ws": workspace_id,
            "upstream": upstream_url,
            "via": via,
            "mb": managed_by,
        },
    )
    await s.commit()
    return exit_id


async def _instance(s: AsyncSession, workspace_id: str, json_spec: str) -> uuid.UUID:
    instance_id = uuid.uuid4()
    await s.execute(
        text(
            "INSERT INTO mcp_server_instances (id, name, server_spec_id, transport, json_spec, "
            "verification, network_scope, workspace_id, created_by, created_at, updated_at) "
            "VALUES (:id, :name, 'spec', 'docker', CAST(:spec AS jsonb), '{}', 'private', :ws, "
            "'member', now(), now())"
        ),
        {"id": instance_id, "name": f"egress-proof-{instance_id}", "spec": json_spec, "ws": workspace_id},
    )
    await s.commit()
    return instance_id


def _repo(s: AsyncSession, workspace_id: str = TENANT) -> EgressExitRepository:
    return EgressExitRepository(s, UserContext(user_id="member", workspace_id=workspace_id))


async def test_a_workspace_sees_its_own_exits_and_the_platforms_and_no_others(session):
    own = await _exit(session, TENANT)
    platform = await _exit(
        session, PLATFORM_WORKSPACE_ID, managed_by="platform", upstream_url=None, via="aeza"
    )
    foreign = await _exit(session, OTHER)

    with workspace_scope(TENANT):
        listed = {e.id for e in await _repo(session).list_all()}
        hidden = await _repo(session).get_by_id(foreign)

    assert own in listed and platform in listed and foreign not in listed
    assert hidden is None


async def test_no_tenant_edits_or_deletes_a_platform_exit(session):
    platform = await _exit(
        session, PLATFORM_WORKSPACE_ID, managed_by="platform", upstream_url=None, via="aeza"
    )

    with workspace_scope(TENANT):
        updated = await _repo(session).update(platform, upstream_url="http://attacker:3128")
        deleted = await _repo(session).delete(platform)

    row = (
        await session.execute(
            text("SELECT upstream_url FROM egress_exits WHERE id = :id"), {"id": platform}
        )
    ).one()
    assert updated is None and deleted is False
    assert row.upstream_url is None


async def test_the_instances_bound_to_an_exit_are_the_workspaces_own(session):
    exit_id = await _exit(session, TENANT)
    bound = await _instance(session, TENANT, f'{{"egress_exit": "{exit_id}"}}')
    await _instance(session, TENANT, "{}")
    await _instance(session, OTHER, f'{{"egress_exit": "{exit_id}"}}')

    with workspace_scope(TENANT):
        instances = await _repo(session).bound_instances(exit_id)

    assert [i.id for i in instances] == [bound]


async def test_only_a_platform_exit_may_leave_without_an_upstream(session):
    with pytest.raises(IntegrityError, match="ck_egress_exits_route"):
        await _exit(session, TENANT, upstream_url=None, via="aeza")
    await session.rollback()
