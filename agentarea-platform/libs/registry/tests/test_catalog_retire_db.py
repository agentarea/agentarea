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


async def _service(session: AsyncSession, monkeypatch, payload: dict):
    from agentarea_registry.application.service import RegistryService
    from agentarea_registry.infrastructure.repository import RegistryRepository

    reg = Registry(
        name=f"{PREFIX}bundles-{uuid.uuid4().hex[:6]}",
        registry_type="bundles",
        source_type="url",
        source_url="https://example.test/bundles.json",
    )
    session.add(reg)
    await session.commit()
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _url: payload))
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))
    service = RegistryService(
        RegistryRepository(session), RegistryItemRepository(session), server_repo=None
    )
    return service, reg


async def test_a_source_listing_an_item_twice_still_syncs(session: AsyncSession, monkeypatch):
    # The unique (registry_id, external_id) constraint exists only on the real
    # schema: the second copy of a new item used to try a second INSERT, and the
    # failed statement then took every later item and the sync down with it.
    payload = {"bundles": [{"name": n, "schema_version": "0.1.0"} for n in ("a", "a", "b")]}
    service, reg = await _service(session, monkeypatch, payload)

    stats = await service.sync_registry(reg.id)

    assert stats["skipped"] == 0
    names = (
        await session.execute(
            text("SELECT external_id FROM registry_items WHERE registry_id = :r ORDER BY 1"),
            {"r": reg.id},
        )
    ).scalars().all()
    assert names == ["a", "b"]


async def test_retiring_a_registry_deletes_what_nothing_uses(session: AsyncSession, monkeypatch):
    payload = {"bundles": [{"name": n, "schema_version": "0.1.0"} for n in ("used", "unused")]}
    service, reg = await _service(session, monkeypatch, payload)
    await service.sync_registry(reg.id)
    used = (
        await session.execute(
            text("SELECT id FROM registry_items WHERE registry_id = :r AND external_id = 'used'"),
            {"r": reg.id},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO registry_item_installs (id, workspace_id, registry_item_id, installed_entity_id) "
            "VALUES (:id, :w, :item, :entity)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "item": used, "entity": uuid.uuid4()},
    )
    await session.commit()

    assert await service.retire_registry(reg.id) == 1

    left = (
        await session.execute(
            text("SELECT external_id, registry_active FROM registry_items WHERE registry_id = :r"),
            {"r": reg.id},
        )
    ).all()
    assert dict(left) == {"used": False}


@pytest.fixture
async def enforced(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    from agentarea_common.base.tenant_scope import tenant_scoped_session_class
    from agentarea_common.config.database import TenantScopeMode

    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
    )
    async with maker() as s:
        yield s


async def test_the_reference_check_sees_every_workspace_under_an_enforced_scope(
    session: AsyncSession, enforced: AsyncSession
):
    # RU runs AGENTAREA_DB_TENANT_SCOPE=enforce and every sync binds a workspace.
    # The DELETE names other modules' scoped tables; it must run, and it must
    # still see a fork made in a workspace other than the one bound.
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.constants import PLATFORM_WORKSPACE_ID

    reg = Registry(
        name=f"{PREFIX}enforced",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
    )
    session.add(reg)
    await session.commit()
    repo = RegistryItemRepository(session)
    forked = await repo.create(registry_id=reg.id, external_id="forked", name="forked")
    await repo.create(registry_id=reg.id, external_id="gone", name="gone")
    await session.execute(
        text(
            "INSERT INTO skills (id, workspace_id, created_by, name, slug, registry_item_id) "
            "VALUES (:id, :w, 'u', 'forked', :slug, :item)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "slug": f"forked-{uuid.uuid4().hex[:8]}", "item": forked.id},
    )
    await session.commit()

    with workspace_scope(PLATFORM_WORKSPACE_ID):
        scoped = RegistryItemRepository(enforced)
        assert await scoped.mark_in_source(reg.id, set()) == 2
        assert await scoped.delete_unreferenced_out_of_source(reg.id) == 1

    left = (
        await session.execute(
            text("SELECT external_id FROM registry_items WHERE registry_id = :r"), {"r": reg.id}
        )
    ).scalars().all()
    assert left == ["forked"]


async def test_an_item_an_install_keeps_takes_its_registrys_trust(session: AsyncSession):
    # The migration labels only what the source still publishes; a dropped item
    # an install keeps is relabelled by the cleanup, once the rest is gone.
    reg = Registry(
        name=f"{PREFIX}relabel",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
        trust="community",
    )
    session.add(reg)
    await session.commit()
    repo = RegistryItemRepository(session)
    kept = await repo.create(registry_id=reg.id, external_id="kept", name="kept")
    await session.execute(
        text("UPDATE registry_items SET registry_trust = 'official' WHERE id = :id"),
        {"id": kept.id},
    )
    await session.execute(
        text(
            "INSERT INTO registry_item_installs (id, workspace_id, registry_item_id, installed_entity_id) "
            "VALUES (:id, :w, :item, :entity)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "item": kept.id, "entity": uuid.uuid4()},
    )
    await session.commit()

    await repo.mark_in_source(reg.id, set())
    await repo.delete_unreferenced_out_of_source(reg.id)

    trust = (
        await session.execute(
            text("SELECT registry_trust FROM registry_items WHERE id = :id"), {"id": kept.id}
        )
    ).scalar_one()
    assert trust == "community"
