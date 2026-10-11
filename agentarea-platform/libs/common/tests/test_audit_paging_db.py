"""Keyset paging over the real ``audit_events`` table.

A cursor that names no event of the workspace used to be dropped, which
restarted the walk at page one; one from another workspace was honoured as a
position. Events sharing a ``created_at`` straddling a page boundary were
skipped, because the page condition compared the timestamp alone.

Needs a PostgreSQL migrated to head; skips without one:

    AUDIT_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agentarea_test  # pragma: allowlist secret
"""

import os
from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.audit.repository import AuditRepository, UnknownAuditCursorError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("AUDIT_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="AUDIT_TEST_DATABASE_URL not set; skipping schema-backed audit tests",
)

SAME_INSTANT = datetime(2026, 10, 9, 12, 0, 0)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    # Rows stay: the table refuses DELETE. Each test writes to its own workspace.
    await engine.dispose()


async def _insert(session: AsyncSession, workspace_id: str, count: int) -> list[UUID]:
    ids = [uuid4() for _ in range(count)]
    for event_id in ids:
        session.add(
            AuditEventORM(
                id=event_id,
                created_at=SAME_INSTANT,
                updated_at=SAME_INSTANT,
                actor_id="tester",
                actor_type="user",
                workspace_id=workspace_id,
                action="agent.create",
                resource_type="agent",
                event_metadata={},
            )
        )
    await session.commit()
    return ids


async def test_paging_through_events_of_one_instant_returns_each_once(session) -> None:
    workspace = f"audit-paging-{uuid4()}"
    stored = await _insert(session, workspace, 5)
    repo = AuditRepository(session)

    seen: list[UUID] = []
    cursor = None
    for _ in range(10):
        page = await repo.query(workspace, cursor=cursor, limit=2)
        seen.extend(event.id for event in page)
        if len(page) < 2:
            break
        cursor = page[-1].id

    assert sorted(seen) == sorted(stored)
    assert len(seen) == len(set(seen))


async def test_an_unknown_cursor_is_refused(session) -> None:
    workspace = f"audit-paging-{uuid4()}"
    await _insert(session, workspace, 1)

    with pytest.raises(UnknownAuditCursorError):
        await AuditRepository(session).query(workspace, cursor=uuid4())


async def test_a_cursor_from_another_workspace_is_refused(session) -> None:
    mine, theirs = f"audit-paging-{uuid4()}", f"audit-paging-{uuid4()}"
    await _insert(session, mine, 1)
    (their_event,) = await _insert(session, theirs, 1)

    with pytest.raises(UnknownAuditCursorError):
        await AuditRepository(session).query(mine, cursor=their_event)
