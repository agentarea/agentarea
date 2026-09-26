"""Every /explore query must be answerable from an index, on the real schema.

The catalog holds ~300k rows in production and each row carries a ~1 KB
``spec``. Browse used to join ``registries`` and sort on a column from it, so no
index could produce the order: every page, total and facet was a parallel seq
scan of the whole table (1.4 GB), three of them per page load -- 12 s against an
8 s client budget, and enough IO to stall every other query on the database.

Plans are checked with the planner's alternatives switched off rather than by
seeding a production-sized table: with ``enable_seqscan``/``enable_sort`` off
the planner still falls back to a seq scan or an explicit sort when no index
can serve the query, so their absence proves an index path exists regardless
of row counts or cost estimates.

The statements are captured from the repository itself, so the test follows the
SQL the code actually sends rather than a hand-written copy of it.
"""

import json
import os
from collections.abc import AsyncGenerator

import pytest
from agentarea_registry.application.catalog_facets import derive_facets
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="CATALOG_TEST_DATABASE_URL not set; skipping schema-backed catalog plan tests",
)

PREFIX = "plan-test-"


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


async def _seed(session: AsyncSession) -> None:
    repo = RegistryItemRepository(session)
    for name, registry_type, priority in (
        ("skills-curated", "skills", 10),
        ("skills-mirror", "skills", 900),
        ("conns", "mcp_servers", 100),
    ):
        reg = Registry(
            name=f"{PREFIX}{name}",
            registry_type=registry_type,
            source_type="url",
            source_url=f"https://example.test/{name}.json",
            recommendation_priority=priority,
        )
        session.add(reg)
        await session.commit()
        for n in range(5):
            spec = {"connection_type": "openapi" if n == 0 else "url"}
            tags = [f"category:{'data' if n % 2 else 'dev'}"]
            facets = derive_facets(registry_type, f"{name}-{n}", spec, tags)
            await repo.create(
                registry_id=reg.id,
                external_id=f"{name}-{n}",
                name=f"{name}-{n}",
                description=f"merges things {n}",
                spec=spec,
                tags=tags,
                recommendation_rank=n,
                **facets._asdict(),
            )


async def _captured(engine: AsyncEngine, session: AsyncSession, call) -> list[tuple[str, tuple]]:
    statements: list[tuple[str, tuple]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "registry_items" in statement:
            statements.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await call(RegistryItemRepository(session))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements, "the repository sent no query touching registry_items"
    return statements


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get("Plans", []):
        found.extend(_nodes(child))
    return found


async def _plans(engine: AsyncEngine, statements, *settings: str) -> list[list[dict]]:
    plans = []
    async with engine.connect() as conn:
        for setting in settings:
            await conn.exec_driver_sql(f"SET {setting} = off")
        for statement, parameters in statements:
            result = await conn.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement}", parameters)
            raw = result.scalar_one()
            plans.append(_nodes((json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]))
        await conn.rollback()
    return plans


def _seq_scans_on_items(nodes: list[dict]) -> list[dict]:
    return [
        n
        for n in nodes
        if n["Node Type"] == "Seq Scan" and n.get("Relation Name") == "registry_items"
    ]


def _sorts(nodes: list[dict]) -> list[str]:
    return [n["Node Type"] for n in nodes if "Sort" in n["Node Type"]]


def _item_scans(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("Relation Name") == "registry_items"]


def _scoped_to_type(node: dict) -> bool:
    # A walk over an index that merely *contains* registry_type still reads the
    # whole catalog; only a condition on it bounds the scan to one type.
    return "registry_type" in node.get("Index Cond", "")


@pytest.fixture
async def seeded(engine: AsyncEngine, session: AsyncSession) -> None:
    await _seed(session)
    # Bulk that matches no search, so a search is selective the way it is in
    # production and the planner has a real choice to make.
    await session.execute(
        text(
            """
            INSERT INTO registry_items (id, registry_id, external_id, name, description,
                spec, tags, update_available, category, sort_key, featured,
                recommendation_rank, registry_type, registry_priority, registry_active,
                created_at, updated_at)
            SELECT gen_random_uuid(), r.id, 'filler-' || n, 'filler ' || n, 'unrelated text',
                '{}', '[]', false, 'dev', 'filler ' || n, false, n, r.registry_type,
                r.recommendation_priority, r.is_active, now(), now()
            FROM registries r, generate_series(1, 3000) n
            WHERE r.name = :name
            """
        ),
        {"name": f"{PREFIX}skills-mirror"},
    )
    await session.commit()
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("VACUUM ANALYZE registry_items")


PAGES = {
    "recommended": lambda r: r.browse("skills", sort="recommended", limit=48, offset=0),
    "recommended in a category": lambda r: r.browse(
        "skills", category="data", sort="recommended", limit=48, offset=0
    ),
    "by name": lambda r: r.browse("skills", sort="name", limit=48, offset=0),
    "by name in a category": lambda r: r.browse(
        "skills", category="data", sort="name", limit=48, offset=0
    ),
    "connections by protocol": lambda r: r.browse(
        "mcp_servers", protocol="api", sort="recommended", limit=48, offset=0
    ),
}

FACETS = {
    "categories": lambda r: r.category_counts("skills"),
    "categories for one protocol": lambda r: r.category_counts("mcp_servers", protocol="api"),
    "protocols": lambda r: r.protocol_counts("mcp_servers"),
}


@pytest.mark.parametrize("name", list(PAGES))
async def test_a_page_and_its_total_are_read_from_an_index_in_order(engine, session, seeded, name):
    statements = await _captured(engine, session, PAGES[name])
    page, *counts = await _plans(engine, statements, "enable_seqscan", "enable_sort")

    assert not _sorts(page), "no index yields the page order, so every page sorts the table"
    assert all(_scoped_to_type(n) for n in _item_scans(page))
    for nodes in counts:
        assert all(
            n["Node Type"] == "Index Only Scan" and _scoped_to_type(n) for n in _item_scans(nodes)
        ), "the total reads catalog rows instead of counting index entries"


@pytest.mark.parametrize("name", list(FACETS))
async def test_facets_are_counted_from_an_index(engine, session, seeded, name):
    statements = await _captured(engine, session, FACETS[name])
    for nodes in await _plans(engine, statements, "enable_seqscan"):
        scans = _item_scans(nodes)
        assert scans
        assert all(n["Node Type"] == "Index Only Scan" and _scoped_to_type(n) for n in scans)


async def test_search_uses_the_trigram_indexes(engine, session, seeded):
    # A btree cannot answer ILIKE '%term%'; with plain index scans switched off
    # only a bitmap over a trigram index is left, or else a seq scan.
    statements = await _captured(
        engine, session, lambda r: r.browse("skills", q="merge", sort="name", limit=48, offset=0)
    )
    for nodes in await _plans(
        engine, statements, "enable_seqscan", "enable_indexscan", "enable_indexonlyscan"
    ):
        assert not _seq_scans_on_items(nodes)
        assert any(
            n["Node Type"] == "Bitmap Index Scan" and "trgm" in n["Index Name"] for n in nodes
        )
