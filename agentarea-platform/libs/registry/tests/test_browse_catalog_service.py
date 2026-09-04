"""End-to-end wiring for catalog browsing: service over the real repository.

The unit tests either side of this cover the query (test_registry_item_browse)
and the derivation (test_catalog_facets). This one checks the seam between them
-- that the page, its total and the facets all come back from one call and
describe the same filtered catalog.
"""

import pytest_asyncio
from agentarea_registry.application.catalog_facets import derive_facets
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository


@pytest_asyncio.fixture
async def service(db_session):
    item_repo = RegistryItemRepository(db_session)
    registry_repo = RegistryRepository(db_session)

    reg = Registry(
        name="skills",
        registry_type="skills",
        source_type="url",
        source_url="https://example.test/skills.json",
    )
    db_session.add(reg)
    await db_session.commit()
    await db_session.refresh(reg)

    catalog = [
        ("pdf-fill--acme--1", ["category:other"]),
        ("csv-clean--acme--2", ["category:data"]),
        ("xls-merge--acme--3", ["category:data", "featured"]),
        ("odd-one--acme--4", []),
    ]
    for name, tags in catalog:
        facets = derive_facets("skills", name, {}, tags)
        await item_repo.create(
            registry_id=reg.id,
            external_id=name,
            name=name,
            spec={},
            tags=tags,
            category=facets.category,
            sort_key=facets.sort_key,
            featured=facets.featured,
        )

    return RegistryService(registry_repo, item_repo, server_repo=None)


class TestBrowseCatalog:
    async def test_returns_page_total_and_facets_from_one_call(self, service):
        items, total, categories = await service.browse_catalog("skills", limit=10)
        assert [i.name for i in items] == [
            "xls-merge--acme--3",  # featured floats to the top
            "csv-clean--acme--2",
            "odd-one--acme--4",
            "pdf-fill--acme--1",
        ]
        assert total == 4
        assert categories == [("data", 2), ("other", 1)]

    async def test_a_category_page_beyond_the_first_still_reports_the_total(self, service):
        # The ?category=other shape: paging must keep working when the current
        # slice contributes nothing visible.
        items, total, _ = await service.browse_catalog("skills", category="data", limit=1, offset=5)
        assert items == []
        assert total == 2

    async def test_facets_ignore_the_active_category_so_you_can_switch_away(self, service):
        _, _, categories = await service.browse_catalog("skills", category="data")
        assert categories == [("data", 2), ("other", 1)]

    async def test_name_sort_drops_the_featured_priority(self, service):
        items, _, _ = await service.browse_catalog("skills", sort="name", limit=10)
        assert [i.name for i in items] == [
            "csv-clean--acme--2",
            "odd-one--acme--4",
            "pdf-fill--acme--1",
            "xls-merge--acme--3",
        ]

    async def test_search_narrows_the_page_the_total_and_the_facets_together(self, service):
        items, total, categories = await service.browse_catalog("skills", query="csv")
        assert [i.name for i in items] == ["csv-clean--acme--2"]
        assert total == 1
        assert categories == [("data", 1)]

    async def test_paging_partitions_the_catalog(self, service):
        first, total, _ = await service.browse_catalog("skills", limit=2, offset=0)
        second, _, _ = await service.browse_catalog("skills", limit=2, offset=2)
        assert len({i.id for i in [*first, *second]}) == 4
        assert total == 4
