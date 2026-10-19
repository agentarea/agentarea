"""Catalog skills and agents of a workspace registry reach that workspace only.

ADR-0044: a workspace admin's registry shares ``registry_items`` with the
platform catalog. The skill and agent projections read it with raw SQL, so each
of their reads has to keep another workspace's items out: not listed, not
found by id or key, and so not installable.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.catalog_agent_repository import CatalogAgentRepository
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


async def _item(session, registry_type: str, name: str, workspace_id: str | None) -> str:
    registry_id, item_id = str(uuid4()), str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, scope, workspace_id, mode, trust, created_at, updated_at) "
            "VALUES (:id, :name, :rt, 'url', 'x', true, :scope, :ws, :mode, :trust, now(), now())"
        ),
        {
            "id": registry_id,
            "name": f"test-{registry_id}",
            "rt": registry_type,
            "scope": "workspace" if workspace_id else "platform",
            "ws": workspace_id,
            "mode": "upstream" if workspace_id else "mirror",
            "trust": "private" if workspace_id else "official",
        },
    )
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "version, spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, registry_workspace_id, registry_trust, created_at, updated_at) "
            "SELECT :id, r.id, :name, :name, 'probe', '1', '{}', '[\"preset\"]', :name, false, "
            "r.registry_type, r.recommendation_priority, r.is_active, r.workspace_id, r.trust, "
            "now(), now() FROM registries r WHERE r.id = :registry_id"
        ),
        {"id": item_id, "registry_id": registry_id, "name": name},
    )
    return item_id


@pytest.fixture
def marker() -> str:
    return f"probe{uuid4().hex[:10]}"


@pytest.fixture
def acme() -> UserContext:
    return UserContext(user_id="u", workspace_id=f"ws-acme-{uuid4()}")


@pytest.fixture
def globex() -> UserContext:
    return UserContext(user_id="u", workspace_id=f"ws-globex-{uuid4()}")


async def test_skills_of_another_workspaces_registry_are_invisible(session, marker, acme, globex):
    await _item(session, "skills", f"{marker}-platform", None)
    own = await _item(session, "skills", f"{marker}-acme", acme.workspace_id)
    other = await _item(session, "skills", f"{marker}-globex", globex.workspace_id)
    repo = CatalogSkillRepository(session, acme)

    rows, total = await repo.list_page(limit=10, offset=0, exclude_item_ids=[], search=marker)
    listed = {i.name for i in await repo.list_items()}

    assert total == 2
    assert {r.name for r in rows} == {f"{marker}-platform", f"{marker}-acme"}
    assert f"{marker}-globex" not in listed
    assert await repo.get_item(other) is None
    assert await repo.find_by_key(f"{marker}-globex") is None
    assert await repo.versions_for([other]) == {}
    assert await repo.get_item(own) is not None
    assert await CatalogSkillRepository(session, globex).get_item(other) is not None


async def test_agents_of_another_workspaces_registry_are_invisible(session, marker, acme, globex):
    await _item(session, "agents", f"{marker}-platform", None)
    other = await _item(session, "agents", f"{marker}-globex", globex.workspace_id)
    repo = CatalogAgentRepository(session, acme)

    names = {i.name for i in await repo.list_items()}
    presets = {i.name for i in await repo.list_presets()}

    assert f"{marker}-platform" in names and f"{marker}-platform" in presets
    assert f"{marker}-globex" not in names | presets
    assert await repo.get_item(other) is None
    assert await CatalogAgentRepository(session, globex).get_item(other) is not None
