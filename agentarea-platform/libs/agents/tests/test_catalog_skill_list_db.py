"""The catalog half of the skill list against the real migrated schema.

The catalog holds ~150k skills in production. The list, its total and the
update check on forked skills used to join ``registries`` and compare
``ri.id::text``, which no index serves: three parallel seq scans of the whole
catalog per request (0.7-4 s on RU prod), and items of inactive registries were
listed. Plans are checked with the planner's alternatives switched off, as in
``test_catalog_browse_plans_db.py``: if a seq scan or sort survives, no index
can serve the query.

Set CATALOG_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CATALOG_TEST_DATABASE_URL not set")


@pytest.fixture
def marker() -> str:
    """A name fragment only this test's rows carry, so the shared catalog cannot leak in."""
    return f"probe{uuid4().hex[:10]}"


@pytest.fixture
def repo(session) -> CatalogSkillRepository:
    return CatalogSkillRepository(session, UserContext(user_id="u", workspace_id=f"ws-{uuid4()}"))


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


async def _registry(session, *, active: bool = True) -> str:
    registry_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'skills', 'managed', 'x', :active, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}", "active": active},
    )
    return registry_id


async def _item(session, registry_id: str, name: str, *, sort_key: str | None = None) -> str:
    item_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "version, spec, tags, sort_key, featured, registry_type, registry_priority, "
            "registry_active, created_at, updated_at) "
            "SELECT :id, r.id, :external_id, :name, 'desc', '2', CAST(:spec AS jsonb), "
            "'[]', :sort_key, false, r.registry_type, r.recommendation_priority, "
            "r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": item_id,
            "registry_id": registry_id,
            "external_id": f"{name}-{item_id}",
            "name": name,
            "sort_key": sort_key if sort_key is not None else name,
            "spec": json.dumps({"source_type": "github", "source_url": "https://x"}),
        },
    )
    return item_id


async def test_the_page_follows_the_display_order_and_skips_forked_items(session, repo, marker):
    registry = await _registry(session)
    await _item(session, registry, f"{marker}-zeta", sort_key=f"{marker} a")
    forked = await _item(session, registry, f"{marker}-alpha", sort_key=f"{marker} b")
    await _item(session, registry, f"{marker}-mu", sort_key=f"{marker} c")

    rows, total = await repo.list_page(
        limit=10, offset=0, exclude_item_ids=[forked], search=marker
    )

    assert total == 2
    assert [r.name for r in rows] == [f"{marker}-zeta", f"{marker}-mu"]


async def test_an_inactive_registry_contributes_nothing(session, repo, marker):
    hidden = await _item(session, await _registry(session, active=False), f"{marker}-hidden")

    rows, total = await repo.list_page(limit=10, offset=0, exclude_item_ids=[], search=marker)

    assert (rows, total) == ([], 0)
    assert await repo.get_item(hidden) is None
    assert await repo.find_by_key(f"{marker}-hidden") is None
    assert await repo.versions_for([hidden]) == {}


async def test_a_page_past_the_end_reads_no_rows(session, repo, marker):
    await _item(session, await _registry(session), f"{marker}-only")
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.bind.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows, total = await repo.list_page(limit=5, offset=5, exclude_item_ids=[], search=marker)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert (rows, total) == ([], 1)
    assert [s for s in statements if "COUNT" not in s] == []


async def test_versions_for_reads_forked_items(session, repo, marker):
    item = await _item(session, await _registry(session), f"{marker}-forked")

    assert await repo.versions_for([item]) == {item: ("2", None)}


PLAN_PREFIX = "skill-plan-test-"


