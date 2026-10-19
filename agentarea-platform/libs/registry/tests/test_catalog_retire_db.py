"""A source that stops publishing an item removes it, unless something uses it.

Every reconcile used to keep what the source dropped forever: on RU prod 217k
of 220k skill rows were items no source published any more, 1.2 GB of the 2.7 GB
database. Only an item a workspace installed, forked or connected to has to
stay. "Uses it" spans tables of other modules, so this runs on the migrated
schema.
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="CATALOG_TEST_DATABASE_URL not set; skipping schema-backed catalog retire tests",
)

PREFIX = "retire-test-"
WORKSPACE = "retire-test-ws"


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield eng
    async with eng.begin() as conn:
        for table in ("skills", "agents", "openapi_connections", "registry_item_installs"):
            await conn.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": WORKSPACE})
        await conn.execute(text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


async def test_only_unreferenced_items_the_source_dropped_are_deleted(session: AsyncSession):
    reg = Registry(
        name=f"{PREFIX}skills",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
    )
    session.add(reg)
    await session.commit()
    repo = RegistryItemRepository(session)
    ids = {}
    for name in ("kept", "gone", "installed", "forked", "agent", "connected", "mirrored"):
        item = await repo.create(registry_id=reg.id, external_id=name, name=name)
        ids[name] = item.id

    await session.execute(
        text(
            "INSERT INTO registry_item_installs (id, workspace_id, registry_item_id, installed_entity_id) "
            "VALUES (:id, :w, :item, :entity)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "item": ids["installed"], "entity": uuid.uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO skills (id, workspace_id, created_by, name, slug, registry_item_id) "
            "VALUES (:id, :w, 'u', 'forked', :slug, :item)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "slug": f"forked-{uuid.uuid4().hex[:8]}", "item": ids["forked"]},
    )
    await session.execute(
        text(
            "INSERT INTO agents (id, workspace_id, created_by, name, slug, status, registry_item_id) "
            "VALUES (:id, :w, 'u', 'agent', :slug, 'active', :item)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "slug": f"agent-{uuid.uuid4().hex[:8]}", "item": str(ids["agent"])},
    )
    await session.execute(
        text(
            "INSERT INTO openapi_connections (id, workspace_id, created_by, name, base_url, registry_item_id) "
            "VALUES (:id, :w, 'u', 'connected', 'https://api.example.test', :item)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "item": ids["connected"]},
    )
    await repo.update(ids["mirrored"], installed_entity_id=str(uuid.uuid4()))
    await session.commit()

    assert await repo.mark_in_source(reg.id, {"kept"}) == 6
    assert await repo.delete_unreferenced_out_of_source(reg.id) == 1

    left = (
        await session.execute(
            text("SELECT external_id, in_source FROM registry_items WHERE registry_id = :r"),
            {"r": reg.id},
        )
    ).all()
    assert dict(left) == {
        "kept": True,
        "installed": False,
        "forked": False,
        "agent": False,
        "connected": False,
        "mirrored": False,
    }
