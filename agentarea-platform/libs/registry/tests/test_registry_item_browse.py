"""Catalog browsing: one ordered, paged query across every registry of a type.

The gallery used to page each registry of a type separately and stitch the
results together client-side, advancing a single offset by the *summed* item
count -- which skipped whole slices of every registry past page 1 -- and then
re-sorted and re-filtered the stitched list in the browser. These tests pin the
server-side replacement: filtering, sorting and paging all happen in SQL, so
one offset means one thing.
"""

import pytest_asyncio
from agentarea_registry.application.catalog_facets import derive_facets
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository


async def _registry(session, name: str, registry_type: str = "skills", is_active: bool = True):
    reg = Registry(
        name=name,
        registry_type=registry_type,
        source_type="url",
        source_url=f"https://example.test/{name}.json",
        is_active=is_active,
    )
    session.add(reg)
    await session.commit()
    await session.refresh(reg)
    return reg


async def _item(repo, registry, external_id, name, *, spec=None, tags=None, registry_type=None):
    facets = derive_facets(registry_type or registry.registry_type, name, spec or {}, tags or [])
    return await repo.create(
        registry_id=registry.id,
        external_id=external_id,
        name=name,
        spec=spec or {},
        tags=tags or [],
        category=facets.category,
        sort_key=facets.sort_key,
        featured=facets.featured,
    )


@pytest_asyncio.fixture
async def item_repo(db_session):
    return RegistryItemRepository(db_session)


class TestPagingAcrossRegistries:
    @pytest_asyncio.fixture
    async def two_registries(self, db_session, item_repo):
        # Two active skills registries, interleaving alphabetically -- the exact
        # shape the old per-registry fan-out got wrong.
        a = await _registry(db_session, "alpha")
        b = await _registry(db_session, "beta")
        for n in ("apple", "cherry", "elder"):
            await _item(item_repo, a, f"a-{n}", n)
        for n in ("banana", "date", "fig"):
            await _item(item_repo, b, f"b-{n}", n)
        return a, b

    async def test_orders_across_registries_not_within_each(self, item_repo, two_registries):
        items, _ = await item_repo.browse("skills", sort="name", limit=10, offset=0)
        assert [i.name for i in items] == ["apple", "banana", "cherry", "date", "elder", "fig"]

    async def test_pages_partition_the_catalog_without_gaps_or_repeats(self, item_repo, two_registries):
        page1, total = await item_repo.browse("skills", sort="name", limit=2, offset=0)
        page2, _ = await item_repo.browse("skills", sort="name", limit=2, offset=2)
        page3, _ = await item_repo.browse("skills", sort="name", limit=2, offset=4)
        page4, _ = await item_repo.browse("skills", sort="name", limit=2, offset=6)

        assert [i.name for i in page1] == ["apple", "banana"]
        assert [i.name for i in page2] == ["cherry", "date"]
        assert [i.name for i in page3] == ["elder", "fig"]
        assert page4 == []
        assert total == 6

    async def test_total_is_the_whole_matching_set_not_the_page(self, item_repo, two_registries):
        items, total = await item_repo.browse("skills", limit=2, offset=0)
        assert len(items) == 2
        assert total == 6

    async def test_ignores_other_types_and_inactive_registries(self, db_session, item_repo, two_registries):
        agents = await _registry(db_session, "agent-reg", registry_type="agents")
        await _item(item_repo, agents, "ag-1", "aardvark")
        dormant = await _registry(db_session, "dormant", is_active=False)
        await _item(item_repo, dormant, "d-1", "aaa-hidden")

        items, total = await item_repo.browse("skills", sort="name", limit=10, offset=0)
        assert [i.name for i in items] == ["apple", "banana", "cherry", "date", "elder", "fig"]
        assert total == 6


class TestOrdering:
    @pytest_asyncio.fixture
    async def mixed(self, db_session, item_repo):
        reg = await _registry(db_session, "r")
        await _item(item_repo, reg, "1", "zebra")
        await _item(item_repo, reg, "2", "Apple")
        await _item(item_repo, reg, "3", "mango", tags=["featured"])
        await _item(item_repo, reg, "4", "banana", tags=["featured"])
        return reg

    async def test_featured_sort_floats_curated_entries_then_alphabetises(self, item_repo, mixed):
        items, _ = await item_repo.browse("skills", sort="featured", limit=10, offset=0)
        assert [i.name for i in items] == ["banana", "mango", "Apple", "zebra"]

    async def test_name_sort_is_case_insensitive(self, item_repo, mixed):
        items, _ = await item_repo.browse("skills", sort="name", limit=10, offset=0)
        assert [i.name for i in items] == ["Apple", "banana", "mango", "zebra"]

    async def test_featured_is_the_default_sort(self, item_repo, mixed):
        default, _ = await item_repo.browse("skills", limit=10, offset=0)
        explicit, _ = await item_repo.browse("skills", sort="featured", limit=10, offset=0)
        assert [i.id for i in default] == [i.id for i in explicit]

    async def test_ties_break_deterministically_so_pages_do_not_overlap(self, db_session, item_repo):
        # Same sort_key on every row: without a stable tiebreak, OFFSET paging is
        # free to return the same row twice and drop another.
        reg = await _registry(db_session, "dupes")
        for n in range(6):
            await _item(item_repo, reg, f"d-{n}", "same")

        seen = []
        for offset in (0, 2, 4):
            page, _ = await item_repo.browse("skills", sort="name", limit=2, offset=offset)
            seen.extend(i.id for i in page)
        assert len(set(seen)) == 6

    async def test_unknown_sort_falls_back_to_the_default(self, item_repo, mixed):
        items, _ = await item_repo.browse("skills", sort="nonsense", limit=10, offset=0)
        assert [i.name for i in items] == ["banana", "mango", "Apple", "zebra"]