@pytest.fixture
async def seeded():
    """A committed, vacuumed catalog, as the planner sees one in production.

    Index-only counts depend on the visibility map, which only VACUUM sets and
    VACUUM cannot run inside the rolled-back test transaction.
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        registry = str(uuid4())
        await conn.execute(
            text(
                "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
                "is_active, created_at, updated_at) "
                "VALUES (:id, :name, 'skills', 'managed', 'x', true, now(), now())"
            ),
            {"id": registry, "name": f"{PLAN_PREFIX}{registry}"},
        )
        await conn.execute(
            text(
                "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
                "spec, tags, sort_key, featured, registry_type, registry_priority, "
                "registry_active, created_at, updated_at) "
                "SELECT gen_random_uuid(), r.id, 'filler-' || n, 'filler ' || n, "
                "'unrelated text', '{}', '[]', 'filler ' || n, false, r.registry_type, "
                "r.recommendation_priority, r.is_active, now(), now() "
                "FROM registries r, generate_series(1, 3000) n WHERE r.id = :registry_id"
            ),
            {"registry_id": registry},
        )
        ids = (
            await conn.execute(
                text("SELECT id FROM registry_items WHERE registry_id = :r LIMIT 3"),
                {"r": registry},
            )
        ).scalars()
        forked = [str(i) for i in ids]
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("VACUUM ANALYZE registry_items")
    yield engine, forked
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM registries WHERE name LIKE :p"), {"p": f"{PLAN_PREFIX}%"}
        )
    await engine.dispose()


async def _plans(seeded, call, *settings: str) -> list[list[dict]]:
    """Capture what ``call`` sends to registry_items, then EXPLAIN it with ``settings`` off."""
    engine, _ = seeded
    captured: list[tuple[str, tuple]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "registry_items" in statement:
            captured.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncSession(engine) as s:
            await call(CatalogSkillRepository(s, UserContext(user_id="u", workspace_id="ws")))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert captured, "the repository sent no query touching registry_items"

    plans = []
    async with engine.connect() as conn:
        for setting in settings:
            await conn.exec_driver_sql(f"SET {setting} = off")
        for statement, parameters in captured:
            raw = (
                await conn.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement}", parameters)
            ).scalar_one()
            plans.append(_nodes((json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]))
        await conn.rollback()
    return plans


def _nodes(plan: dict) -> list[dict]:
    found = [plan]
    for child in plan.get("Plans", []):
        found.extend(_nodes(child))
    return found


def _item_scans(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("Relation Name") == "registry_items"]


def _scoped_to_type(node: dict) -> bool:
    # The browse-order index, and a condition on its leading registry_type: a
    # walk over an index that merely contains registry_type still reads the
    # whole catalog, and any other index cannot yield the sort_key order.
    return node.get("Index Name") == "ix_registry_items_browse_name" and (
        "registry_type" in node.get("Index Cond", "")
    )


async def test_the_page_and_its_total_are_read_from_an_index_in_order(seeded):
    _, forked = seeded
    # Bitmap scans are off too: at test scale a bitmap over the facets index
    # can undercut the index-only walk that production picks for the total,
    # and a bitmap page would need a sort anyway.
    count, page = await _plans(
        seeded,
        lambda r: r.list_page(limit=48, offset=0, exclude_item_ids=forked),
        "enable_seqscan",
        "enable_sort",
        "enable_bitmapscan",
    )

    assert not [n for n in page if "Sort" in n["Node Type"]], "every page sorts the catalog"
    assert all(_scoped_to_type(n) for n in _item_scans(page))
    assert all(
        n["Node Type"] == "Index Only Scan" and _scoped_to_type(n) for n in _item_scans(count)
    ), "the total reads catalog rows instead of counting index entries"
    assert not [n for n in page + count if n.get("Relation Name") == "registries"]


async def test_the_update_check_looks_forks_up_by_primary_key(seeded):
    _, forked = seeded
    (nodes,) = await _plans(seeded, lambda r: r.versions_for(forked), "enable_seqscan")

    assert all(n["Node Type"] != "Seq Scan" for n in _item_scans(nodes))
    assert any(
        n.get("Index Name") == "registry_items_pkey" and "id = ANY" in n.get("Index Cond", "")
        for n in nodes
    )


async def test_search_uses_the_trigram_indexes(seeded):
    # A btree cannot answer ILIKE '%term%'; with plain index scans switched off
    # only a bitmap over a trigram index is left, or else a seq scan.
    for nodes in await _plans(
        seeded,
        lambda r: r.list_page(limit=48, offset=0, exclude_item_ids=[], search="merge"),
        "enable_seqscan",
        "enable_indexscan",
        "enable_indexonlyscan",
    ):
        assert all(n["Node Type"] != "Seq Scan" for n in _item_scans(nodes))
        assert any(
            n["Node Type"] == "Bitmap Index Scan" and "trgm" in n["Index Name"] for n in nodes
        )
