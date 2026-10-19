"""A workspace's registry is seen by that workspace only, on the migrated schema.

ADR-0044 lets a workspace admin add a registry. Its items share
``registry_items`` with the platform catalog, so every catalog read has to keep
another workspace's private items out, and the schema has to keep a workspace
registry from holding a type whose sync writes platform-wide entities.
"""

import importlib.util
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="CATALOG_TEST_DATABASE_URL not set; skipping schema-backed catalog visibility tests",
)

PREFIX = "visibility-test-"
ACME = UserContext(user_id="u-acme", workspace_id="visibility-test-acme")
GLOBEX = UserContext(user_id="u-globex", workspace_id="visibility-test-globex")
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "apps/api/alembic/versions/20261019_1500_registry_scope_mode_trust.py"
)


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


async def _registry(session: AsyncSession, name: str, owner: UserContext | None) -> Registry:
    registry = Registry(
        name=f"{PREFIX}{name}",
        registry_type="skills",
        source_type="url",
        source_url=f"https://example.test/{name}.json",
        scope="workspace" if owner else "platform",
        workspace_id=owner.workspace_id if owner else None,
        mode="upstream" if owner else "mirror",
        trust="private" if owner else "official",
    )
    session.add(registry)
    await session.commit()
    await RegistryItemRepository(session).create(
        registry_id=registry.id,
        external_id=f"{name}-skill",
        name=f"{PREFIX}{name}-skill",
        description="visibility probe",
    )
    return registry


@pytest.fixture
async def catalog(session: AsyncSession) -> dict[str, Registry]:
    return {
        "platform": await _registry(session, "platform", None),
        "acme": await _registry(session, "acme", ACME),
        "globex": await _registry(session, "globex", GLOBEX),
    }


def _names(items) -> set[str]:
    return {i.name.removeprefix(PREFIX) for i in items}


async def test_browse_and_search_show_the_platform_and_the_callers_own(session, catalog):
    for caller, own in ((ACME, "acme"), (GLOBEX, "globex")):
        repo = RegistryItemRepository(session, caller)
        page, total = await repo.browse("skills", q=PREFIX, limit=50)
        found = await repo.search(query_str=PREFIX)

        assert _names(page) == {"platform-skill", f"{own}-skill"}
        assert total == 2
        assert _names(found) == {"platform-skill", f"{own}-skill"}


async def test_another_workspaces_item_and_registry_are_not_found(session, catalog):
    globex_item = (await RegistryItemRepository(session).list_by_registry(catalog["globex"].id))[0]

    assert await RegistryItemRepository(session, ACME).get_visible(globex_item.id) is None
    assert await RegistryItemRepository(session, GLOBEX).get_visible(globex_item.id) is not None
    assert await RegistryRepository(session, ACME).get_visible(catalog["globex"].id) is None
    listed = {r.name for r in await RegistryRepository(session, ACME).list_visible()}
    assert f"{PREFIX}globex" not in listed
    assert {f"{PREFIX}platform", f"{PREFIX}acme"} <= listed


async def test_items_carry_their_registrys_workspace_and_trust(session, catalog):
    (item,) = await RegistryItemRepository(session).list_by_registry(catalog["acme"].id)
    assert (item.registry_workspace_id, item.registry_trust) == (ACME.workspace_id, "private")

    await RegistryRepository(session).update(catalog["acme"].id, trust="community")
    await session.refresh(item)
    assert item.registry_trust == "community"


async def test_a_catalog_read_without_a_caller_is_refused(session, catalog):
    with pytest.raises(ValueError, match="workspace"):
        await RegistryItemRepository(session).browse("skills")


async def test_a_workspace_registry_cannot_hold_types_that_write_platform_entities(session):
    session.add(
        Registry(
            name=f"{PREFIX}mcp",
            registry_type="mcp_servers",
            source_type="url",
            source_url="https://example.test/mcp.json",
            scope="workspace",
            workspace_id=ACME.workspace_id,
        )
    )
    with pytest.raises(IntegrityError, match="ck_registries_scope_workspace"):
        await session.commit()


