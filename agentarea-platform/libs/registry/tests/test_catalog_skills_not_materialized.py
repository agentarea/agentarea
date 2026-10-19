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
        id=uuid4(), registry_type="skills", source_type="url", source_url="https://x/s.json"
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


async def test_a_platform_skill_row_left_by_an_earlier_sync_is_removed(db_session, monkeypatch):
    from agentarea_registry.domain.models import Registry
    from agentarea_registry.infrastructure.repository import (
        RegistryItemRepository,
        RegistryRepository,
    )

    registry = Registry(
        name="skills", registry_type="skills", source_type="url", source_url="https://x/s.json"
    )
    db_session.add(registry)
    await db_session.commit()
    items = RegistryItemRepository(db_session)
    legacy_row = uuid4()
    item = await items.create(registry_id=registry.id, external_id="pdf", name="pdf")
    await items.update(item.id, installed_entity_id=legacy_row)
    skill_repo = SimpleNamespace(delete=AsyncMock(return_value=True))
    service = RegistryService(
        RegistryRepository(db_session), items, server_repo=None, skill_repo=skill_repo
    )
    source = {"skills": [{"name": "pdf", "description": "Fill PDFs", "content": "# pdf"}]}
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda url: source))

    await service.sync_registry(registry.id)

    skill_repo.delete.assert_awaited_once_with(legacy_row)
    await db_session.refresh(item)
    assert item.installed_entity_id is None
