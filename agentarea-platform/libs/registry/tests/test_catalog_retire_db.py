"""A source that stops publishing an item removes it, unless something uses it.

Every reconcile used to keep what the source dropped forever: in production 217k
of 220k skill rows were items no source published any more, 1.2 GB of the 2.7 GB
database. Only an item a workspace installed, forked or connected to has to
stay. "Uses it" spans tables of other modules, so this runs on the migrated
schema.
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
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
        for table in (
            "skills",
            "agents",
            "openapi_connections",
            "registry_item_installs",
            "mcp_server_instances",
            "mcp_servers",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE workspace_id LIKE :w"), {"w": f"{WORKSPACE}%"}
            )
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
        {
            "id": uuid.uuid4(),
            "w": WORKSPACE,
            "slug": f"forked-{uuid.uuid4().hex[:8]}",
            "item": ids["forked"],
        },
    )
    await session.execute(
        text(
            "INSERT INTO agents (id, workspace_id, created_by, name, slug, status, registry_item_id) "
            "VALUES (:id, :w, 'u', 'agent', :slug, 'active', :item)"
        ),
        {
            "id": uuid.uuid4(),
            "w": WORKSPACE,
            "slug": f"agent-{uuid.uuid4().hex[:8]}",
            "item": str(ids["agent"]),
        },
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
        (
            await session.execute(
                text("SELECT external_id FROM registry_items WHERE registry_id = :r ORDER BY 1"),
                {"r": reg.id},
            )
        )
        .scalars()
        .all()
    )
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
    # Production runs AGENTAREA_DB_TENANT_SCOPE=enforce and every sync binds a workspace.
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
        {
            "id": uuid.uuid4(),
            "w": WORKSPACE,
            "slug": f"forked-{uuid.uuid4().hex[:8]}",
            "item": forked.id,
        },
    )
    await session.commit()

    with workspace_scope(PLATFORM_WORKSPACE_ID):
        scoped = RegistryItemRepository(enforced)
        assert await scoped.mark_in_source(reg.id, set()) == 2
        assert await scoped.delete_unreferenced_out_of_source(reg.id) == 1

    left = (
        (
            await session.execute(
                text("SELECT external_id FROM registry_items WHERE registry_id = :r"), {"r": reg.id}
            )
        )
        .scalars()
        .all()
    )
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


async def test_retiring_a_registry_moves_its_uses_onto_the_replacements_items(
    session: AsyncSession,
):
    # The community shards are folded into one registry that publishes the same
    # ids. Installs, forks and agents move to its item before the shard's go,
    # except where a workspace already holds the replacement item.
    repo = RegistryItemRepository(session)
    shard = Registry(
        name=f"{PREFIX}shard", registry_type="skills", source_type="url", source_url="x"
    )
    folded = Registry(
        name=f"{PREFIX}folded", registry_type="skills", source_type="url", source_url="y"
    )
    session.add_all([shard, folded])
    await session.commit()
    old = await repo.create(registry_id=shard.id, external_id="pdf", name="pdf")
    clash = await repo.create(registry_id=shard.id, external_id="docx", name="docx")
    lonely = await repo.create(registry_id=shard.id, external_id="gone", name="gone")
    new = await repo.create(registry_id=folded.id, external_id="pdf", name="pdf")
    new_clash = await repo.create(registry_id=folded.id, external_id="docx", name="docx")
    other_ws = f"{WORKSPACE}-b"
    skill = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO skills (id, workspace_id, created_by, name, slug, registry_item_id) "
            "VALUES (:id, :w, 'u', 'pdf', :slug, :item)"
        ),
        {"id": skill, "w": WORKSPACE, "slug": f"pdf-{uuid.uuid4().hex[:8]}", "item": old.id},
    )
    await session.execute(
        text(
            "INSERT INTO agents (id, workspace_id, created_by, name, slug, status, registry_item_id) "
            "VALUES (:id, :w, 'u', 'a', :slug, 'active', :item)"
        ),
        {
            "id": uuid.uuid4(),
            "w": WORKSPACE,
            "slug": f"a-{uuid.uuid4().hex[:8]}",
            "item": str(lonely.id),
        },
    )
    for workspace, item in ((WORKSPACE, old.id), (other_ws, clash.id), (other_ws, new_clash.id)):
        await session.execute(
            text(
                "INSERT INTO registry_item_installs (id, workspace_id, registry_item_id, installed_entity_id) "
                "VALUES (:id, :w, :item, :entity)"
            ),
            {"id": uuid.uuid4(), "w": workspace, "item": item, "entity": uuid.uuid4()},
        )
    await session.commit()
    service = RegistryService(RegistryRepository(session), repo, server_repo=None)  # type: ignore[arg-type]

    await service.retire_registry(shard.id, replacements=[folded.id])

    left = await session.execute(
        text("SELECT external_id FROM registry_items WHERE registry_id = :r ORDER BY 1"),
        {"r": shard.id},
    )
    assert left.scalars().all() == ["docx", "gone"]
    moved = await session.execute(
        text("SELECT registry_item_id FROM skills WHERE id = :id"), {"id": skill}
    )
    assert moved.scalar_one() == new.id
    installs = await session.execute(
        text(
            "SELECT workspace_id, registry_item_id FROM registry_item_installs "
            "WHERE workspace_id IN (:a, :b) ORDER BY 1, 2"
        ),
        {"a": WORKSPACE, "b": other_ws},
    )
    assert sorted(installs.tuples().all()) == sorted(
        [(WORKSPACE, new.id), (other_ws, clash.id), (other_ws, new_clash.id)]
    )


async def test_an_item_another_platform_registry_now_publishes_takes_its_uses_along(
    session: AsyncSession, monkeypatch
):
    # A regional entry leaves the global catalog for its region's file: the same
    # id, published by a second registry. What a workspace connected moves with it,
    # and the global copy, now unused, goes.
    payloads = {
        "global": {"bundles": [{"name": n, "schema_version": "0.1.0"} for n in ("moved", "kept")]},
        "region": {"bundles": []},
    }
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda url: payloads[url]))
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))
    glob = Registry(name=f"{PREFIX}global", registry_type="bundles", source_type="url", source_url="global")
    region = Registry(name=f"{PREFIX}region", registry_type="bundles", source_type="url", source_url="region")
    session.add_all([glob, region])
    await session.commit()
    repo = RegistryItemRepository(session)
    service = RegistryService(RegistryRepository(session), repo, server_repo=None)  # type: ignore[arg-type]
    await service.sync_registry(glob.id)
    old = (
        await session.execute(
            text("SELECT id FROM registry_items WHERE registry_id = :r AND external_id = 'moved'"),
            {"r": glob.id},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO registry_item_installs (id, workspace_id, registry_item_id, installed_entity_id) "
            "VALUES (:id, :w, :item, :entity)"
        ),
        {"id": uuid.uuid4(), "w": WORKSPACE, "item": old, "entity": uuid.uuid4()},
    )
    await session.commit()

    payloads["global"] = {"bundles": [{"name": "kept", "schema_version": "0.1.0"}]}
    payloads["region"] = {"bundles": [{"name": "moved", "schema_version": "0.1.0"}]}
    await service.sync_registry(region.id)
    await service.sync_registry(glob.id)

    new = (
        await session.execute(
            text("SELECT id FROM registry_items WHERE registry_id = :r AND external_id = 'moved'"),
            {"r": region.id},
        )
    ).scalar_one()
    install = await session.execute(
        text("SELECT registry_item_id FROM registry_item_installs WHERE workspace_id = :w"),
        {"w": WORKSPACE},
    )
    assert install.scalars().all() == [new]
    left = await session.execute(
        text("SELECT external_id FROM registry_items WHERE registry_id = :r"), {"r": glob.id}
    )
    assert left.scalars().all() == ["kept"]


async def _mcp_copy(session: AsyncSession, item_id: uuid.UUID, workspace: str = WORKSPACE) -> uuid.UUID:
    server = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO mcp_servers (id, workspace_id, created_by, name, slug, description, "
            "version, tags, is_public, status, registry_item_id) VALUES (:id, :w, 'u', 'srv', "
            ":slug, '', '1', '[]', false, 'active', :item)"
        ),
        {"id": server, "w": workspace, "slug": f"srv-{server.hex[:8]}", "item": item_id},
    )
    return server


async def test_a_moved_mcp_server_keeps_one_platform_copy_and_its_instances_follow(
    session: AsyncSession,
):
    # Both registries mirror the server: each item has the platform's own copy.
    # The dropped item's copy must not move onto the new item (two copies of one
    # server); its instances move to the new copy and the old copy goes.
    repo = RegistryItemRepository(session)
    glob = Registry(
        name=f"{PREFIX}mcp-global", registry_type="mcp_servers", source_type="url", source_url="g"
    )
    region = Registry(
        name=f"{PREFIX}mcp-region", registry_type="mcp_servers", source_type="url", source_url="r"
    )
    session.add_all([glob, region])
    await session.commit()
    old = await repo.create(registry_id=glob.id, external_id="srv", name="srv")
    still = await repo.create(registry_id=glob.id, external_id="both", name="both")
    new = await repo.create(registry_id=region.id, external_id="srv", name="srv")
    await repo.create(registry_id=region.id, external_id="both", name="both")
    old_copy = await _mcp_copy(session, old.id)
    new_copy = await _mcp_copy(session, new.id)
    still_copy = await _mcp_copy(session, still.id)
    user_server = await _mcp_copy(session, old.id, workspace=f"{WORKSPACE}-b")
    for item, copy in ((old, old_copy), (new, new_copy), (still, still_copy)):
        await repo.update(item.id, installed_entity_id=copy)
    instance = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO mcp_server_instances (id, name, server_spec_id, transport, workspace_id, "
            "created_by) VALUES (:id, 'i', :spec, 'docker', :w, 'u')"
        ),
        {"id": instance, "spec": str(old_copy), "w": WORKSPACE},
    )
    await session.commit()
    await repo.mark_in_source(glob.id, {"both"})

    deleted: list[str] = []

    class Servers:
        async def delete(self, server_id: str) -> bool:
            deleted.append(server_id)
            await session.execute(text("DELETE FROM mcp_servers WHERE id = :id"), {"id": server_id})
            return True

    service = RegistryService(RegistryRepository(session), repo, server_repo=Servers())  # type: ignore[arg-type]
    await service._move_uses(glob, [region.id])
    assert await repo.delete_unreferenced_out_of_source(glob.id) == 1

    assert deleted == [str(old_copy)]
    spec = await session.execute(
        text("SELECT server_spec_id FROM mcp_server_instances WHERE id = :id"), {"id": instance}
    )
    assert spec.scalar_one() == str(new_copy)
    owners = await session.execute(
        text("SELECT id, registry_item_id FROM mcp_servers WHERE id IN (:a, :b, :c)"),
        {"a": new_copy, "b": still_copy, "c": user_server},
    )
    assert dict(owners.tuples().all()) == {new_copy: new.id, still_copy: still.id, user_server: new.id}
    left = await session.execute(
        text("SELECT external_id FROM registry_items WHERE registry_id = :r"), {"r": glob.id}
    )
    assert left.scalars().all() == ["both"]
