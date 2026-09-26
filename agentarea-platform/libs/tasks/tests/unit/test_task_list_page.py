"""The workspace task list pages and filters in SQL.

GET /v1/tasks used to read the newest ``limit`` rows and then filter by status
and slice by offset in memory, so ``offset`` past the first page returned
nothing and a status filter only ever saw that first page: 49 of 149 tasks
were unreachable. These tests round-trip real rows through the query.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

WORKSPACE = "ws-1"
START = datetime(2026, 9, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: TaskORM.__table__.create(sync_conn))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


def _row(index: int, status: str, **overrides) -> TaskORM:
    fields = {
        "id": uuid4(),
        "agent_id": uuid4(),
        "description": f"task {index}",
        "status": status,
        "workspace_id": WORKSPACE,
        "created_by": "user-1",
        "created_at": START + timedelta(minutes=index),
        "updated_at": START + timedelta(minutes=index),
    }
    fields.update(overrides)
    return TaskORM(**fields)


def _repo(session: AsyncSession) -> TaskRepository:
    return TaskRepository(session, UserContext(user_id="user-1", workspace_id=WORKSPACE))


@pytest.mark.asyncio
async def test_offset_reaches_the_rows_past_the_first_page(session):
    session.add_all(_row(i, "completed") for i in range(5))
    await session.flush()

    page = await _repo(session).list_page(limit=2, offset=4)

    assert [task.description for task in page] == ["task 0"]


@pytest.mark.asyncio
async def test_pages_are_newest_first_and_do_not_overlap(session):
    session.add_all(_row(i, "completed") for i in range(5))
    await session.flush()
    repo = _repo(session)

    first = await repo.list_page(limit=2, offset=0)
    second = await repo.list_page(limit=2, offset=2)

    assert [task.description for task in first] == ["task 4", "task 3"]
    assert [task.description for task in second] == ["task 2", "task 1"]


@pytest.mark.asyncio
async def test_status_filters_before_paging(session):
    """A failure older than the first page of all tasks is still found."""
    session.add(_row(0, "failed"))
    session.add_all(_row(i, "completed") for i in range(1, 5))
    await session.flush()

    page = await _repo(session).list_page(limit=2, offset=0, statuses=["failed"])

    assert [task.description for task in page] == ["task 0"]


@pytest.mark.asyncio
async def test_status_and_offset_combine(session):
    session.add_all(_row(i, "failed" if i % 2 else "completed") for i in range(6))
    await session.flush()

    page = await _repo(session).list_page(limit=2, offset=2, statuses=["failed"])

    assert [task.description for task in page] == ["task 1"]


@pytest.mark.asyncio
async def test_created_by_and_search_narrow_in_sql(session):
    agent_id = uuid4()
    session.add_all(
        [
            _row(0, "completed", description="Write the digest"),
            _row(1, "completed", description="unrelated", agent_id=agent_id),
            _row(2, "completed", description="unrelated"),
            _row(3, "completed", description="digest", created_by="user-2"),
        ]
    )
    await session.flush()
    repo = _repo(session)

    by_text = await repo.list_page(limit=10, offset=0, search="DIGEST", created_by="user-1")
    by_agent = await repo.list_page(limit=10, offset=0, search="digest", agent_ids=[agent_id])

    assert [task.description for task in by_text] == ["Write the digest"]
    assert [task.description for task in by_agent] == ["digest", "unrelated", "Write the digest"]


@pytest.mark.asyncio
async def test_other_workspaces_stay_invisible(session):
    session.add(_row(0, "completed"))
    session.add(_row(1, "completed", workspace_id="ws-2"))
    await session.flush()

    page = await _repo(session).list_page(limit=10, offset=0)

    assert [task.description for task in page] == ["task 0"]


@pytest.mark.asyncio
async def test_several_statuses_match_any_of_them(session):
    session.add_all(
        [_row(0, "pending"), _row(1, "submitted"), _row(2, "running"), _row(3, "preparing")]
    )
    await session.flush()

    page = await _repo(session).list_page(
        limit=10, offset=0, statuses=["pending", "submitted", "preparing"]
    )

    assert [task.description for task in page] == ["task 3", "task 1", "task 0"]