async def test_a_platform_registry_names_no_workspace(session):
    session.add(
        Registry(
            name=f"{PREFIX}stray",
            registry_type="skills",
            source_type="url",
            source_url="https://example.test/stray.json",
            workspace_id=ACME.workspace_id,
        )
    )
    with pytest.raises(IntegrityError, match="ck_registries_scope_workspace"):
        await session.commit()


async def test_names_are_unique_per_scope(session, catalog):
    # The same name in another workspace, or beside the platform's, is fine.
    await _registry(session, "acme-shared", ACME)
    session.add(
        Registry(
            name=f"{PREFIX}acme-shared",
            registry_type="skills",
            source_type="url",
            source_url="https://example.test/x.json",
            scope="workspace",
            workspace_id=GLOBEX.workspace_id,
            mode="upstream",
            trust="private",
        )
    )
    await session.commit()

    session.add(
        Registry(
            name=f"{PREFIX}acme-shared",
            registry_type="skills",
            source_type="url",
            source_url="https://example.test/y.json",
            scope="workspace",
            workspace_id=ACME.workspace_id,
            mode="upstream",
            trust="private",
        )
    )
    with pytest.raises(IntegrityError, match="uq_registries_workspace_name"):
        await session.commit()


def _migration():
    spec = importlib.util.spec_from_file_location("registry_scope", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_backfill_labels_the_community_shards(session):
    migration = _migration()
    for name in ("system-skills-community-07", "system-skills-curated"):
        await session.execute(
            text(
                "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
                "is_active, sync_mode, item_count, recommendation_priority, created_at, "
                "updated_at) VALUES (gen_random_uuid(), :name, 'skills', 'url', 'x', true, "
                "'manual', 0, 100, now(), now())"
            ),
            {"name": name},
        )
        await session.execute(
            text(
                "INSERT INTO registry_items (id, registry_id, external_id, name, spec, tags, "
                "update_available, sort_key, featured, recommendation_rank, registry_type, "
                "registry_priority, registry_active, created_at, updated_at) "
                "SELECT gen_random_uuid(), r.id, 'probe', 'probe', '{}', '[]', false, 'probe', "
                "false, 0, 'skills', 100, true, now(), now() FROM registries r WHERE r.name = :name"
            ),
            {"name": name},
        )
    # The backfill matches production names, so these rows never commit.
    try:
        await session.execute(text(migration.BACKFILL_REGISTRIES))
        await session.execute(text(migration.BACKFILL_ITEM_TRUST))
        rows = (
            await session.execute(
                text(
                    "SELECT r.name, r.scope, r.mode, r.trust, ri.registry_trust "
                    "FROM registries r JOIN registry_items ri ON ri.registry_id = r.id "
                    "WHERE r.name IN ('system-skills-community-07', 'system-skills-curated')"
                )
            )
        ).all()
    finally:
        await session.rollback()

    assert {tuple(r) for r in rows} == {
        ("system-skills-community-07", "platform", "upstream", "community", "community"),
        ("system-skills-curated", "platform", "mirror", "official", "official"),
    }


async def test_a_secret_a_registry_reads_with_cannot_be_deleted(session):
    secret_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, "
            "created_by, created_at, updated_at) VALUES (:id, :ws, :name, 'x', 'u', now(), now())"
        ),
        {"id": secret_id, "ws": ACME.workspace_id, "name": f"{PREFIX}token-{secret_id.hex[:8]}"},
    )
    session.add(
        Registry(
            name=f"{PREFIX}private-repo",
            registry_type="skills",
            source_type="github",
            source_url="acme/private-skills",
            scope="workspace",
            workspace_id=ACME.workspace_id,
            mode="upstream",
            trust="private",
            credentials_secret_ref=secret_id,
        )
    )
    await session.commit()
    try:
        with pytest.raises(IntegrityError, match="credentials_secret_ref"):
            await session.execute(
                text("DELETE FROM encrypted_secrets WHERE id = :id"), {"id": secret_id}
            )
        await session.rollback()
    finally:
        await session.execute(
            text("DELETE FROM registries WHERE credentials_secret_ref = :id"), {"id": secret_id}
        )
        await session.execute(
            text("DELETE FROM encrypted_secrets WHERE id = :id"), {"id": secret_id}
        )
        await session.commit()
