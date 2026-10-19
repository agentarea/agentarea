"""Syncing a skills catalog creates catalog items, not platform Skill rows.

Skills are read through the catalog projection and forked into a workspace on
use, like agents (ADR-003). Materializing one platform Skill per catalog item
left 220k unused rows on RU, each with four ownership tuples in the graph.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agentarea_registry.application.service import RegistryService


async def test_a_new_catalog_skill_gets_no_skill_row():
    registry = SimpleNamespace(
        id=uuid4(),
        registry_type="skills",
        source_type="url",
        source_url="https://x/s.json",
        scope="platform",
        mode="upstream",
    )
    item = SimpleNamespace(id=uuid4(), version="latest", spec={}, name="pdf")
    item_repo = SimpleNamespace(
        list_by_registry=AsyncMock(return_value=[]),
        mark_in_source=AsyncMock(return_value=0),
        delete_unreferenced_out_of_source=AsyncMock(return_value=0),
        create=AsyncMock(return_value=item),
        update=AsyncMock(),
        delete=AsyncMock(),
    )
    skill_repo = SimpleNamespace(create=AsyncMock(), get_by_slug=AsyncMock(return_value=None))
    service = RegistryService(
        SimpleNamespace(get_by_id=AsyncMock(return_value=registry), update=AsyncMock()),
        item_repo,
        server_repo=None,
        skill_repo=skill_repo,
    )
    source = {"skills": [{"name": "pdf", "description": "Fill PDFs", "content": "# pdf"}]}

    with patch.object(RegistryService, "_fetch_source", staticmethod(lambda url: source)):
        stats = await service.sync_registry(registry.id)

    assert stats["new_specs"] == 1
    skill_repo.create.assert_not_called()
    item_repo.update.assert_awaited_with(item.id, installed_entity_id=None, installed_version="latest")


async def _legacy_catalog(db_session, monkeypatch, workspace_id, published):
    from agentarea_registry.domain.models import Registry
    from agentarea_registry.infrastructure.repository import (
        RegistryItemRepository,
        RegistryRepository,
    )

    registry = Registry(
        name="skills",
        registry_type="skills",
        source_type="url",
        source_url="https://x/s.json",
        scope="platform",
        mode="upstream",
    )
    db_session.add(registry)
    await db_session.commit()
    items = RegistryItemRepository(db_session)
    rows = {}
    for name in ("pdf", "docx"):
        item = await items.create(registry_id=registry.id, external_id=name, name=name)
        rows[name] = uuid4()
        await items.update(item.id, installed_entity_id=rows[name])
    skill_repo = SimpleNamespace(
        delete=AsyncMock(return_value=True),
        user_context=SimpleNamespace(workspace_id=workspace_id),
    )
    service = RegistryService(
        RegistryRepository(db_session), items, server_repo=None, skill_repo=skill_repo
    )
    source = {"skills": [{"name": n, "description": n, "content": f"# {n}"} for n in published]}
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda url: source))
    return service, registry, items, skill_repo, rows


async def test_platform_skill_rows_left_by_earlier_syncs_are_removed(db_session, monkeypatch):
    from agentarea_common.constants import PLATFORM_WORKSPACE_ID

    service, registry, items, skill_repo, rows = await _legacy_catalog(
        db_session, monkeypatch, PLATFORM_WORKSPACE_ID, published=["pdf"]
    )
    # Which unlinked items are then deleted is covered on the real schema
    # (test_catalog_retire_db); the referencing tables are not in this SQLite.
    monkeypatch.setattr(items, "delete_unreferenced_out_of_source", AsyncMock(return_value=0))

    await service.sync_registry(registry.id)

    # Both: the published item's row, and the dropped item's, so it can go too.
    assert sorted(c.args[0] for c in skill_repo.delete.await_args_list) == sorted(rows.values())
    assert all(i.installed_entity_id is None for i in await items.list_by_registry(registry.id))


async def test_a_sync_through_a_tenant_repository_leaves_platform_rows_linked(
    db_session, monkeypatch
):
    service, registry, items, skill_repo, rows = await _legacy_catalog(
        db_session, monkeypatch, "some-workspace", published=["pdf", "docx"]
    )

    await service.sync_registry(registry.id)

    skill_repo.delete.assert_not_called()
    linked = {i.external_id: i.installed_entity_id for i in await items.list_by_registry(registry.id)}
    assert linked == rows
