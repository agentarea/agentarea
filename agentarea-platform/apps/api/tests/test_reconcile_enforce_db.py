"""The reconcile runs under the enforced tenant scope RU deploys with.

``AGENTAREA_DB_TENANT_SCOPE=enforce`` refuses any statement on a workspace-scoped
table the bound scope cannot confine. Every reconcile binds a workspace, and
what a sync deletes is checked against every workspace's installs and forks, so
the whole run -- a platform source synced, a retired one emptied, a workspace's
own registry synced -- goes through sessions in that mode here, on the migrated
schema.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from agentarea_api import cli
from agentarea_common.base.tenant_scope import tenant_scoped_session_class
from agentarea_common.config.database import TenantScopeMode
from agentarea_registry.application.service import RegistryService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")

RUN = uuid.uuid4().hex[:8]
PREFIX = f"enforce-{RUN}-"
OWNER = f"{PREFIX}ws-a"
OTHER = f"{PREFIX}ws-b"
PLATFORM_URL = "https://platform.example/skills.json"
WORKSPACE_URL = "https://index.example/skills.json"


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    async with eng.begin() as conn:
        for table in ("skills", "registry_item_installs"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE workspace_id LIKE :p"),  # noqa: S608
                {"p": f"{PREFIX}%"},
            )
        await conn.execute(text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PREFIX}%"})
    await eng.dispose()


async def _registry(conn, name: str, **fields) -> uuid.UUID:
    registry_id = uuid.uuid4()
    values = {
        "registry_type": "skills",
        "source_type": "url",
        "source_url": PLATFORM_URL,
        "scope": "platform",
        "workspace_id": None,
        "mode": "upstream",
        "trust": "community",
        **fields,
    }
    await conn.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, scope, "
            "workspace_id, mode, trust, is_active, recommendation_priority, item_count) "
            "VALUES (:id, :name, :registry_type, :source_type, :source_url, :scope, "
            ":workspace_id, :mode, :trust, true, 100, 0)"
        ),
        {"id": registry_id, "name": name, **values},
    )
    return registry_id


async def _item(conn, registry_id: uuid.UUID, external_id: str, workspace_id=None) -> uuid.UUID:
    item_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, spec, tags, "
            "registry_type, registry_priority, registry_active, registry_workspace_id, "
            "registry_trust, in_source, featured, recommendation_rank, update_available, sort_key) "
            "VALUES (:id, :r, :e, :e, '{}', '[]', 'skills', 100, true, :w, 'community', true, "
            "false, 0, false, :e)"
        ),
        {"id": item_id, "r": registry_id, "e": external_id, "w": workspace_id},
    )
    return item_id


async def _external_ids(conn, registry_id: uuid.UUID) -> dict[str, bool]:
    rows = await conn.execute(
        text("SELECT external_id, registry_active FROM registry_items WHERE registry_id = :r"),
        {"r": registry_id},
    )
    return dict(rows.tuples().all())


async def test_platform_sync_retire_and_workspace_sync_under_enforce(engine, monkeypatch, tmp_path):
    async with engine.begin() as conn:
        retired = await _registry(conn, f"{PREFIX}old")
        forked = await _item(conn, retired, "forked")
        await _item(conn, retired, "unused")
        await conn.execute(
            text(
                "INSERT INTO skills (id, workspace_id, created_by, name, slug, registry_item_id) "
                "VALUES (:id, :w, 'u', 'forked', :slug, :item)"
            ),
            {"id": uuid.uuid4(), "w": OTHER, "slug": f"forked-{RUN}", "item": forked},
        )
        own = await _registry(
            conn,
            f"{PREFIX}own",
            scope="workspace",
            workspace_id=OWNER,
            source_url=WORKSPACE_URL,
            trust="private",
        )
        await _item(conn, own, "dropped", workspace_id=OWNER)

    payloads = {
        PLATFORM_URL: {"skills": [{"name": "fresh", "content": "# Fresh"}]},
        WORKSPACE_URL: {"skills": [{"name": "mine", "content": "# Mine"}]},
    }
    _enforced_reconcile(engine, monkeypatch, payloads)
    manifest = tmp_path / "registries.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": f"{PREFIX}new",
                    "type": "skills",
                    "source_url": PLATFORM_URL,
                    "mode": "upstream",
                    "trust": "community",
                },
                {"name": f"{PREFIX}old", "active": False},
            ]
        )
    )

    await cli._reconcile(None, (), str(manifest), workspace_registries=True)

    async with engine.connect() as conn:
        new = (
            await conn.execute(
                text("SELECT id FROM registries WHERE name = :n"), {"n": f"{PREFIX}new"}
            )
        ).scalar_one()
        assert await _external_ids(conn, new) == {"fresh": True}
        assert await _external_ids(conn, retired) == {"forked": False}
        assert await _external_ids(conn, own) == {"mine": True}


async def test_a_retired_registrys_installs_move_to_the_registry_replacing_it(
    engine, monkeypatch, tmp_path
):
    # The manifest lists the retired shard first; the registry that replaces it
    # is synced before it is retired, and the fork follows the item there.
    async with engine.begin() as conn:
        shard = await _registry(conn, f"{PREFIX}shard")
        old_item = await _item(conn, shard, "pdf")
        fork = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO skills (id, workspace_id, created_by, name, slug, registry_item_id) "
                "VALUES (:id, :w, 'u', 'pdf', :slug, :item)"
            ),
            {"id": fork, "w": OTHER, "slug": f"pdf-{RUN}", "item": old_item},
        )
    _enforced_reconcile(
        engine, monkeypatch, {PLATFORM_URL: {"skills": [{"name": "pdf", "content": "# P"}]}}
    )
    manifest = tmp_path / "registries.json"
    manifest.write_text(
        json.dumps(
            [
                {"name": f"{PREFIX}shard", "active": False},
                {
                    "name": f"{PREFIX}folded",
                    "type": "skills",
                    "source_url": PLATFORM_URL,
                    "mode": "upstream",
                    "trust": "community",
                },
            ]
        )
    )

    await cli._reconcile(None, (), str(manifest))

    async with engine.connect() as conn:
        assert await _external_ids(conn, shard) == {}
        moved_to = (
            await conn.execute(
                text(
                    "SELECT r.name FROM skills s JOIN registry_items ri ON ri.id = s.registry_item_id "
                    "JOIN registries r ON r.id = ri.registry_id WHERE s.id = :id"
                ),
                {"id": fork},
            )
        ).scalar_one()
        assert moved_to == f"{PREFIX}folded"


async def test_a_registry_another_reconcile_is_syncing_is_skipped(
    engine, monkeypatch, tmp_path, capsys
):
    # The ArgoCD Sync hook and the hourly CronJob can run at once; the second
    # to reach a registry leaves it to the first.
    _enforced_reconcile(engine, monkeypatch, {PLATFORM_URL: {"skills": [{"name": "a"}]}})
    manifest = tmp_path / "registries.json"
    manifest.write_text(
        json.dumps([{"name": f"{PREFIX}busy", "type": "skills", "source_url": PLATFORM_URL}])
    )
    async with engine.connect() as holder:
        holder = await holder.execution_options(isolation_level="AUTOCOMMIT")
        await holder.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"),
            {"k": f"registry-sync:platform:{PREFIX}busy"},
        )
        await cli._reconcile(None, (), str(manifest))
        await holder.execute(
            text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"),
            {"k": f"registry-sync:platform:{PREFIX}busy"},
        )

    captured = capsys.readouterr()
    assert "another reconcile is syncing it" in captured.out
    assert f"WARNING: skipped, another reconcile was syncing: {PREFIX}busy" in captured.err
    async with engine.connect() as conn:
        created = await conn.execute(
            text("SELECT count(*) FROM registries WHERE name = :n"), {"n": f"{PREFIX}busy"}
        )
        assert created.scalar_one() == 0


async def test_a_moved_source_is_synced_from_its_new_place(engine, monkeypatch, tmp_path):
    moved_url = "https://moved.example/skills.json"
    async with engine.begin() as conn:
        registry = await _registry(conn, f"{PREFIX}moved")
        await _item(conn, registry, "old-only")
        await conn.execute(
            text("UPDATE registries SET source_etag = 'v2:unchanged' WHERE id = :id"),
            {"id": registry},
        )
    _enforced_reconcile(
        engine, monkeypatch, {moved_url: {"skills": [{"name": "fresh", "content": "# F"}]}}
    )
    manifest = tmp_path / "registries.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": f"{PREFIX}moved",
                    "type": "skills",
                    "source_url": moved_url,
                    "mode": "upstream",
                    "trust": "community",
                }
            ]
        )
    )

    await cli._reconcile(None, (), str(manifest))

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT source_url FROM registries WHERE id = :id"), {"id": registry}
            )
        ).one()
        assert row.source_url == moved_url
        assert await _external_ids(conn, registry) == {"fresh": True}


async def test_platform_credentials_are_a_platform_secret_named_in_the_manifest(
    engine, monkeypatch, tmp_path
):
    secret_id = uuid.uuid4()
    name = f"{PREFIX}github-token"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO encrypted_secrets (id, workspace_id, secret_name, encrypted_value, "
                "created_by) VALUES (:id, 'platform', :name, 'ciphertext', 'test')"
            ),
            {"id": secret_id, "name": name},
        )
    url = "https://private.example/agents.json"
    _enforced_reconcile(engine, monkeypatch, {url: {"agents": []}})
    entry = {"name": f"{PREFIX}private", "type": "agents", "source_url": url}
    manifest = tmp_path / "registries.json"
    try:
        manifest.write_text(json.dumps([{**entry, "credentials_secret_ref": name}]))
        await cli._reconcile(None, (), str(manifest))

        async with engine.connect() as conn:
            stored = (
                await conn.execute(
                    text("SELECT id, credentials_secret_ref FROM registries WHERE name = :n"),
                    {"n": entry["name"]},
                )
            ).one()
            assert stored.credentials_secret_ref == secret_id
            consumers = await conn.execute(
                text("SELECT consumer_id FROM secret_references WHERE secret_id = :s"),
                {"s": secret_id},
            )
            assert consumers.scalars().all() == [str(stored.id)]

        manifest.write_text(json.dumps([entry]))
        await cli._reconcile(None, (), str(manifest))

        async with engine.connect() as conn:
            dropped = await conn.execute(
                text("SELECT credentials_secret_ref FROM registries WHERE name = :n"),
                {"n": entry["name"]},
            )
            assert dropped.scalar_one() is None
            left = await conn.execute(
                text("SELECT count(*) FROM secret_references WHERE secret_id = :s"),
                {"s": secret_id},
            )
            assert left.scalar_one() == 0
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM registries WHERE name = :n"), {"n": entry["name"]}
            )
            await conn.execute(
                text("DELETE FROM secret_references WHERE secret_id = :s"), {"s": secret_id}
            )
            await conn.execute(text("DELETE FROM encrypted_secrets WHERE id = :s"), {"s": secret_id})


def _enforced_reconcile(engine, monkeypatch, payloads) -> None:
    async def untrusted(_self, url):
        return payloads[url]

    async def no_etag(_self, _url):
        return None

    class EnforcedDatabase:
        def __init__(self, *_args) -> None:
            self.engine = engine
            self.async_session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
                sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
            )

    async def no_graph() -> None:
        return None

    monkeypatch.setattr(cli, "Database", EnforcedDatabase)
    monkeypatch.setattr(cli, "get_db_settings", lambda: None)
    monkeypatch.setattr(cli, "_register_graph_client", no_graph)
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda url: payloads[url]))
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: None))
    monkeypatch.setattr(RegistryService, "_fetch_untrusted", untrusted)
    monkeypatch.setattr(RegistryService, "_untrusted_etag", no_etag)
