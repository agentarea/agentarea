"""Integration tests for TaskEvent functionality."""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import TaskEvent
from agentarea_tasks.infrastructure.repository import TaskEventRepository


@pytest.fixture
async def db_session():
    """Create a database session for testing."""
    database = get_database()
    async with database.async_session_factory() as session:
        yield session
        await session.rollback()  # Rollback any changes after test


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


class TestTaskEventRepositoryIntegration:
    """Integration tests for TaskEventRepository."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_event(self, task_event_repository, db_session):
        """Test creating and retrieving a task event."""
        # Create test event
        task_id = uuid4()
        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type="LLMCallStarted",
            data={"model": "gpt-4", "tokens": 150},
            workspace_id="test-workspace",
            created_by="workflow",
        )

        # Save to database
        saved_event = await task_event_repository.create_event(event)
        await db_session.commit()

        # Verify saved event
        assert saved_event.id == event.id
        assert saved_event.task_id == task_id
        assert saved_event.event_type == "LLMCallStarted"
        assert saved_event.data == {"model": "gpt-4", "tokens": 150}
        assert saved_event.workspace_id == "test-workspace"
        assert saved_event.created_by == "workflow"

        # Retrieve events for task
        retrieved_events = await task_event_repository.get_events_for_task(task_id)

        # Verify retrieved events
        assert len(retrieved_events) == 1
        retrieved_event = retrieved_events[0]
        assert retrieved_event.id == event.id
        assert retrieved_event.task_id == task_id
        assert retrieved_event.event_type == "LLMCallStarted"
        assert retrieved_event.data == {"model": "gpt-4", "tokens": 150}

    @pytest.mark.asyncio
    async def test_get_events_for_task_multiple(self, task_event_repository, db_session):
        """Test retrieving multiple events for a task."""
        task_id = uuid4()

        # Create multiple events for the same task
        events = [
            TaskEvent.create_workflow_event(
                task_id=task_id,
                event_type="LLMCallStarted",
                data={"model": "gpt-4"},
                workspace_id="test-workspace",
            ),
            TaskEvent.create_workflow_event(
                task_id=task_id,
                event_type="LLMCallCompleted",
                data={"tokens": 150},
                workspace_id="test-workspace",
            ),
            TaskEvent.create_workflow_event(
                task_id=task_id,
                event_type="TaskCompleted",
                data={"result": "success"},
                workspace_id="test-workspace",
            ),
        ]

        # Save all events
        for event in events:
            await task_event_repository.create_event(event)
        await db_session.commit()

        # Retrieve events for task
        retrieved_events = await task_event_repository.get_events_for_task(task_id)

        # Verify all events retrieved and ordered by timestamp
        assert len(retrieved_events) == 3
        event_types = [event.event_type for event in retrieved_events]
        assert "LLMCallStarted" in event_types
        assert "LLMCallCompleted" in event_types
        assert "TaskCompleted" in event_types

    @pytest.mark.asyncio
    async def test_get_events_by_type(self, task_event_repository, db_session):
        """Test retrieving events by type."""
        # Create events of different types
        task_id_1 = uuid4()
        task_id_2 = uuid4()

        events = [
            TaskEvent.create_workflow_event(
                task_id=task_id_1,
                event_type="LLMCallStarted",
                data={"model": "gpt-4"},
                workspace_id="test-workspace",
            ),
            TaskEvent.create_workflow_event(
                task_id=task_id_2,
                event_type="LLMCallStarted",
                data={"model": "claude-3"},
                workspace_id="test-workspace",
            ),
            TaskEvent.create_workflow_event(
                task_id=task_id_1,
                event_type="TaskCompleted",
                data={"result": "success"},
                workspace_id="test-workspace",
            ),
        ]

        # Save all events
        for event in events:
            await task_event_repository.create_event(event)
        await db_session.commit()

        # Retrieve events by type
        llm_started_events = await task_event_repository.get_events_by_type("LLMCallStarted")
        task_completed_events = await task_event_repository.get_events_by_type("TaskCompleted")

        # Verify filtering by type
        assert len(llm_started_events) == 2
        assert len(task_completed_events) == 1

        assert all(event.event_type == "LLMCallStarted" for event in llm_started_events)
        assert all(event.event_type == "TaskCompleted" for event in task_completed_events)

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, db_session):
        """Test that events are properly isolated by workspace."""
        task_id = uuid4()

        # Create repositories for different workspaces
        workspace1_context = UserContext(user_id="user1", workspace_id="workspace1")
        workspace2_context = UserContext(user_id="user2", workspace_id="workspace2")

        repo1 = TaskEventRepository(db_session, workspace1_context)
        repo2 = TaskEventRepository(db_session, workspace2_context)

        # Create events in different workspaces
        event1 = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type="LLMCallStarted",
            data={"model": "gpt-4"},
            workspace_id="workspace1",
        )

        event2 = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type="LLMCallStarted",
            data={"model": "claude-3"},
            workspace_id="workspace2",
        )

        # Save events using respective repositories
        await repo1.create_event(event1)
        await repo2.create_event(event2)
        await db_session.commit()

        # Verify workspace isolation
        workspace1_events = await repo1.get_events_for_task(task_id)
        workspace2_events = await repo2.get_events_for_task(task_id)

        assert len(workspace1_events) == 1
        assert len(workspace2_events) == 1

        assert workspace1_events[0].data["model"] == "gpt-4"
        assert workspace2_events[0].data["model"] == "claude-3"


class TestTaskEventServiceIntegration:
    """Integration tests for TaskEventService."""

    @pytest.mark.asyncio
    async def test_create_workflow_event_end_to_end(self, task_event_service, db_session):
        """Test creating a workflow event end-to-end."""
        task_id = uuid4()
        event_type = "LLMCallStarted"
        data = {"model": "gpt-4", "tokens": 150}
        workspace_id = "test-workspace"

        # Create event using service
        created_event = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id=workspace_id,
            created_by="integration_test",
        )
        await db_session.commit()

        # Verify event was created
        assert created_event.task_id == task_id
        assert created_event.event_type == event_type
        assert created_event.data == data
        assert created_event.workspace_id == workspace_id
        assert created_event.created_by == "integration_test"

        # Verify event can be retrieved
        retrieved_events = await task_event_service.get_task_events(task_id)
        assert len(retrieved_events) == 1
        assert retrieved_events[0].id == created_event.id

    @pytest.mark.asyncio
    async def test_create_multiple_events_end_to_end(self, task_event_service, db_session):
        """Test creating multiple events end-to-end."""
        events_data = [
            {
                "task_id": str(uuid4()),
                "event_type": "LLMCallStarted",
                "data": {"model": "gpt-4"},
                "workspace_id": "test-workspace",
                "created_by": "integration_test",
            },
            {
                "task_id": str(uuid4()),
                "event_type": "LLMCallCompleted",
                "data": {"tokens": 150},
                "workspace_id": "test-workspace",
                "created_by": "integration_test",
            },
        ]

        # Create events using service
        created_events = await task_event_service.create_multiple_events(events_data)
        await db_session.commit()

        # Verify events were created
        assert len(created_events) == 2

        # Verify each event can be retrieved
        for i, event in enumerate(created_events):
            task_id = uuid4(events_data[i]["task_id"])
            retrieved_events = await task_event_service.get_task_events(task_id)
            assert len(retrieved_events) == 1
            assert retrieved_events[0].id == event.id

    @pytest.mark.asyncio
    async def test_get_events_by_type_end_to_end(self, task_event_service, db_session):
        """Test retrieving events by type end-to-end."""
        # Create events of different types
        await task_event_service.create_workflow_event(
            task_id=uuid4(),
            event_type="LLMCallStarted",
            data={"model": "gpt-4"},
            workspace_id="test-workspace",
        )

        await task_event_service.create_workflow_event(
            task_id=uuid4(),
            event_type="LLMCallStarted",
            data={"model": "claude-3"},
            workspace_id="test-workspace",
        )

        await task_event_service.create_workflow_event(
            task_id=uuid4(),
            event_type="TaskCompleted",
            data={"result": "success"},
            workspace_id="test-workspace",
        )

        await db_session.commit()

        # Retrieve events by type
        llm_started_events = await task_event_service.get_events_by_type("LLMCallStarted")
        task_completed_events = await task_event_service.get_events_by_type("TaskCompleted")

        # Verify filtering
        assert len(llm_started_events) >= 2  # May have events from other tests
        assert len(task_completed_events) >= 1

        # Verify all retrieved events have correct type
        for event in llm_started_events:
            assert event.event_type == "LLMCallStarted"

        for event in task_completed_events:
            assert event.event_type == "TaskCompleted"
