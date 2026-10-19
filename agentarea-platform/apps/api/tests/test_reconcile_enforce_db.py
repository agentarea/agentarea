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
            "workspace_id, mode, trust, is_active, sync_mode, recommendation_priority, item_count) "
            "VALUES (:id, :name, :registry_type, :source_type, :source_url, :scope, "
            ":workspace_id, :mode, :trust, true, 'manual', 100, 0)"
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


def _enforced_reconcile(engine, monkeypatch, payloads) -> None:
    async def untrusted(_self, url):
        return payloads[url]

    async def no_etag(_self, _url):
        return None

    class EnforcedDatabase:
        def __init__(self, *_args) -> None:
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
