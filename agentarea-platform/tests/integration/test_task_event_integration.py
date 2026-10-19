"""The legacy ``task_events`` write path against a migrated database.

Runs from before the task log still store their events here; nothing reads
them back through the repository any more (the feed reads the task log), so
these tests read the stored rows directly.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config.database import DatabaseSettings
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import TaskEvent
from agentarea_tasks.infrastructure.orm import TaskEventORM
from agentarea_tasks.infrastructure.repository import TaskEventRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.integration, pytest.mark.golden]


@pytest_asyncio.fixture
async def db_session():
    """Create a database session for testing.

    Uses a fresh, function-scoped engine instead of the process-wide
    get_database() singleton. asyncio_mode=auto gives each test its own
    event loop by default; the singleton's pooled asyncpg connections
    stay bound to whichever loop first created them, so reusing it across
    tests raised "Future attached to a different loop" / "Event loop is
    closed" once an earlier test's loop had already closed. NullPool opens
    a fresh connection per checkout and the engine is disposed at the end
    of this same test, so it never outlives its own loop.
    """
    settings = DatabaseSettings()
    engine = create_async_engine(settings.url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session
        await session.rollback()  # Rollback any changes after test

    await engine.dispose()


@pytest.fixture
def user_context():
    """Create a test user context."""
    return UserContext(user_id="test-user", workspace_id="test-workspace")


@pytest.fixture
def repository_factory(db_session, user_context):
    """Create a repository factory for testing."""
    return RepositoryFactory(db_session, user_context)


@pytest.fixture
def task_event_repository(db_session, user_context):
    """Create a TaskEventRepository for testing."""
    return TaskEventRepository(db_session, user_context)


@pytest.fixture
def task_event_service(repository_factory):
    """Create a TaskEventService for testing."""
    return TaskEventService(repository_factory, None)  # No event broker needed for these tests


async def _stored(session, task_id, workspace_id):
    rows = await session.scalars(
        select(TaskEventORM)
        .where(TaskEventORM.task_id == task_id, TaskEventORM.workspace_id == workspace_id)
        .order_by(TaskEventORM.timestamp)
    )
    return list(rows.all())


def _event(task_id, event_type, data, workspace_id="test-workspace", created_by="test_user"):
    return TaskEvent.create_workflow_event(
        task_id=task_id,
        event_id=uuid4(),
        event_type=event_type,
        timestamp=datetime.now(UTC),
        data=data,
        workspace_id=workspace_id,
        created_by=created_by,
    )


class TestTaskEventRepositoryIntegration:
    @pytest.mark.asyncio
    async def test_create_event_stores_the_row(self, task_event_repository, db_session):
        task_id = uuid4()
        event = _event(
            task_id, "llm.call.started", {"model": "gpt-4", "tokens": 150}, created_by="workflow"
        )

        saved = await task_event_repository.create_event(event)
        await db_session.commit()

        assert (saved.id, saved.task_id, saved.event_type) == (
            event.id,
            task_id,
            "llm.call.started",
        )
        assert saved.data == {"model": "gpt-4", "tokens": 150}
        assert (saved.workspace_id, saved.created_by) == ("test-workspace", "workflow")
        [row] = await _stored(db_session, task_id, "test-workspace")
        assert (row.id, row.event_type, row.data) == (event.id, "llm.call.started", event.data)

    @pytest.mark.asyncio
    async def test_a_repeated_event_is_stored_once(self, task_event_repository, db_session):
        task_id = uuid4()
        event = _event(task_id, "task.completed", {"result": "success"})

        await task_event_repository.create_event(event)
        await task_event_repository.create_event(event)
        await db_session.commit()

        assert [row.id for row in await _stored(db_session, task_id, "test-workspace")] == [
            event.id
        ]

    @pytest.mark.asyncio
    async def test_each_workspace_stores_its_own_events(self, db_session):
        task_id = uuid4()
        repo1 = TaskEventRepository(
            db_session, UserContext(user_id="user1", workspace_id="workspace1")
        )
        repo2 = TaskEventRepository(
            db_session, UserContext(user_id="user2", workspace_id="workspace2")
        )

        await repo1.create_event(
            _event(task_id, "llm.call.started", {"model": "gpt-4"}, "workspace1")
        )
        await repo2.create_event(
            _event(task_id, "llm.call.started", {"model": "claude-3"}, "workspace2")
        )
        await db_session.commit()

        [one] = await _stored(db_session, task_id, "workspace1")
        [two] = await _stored(db_session, task_id, "workspace2")
        assert (one.data["model"], two.data["model"]) == ("gpt-4", "claude-3")

    @pytest.mark.asyncio
    async def test_an_event_of_another_workspace_is_refused(self, task_event_repository):
        with pytest.raises(ValueError, match="not test-workspace"):
            await task_event_repository.create_event(
                _event(uuid4(), "llm.call.started", {}, workspace_id="someone-else")
            )


class TestTaskEventServiceIntegration:
    @pytest.mark.asyncio
    async def test_create_workflow_event_end_to_end(self, task_event_service, db_session):
        task_id = uuid4()
        data = {"model": "gpt-4", "tokens": 150}

        created = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_id=uuid4(),
            event_type="llm.call.started",
            timestamp=datetime.now(UTC),
            data=data,
            workspace_id="test-workspace",
            created_by="integration_test",
        )
        await db_session.commit()

        assert (created.task_id, created.event_type, created.data) == (
            task_id,
            "llm.call.started",
            data,
        )
        assert (created.workspace_id, created.created_by) == ("test-workspace", "integration_test")
        [row] = await _stored(db_session, task_id, "test-workspace")
        assert row.id == created.id