class TestFiltering:
    @pytest_asyncio.fixture
    async def catalog(self, db_session, item_repo):
        reg = await _registry(db_session, "r")
        await _item(item_repo, reg, "1", "pdf-fill", tags=["category:other"])
        await _item(item_repo, reg, "2", "csv-clean", tags=["category:data"])
        await _item(item_repo, reg, "3", "xls-merge", tags=["category:data"])
        await _item(item_repo, reg, "4", "no-cat", tags=[])
        return reg

    async def test_category_filter_narrows_and_retotals(self, item_repo, catalog):
        items, total = await item_repo.browse("skills", category="data", sort="name", limit=10, offset=0)
        assert [i.name for i in items] == ["csv-clean", "xls-merge"]
        assert total == 2

    async def test_a_category_matching_nothing_on_this_page_still_reports_the_full_total(
        self, item_repo, catalog
    ):
        # The bug behind ?category=other: a page whose matches were all beyond the
        # first slice used to render "No matches" and kill infinite scroll.
        items, total = await item_repo.browse("skills", category="data", sort="name", limit=1, offset=1)
        assert [i.name for i in items] == ["xls-merge"]
        assert total == 2

    async def test_query_matches_name_and_description(self, db_session, item_repo, catalog):
        await item_repo.create(
            registry_id=catalog.id,
            external_id="5",
            name="unrelated",
            description="merges spreadsheets",
            spec={},
            tags=[],
            category=None,
            sort_key="unrelated",
            featured=False,
        )
        items, total = await item_repo.browse("skills", q="merge", sort="name", limit=10, offset=0)
        assert {i.name for i in items} == {"xls-merge", "unrelated"}
        assert total == 2

    async def test_query_is_case_insensitive(self, item_repo, catalog):
        items, _ = await item_repo.browse("skills", q="PDF", limit=10, offset=0)
        assert [i.name for i in items] == ["pdf-fill"]

    async def test_query_and_category_compose(self, item_repo, catalog):
        items, total = await item_repo.browse("skills", q="e", category="data", sort="name", limit=10, offset=0)
        assert [i.name for i in items] == ["csv-clean", "xls-merge"]
        assert total == 2


class TestCategoryCounts:
    @pytest_asyncio.fixture
    async def catalog(self, db_session, item_repo):
        a = await _registry(db_session, "a")
        b = await _registry(db_session, "b")
        await _item(item_repo, a, "1", "one", tags=["category:other"])
        await _item(item_repo, a, "2", "two", tags=["category:data"])
        await _item(item_repo, b, "3", "three", tags=["category:data"])
        await _item(item_repo, b, "4", "four", tags=[])
        other_type = await _registry(db_session, "c", registry_type="agents")
        await _item(item_repo, other_type, "5", "five", tags=["support"])
        return a, b

    async def test_counts_span_every_registry_of_the_type(self, item_repo, catalog):
        # Facet counts used to be computed from the loaded page, so they shifted
        # under the user as infinite scroll appended.
        assert await item_repo.category_counts("skills") == [("data", 2), ("other", 1)]

    async def test_uncategorised_items_are_not_a_bucket(self, item_repo, catalog):
        counts = await item_repo.category_counts("skills")
        assert all(value is not None for value, _ in counts)

    async def test_ordered_alphabetically_so_the_list_is_scannable(self, db_session, item_repo, catalog):
        # Ordering by count put a category wherever its size happened to land,
        # so finding a known one meant reading the whole sidebar. The counts are
        # flat anyway (most categories hold one or two items), so size bought
        # nothing.
        a, _ = catalog
        await _item(item_repo, a, "6", "six", tags=["category:alpha"])
        assert await item_repo.category_counts("skills") == [
            ("alpha", 1),
            ("data", 2),
            ("other", 1),
        ]

    async def test_the_fallback_bucket_sorts_last_however_big_it_is(self, db_session, item_repo, catalog):
        # "other" is where the source puts what it couldn't classify -- a
        # fallback, not a peer. Alphabetically it would land mid-list, and by
        # size it sat near the top; neither is where it belongs.
        a, _ = catalog
        for n in range(5):
            await _item(item_repo, a, f"pad-{n}", f"pad {n}", tags=["category:other"])
        counts = await item_repo.category_counts("skills")
        assert counts[-1][0] == "other"
        assert counts[-1][1] == 6
        assert [value for value, _ in counts] == ["data", "other"]

    async def test_a_category_named_like_the_fallback_is_not_demoted(self, db_session, item_repo, catalog):
        # Only the exact fallback value is special; "other-tools" is a category.
        a, _ = catalog
        await _item(item_repo, a, "7", "seven", tags=["category:other-tools"])
        assert [v for v, _ in await item_repo.category_counts("skills")] == [
            "data",
            "other-tools",
            "other",
        ]

    async def test_counts_respect_the_search_query(self, item_repo, catalog):
        assert await item_repo.category_counts("skills", q="two") == [("data", 1)]
