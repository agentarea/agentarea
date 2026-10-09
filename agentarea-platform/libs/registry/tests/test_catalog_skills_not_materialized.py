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
        get_by_external_id=AsyncMock(return_value=None),
        mark_in_source=AsyncMock(return_value=0),
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
