"""Preset lookups run against the real migrated catalog schema.

Presets are catalog agents tagged ``preset`` (a jsonb containment query), and
they name catalog skills by a key that the published names extend with a
content hash. Both are raw SQL a mock cannot check.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.catalog_agent_repository import CatalogAgentRepository
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")

CONTEXT = UserContext(user_id="user-a", workspace_id=f"ws-{uuid4()}")
EARLIER = datetime(2026, 9, 1, 12, 0)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


async def _registry(session, registry_type: str) -> str:
    registry_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, :type, 'managed', :url, true, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}", "type": registry_type, "url": "x"},
    )
    return registry_id


async def _item(session, registry_id, name, *, tags=(), spec=None, updated_at=None) -> str:
    item_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, spec, tags, "
            "sort_key, featured, registry_type, registry_priority, registry_active, "
            "created_at, updated_at) "
            "SELECT :id, r.id, :external_id, :name, CAST(:spec AS jsonb), "
            "CAST(:tags AS jsonb), :name, false, r.registry_type, "
            "r.recommendation_priority, r.is_active, now(), :updated_at "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": item_id,
            "registry_id": registry_id,
            "external_id": f"{name}-{item_id}",
            "name": name,
            "spec": json.dumps(spec or {}),
            "tags": json.dumps(list(tags)),
            "updated_at": updated_at or datetime(2026, 9, 20, 12, 0),
        },
    )
    return item_id


async def test_only_agents_tagged_preset_are_presets(session):
    agents = await _registry(session, "agents")
    preset = await _item(session, agents, "Claw", tags=["preset", "assistant"])
    await _item(session, agents, "Plain", tags=["assistant"])

    presets = await CatalogAgentRepository(session, CONTEXT).list_presets()

    assert preset in [p.id for p in presets]
    assert "Plain" not in [p.name for p in presets]


async def test_a_skill_key_finds_the_newest_published_version(session):
    skills = await _registry(session, "skills")
    key = f"brainstorming--src{uuid4().hex[:6]}"
    await _item(session, skills, f"{key}--aaaaaaaaaa", updated_at=EARLIER)
    newest = await _item(session, skills, f"{key}--bbbbbbbbbb", updated_at=EARLIER + timedelta(days=3))

    found = await CatalogSkillRepository(session, CONTEXT).find_by_key(key)

    assert found is not None
    assert found.id == newest


async def test_a_skill_key_does_not_match_a_longer_skill_name(session):
    skills = await _registry(session, "skills")
    key = f"plan--src{uuid4().hex[:6]}"
    await _item(session, skills, f"{key}-extended--cccccccccc")

    assert await CatalogSkillRepository(session, CONTEXT).find_by_key(key) is None


async def test_an_unhashed_skill_name_is_its_own_key(session):
    skills = await _registry(session, "skills")
    key = f"deep-research-{uuid4().hex[:6]}"
    item = await _item(session, skills, key)

    found = await CatalogSkillRepository(session, CONTEXT).find_by_key(key)

    assert found is not None
    assert found.id == item
