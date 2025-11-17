"""Unit tests for TaskEventService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.base import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import Task, TaskEvent
from agentarea_tasks.infrastructure.repository import TaskEventRepository, TaskRepository


@pytest.fixture
def mock_repository_factory():
    """Mock repository factory."""
    factory = MagicMock(spec=RepositoryFactory)
    return factory


@pytest.fixture
def mock_event_broker():
    """Mock event broker."""
    broker = MagicMock(spec=EventBroker)
    return broker


@pytest.fixture
def mock_task_event_repository():
    """Mock task event repository."""
    repo = AsyncMock(spec=TaskEventRepository)
    return repo


@pytest.fixture
def mock_task_repository():
    """Mock task repository."""
    repo = AsyncMock(spec=TaskRepository)
    return repo


@pytest.fixture
def task_event_service(mock_repository_factory, mock_event_broker):
    """Create TaskEventService with mocked dependencies."""
    return TaskEventService(mock_repository_factory, mock_event_broker)


@pytest.fixture
def sample_task_event():
    """Sample task event for testing."""
    return TaskEvent(
        id=uuid4(),
        task_id=uuid4(),
        event_type="LLMCallStarted",
        timestamp=datetime.utcnow(),
        data={"model": "gpt-4", "tokens": 150},
        metadata={"source": "workflow"},
        workspace_id="test-workspace",
        created_by="workflow",
    )


class TestTaskEventService:
    """Test cases for TaskEventService."""

    @pytest.mark.asyncio
    async def test_create_workflow_event_success(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        sample_task_event,
    ):
        """Test successful workflow event creation."""
        # Setup
        task_id = uuid4()
        event_type = "LLMCallStarted"
        data = {"model": "gpt-4", "tokens": 150}

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.create_event.return_value = sample_task_event

        # Execute
        result = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id="test-workspace",
            created_by="workflow",
        )

        # Verify
        assert result == sample_task_event
        mock_repository_factory.create_repository.assert_called_once_with(TaskEventRepository)
        mock_task_event_repository.create_event.assert_called_once()

        # Verify the event passed to repository has correct structure
        call_args = mock_task_event_repository.create_event.call_args[0][0]
        assert call_args.task_id == task_id
        assert call_args.event_type == event_type
        assert call_args.data == data
        assert call_args.workspace_id == "test-workspace"
        assert call_args.created_by == "workflow"

    @pytest.mark.asyncio
    async def test_create_workflow_event_with_defaults(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        mock_task_repository,
        sample_task_event,
    ):
        """Test workflow event creation with default parameters."""
        # Setup
        task_id = uuid4()
        event_type = "TaskCompleted"
        data = {"result": "success"}

        # Mock task repository to return a task with workspace_id and user_id
        mock_task = Task(
            id=task_id,
            agent_id=uuid4(),
            description="Test task",
            parameters={},
            status="running",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            workspace_id="default",
            user_id="workflow",
        )
        mock_task_repository.get_task = AsyncMock(return_value=mock_task)

        # Configure factory to return appropriate repository based on type
        def create_repo(repo_type):
            if repo_type == TaskRepository:
                return mock_task_repository
            elif repo_type == TaskEventRepository:
                return mock_task_event_repository
            return None

        mock_repository_factory.create_repository.side_effect = create_repo
        mock_task_event_repository.create_event.return_value = sample_task_event

        # Execute (using defaults for workspace_id and created_by)
        result = await task_event_service.create_workflow_event(
            task_id=task_id, event_type=event_type, data=data
        )

        # Verify
        assert result == sample_task_event
        call_args = mock_task_event_repository.create_event.call_args[0][0]
        assert call_args.workspace_id == "default"
        assert call_args.created_by == "workflow"

    @pytest.mark.asyncio
    async def test_create_workflow_event_repository_error(
        self, task_event_service, mock_repository_factory, mock_task_event_repository, mock_task_repository
    ):
        """Test handling of repository errors during event creation."""
        # Setup
        task_id = uuid4()
        event_type = "LLMCallFailed"
        data = {"error": "API timeout"}

        # Mock task repository to return a task
        mock_task = Task(
            id=task_id,
            agent_id=uuid4(),
            description="Test task",
            parameters={},
            status="running",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            workspace_id="test-workspace",
            user_id="test-user",
        )
        mock_task_repository.get_task = AsyncMock(return_value=mock_task)

        # Configure factory to return appropriate repository based on type
        def create_repo(repo_type):
            if repo_type == TaskRepository:
                return mock_task_repository
            elif repo_type == TaskEventRepository:
                return mock_task_event_repository
            return None

        mock_repository_factory.create_repository.side_effect = create_repo
        mock_task_event_repository.create_event.side_effect = Exception("Database error")

        # Execute & Verify
        with pytest.raises(Exception, match="Database error"):
            await task_event_service.create_workflow_event(
                task_id=task_id, event_type=event_type, data=data
            )

    @pytest.mark.asyncio
    async def test_get_task_events(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        sample_task_event,
    ):
        """Test retrieving events for a specific task."""
        # Setup
        task_id = uuid4()
        expected_events = [sample_task_event]

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.get_events_for_task.return_value = expected_events

        # Execute
        result = await task_event_service.get_task_events(task_id, limit=50, offset=10)

        # Verify
        assert result == expected_events
        mock_task_event_repository.get_events_for_task.assert_called_once_with(task_id, 50, 10)

    @pytest.mark.asyncio
    async def test_get_events_by_type(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        sample_task_event,
    ):
        """Test retrieving events by type."""
        # Setup
        event_type = "LLMCallStarted"
        expected_events = [sample_task_event]

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.get_events_by_type.return_value = expected_events

        # Execute
        result = await task_event_service.get_events_by_type(event_type, limit=25, offset=5)

        # Verify
        assert result == expected_events
        mock_task_event_repository.get_events_by_type.assert_called_once_with(event_type, 25, 5)

    @pytest.mark.asyncio
    async def test_create_multiple_events_success(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        sample_task_event,
    ):
        """Test creating multiple events successfully."""
        # Setup
        events_data = [
            {
                "task_id": str(uuid4()),
                "event_type": "LLMCallStarted",
                "data": {"model": "gpt-4"},
                "workspace_id": "test-workspace",
                "created_by": "workflow",
            },
            {
                "task_id": str(uuid4()),
                "event_type": "LLMCallCompleted",
                "data": {"tokens": 150},
                "workspace_id": "test-workspace",
                "created_by": "workflow",
            },
        ]

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.create_event.return_value = sample_task_event

        # Execute
        result = await task_event_service.create_multiple_events(events_data)

        # Verify
        assert len(result) == 2
        assert all(event == sample_task_event for event in result)
        assert mock_task_event_repository.create_event.call_count == 2

    @pytest.mark.asyncio
    async def test_create_multiple_events_partial_failure(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        mock_task_repository,
        sample_task_event,
    ):
        """Test creating multiple events with some failures."""
        # Setup
        task_id_1 = uuid4()
        task_id_3 = uuid4()
        events_data = [
            {
                "task_id": str(task_id_1),
                "event_type": "LLMCallStarted",
                "data": {"model": "gpt-4"},
                "workspace_id": "test-workspace",
                "created_by": "workflow",
            },
            {
                "task_id": "invalid-uuid",  # This will cause an error
                "event_type": "LLMCallCompleted",
                "data": {"tokens": 150},
            },
            {
                "task_id": str(task_id_3),
                "event_type": "TaskCompleted",
                "data": {"result": "success"},
                "workspace_id": "test-workspace",
                "created_by": "workflow",
            },
        ]

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.create_event.return_value = sample_task_event

        # Execute
        result = await task_event_service.create_multiple_events(events_data)

        # Verify - should have 2 successful events (first and third)
        assert len(result) == 2
        assert all(event == sample_task_event for event in result)


class TestTaskEventDomainModel:
    """Test cases for TaskEvent domain model."""

    def test_task_event_creation(self):
        """Test TaskEvent model creation with valid data."""
        task_id = uuid4()
        event_id = uuid4()
        timestamp = datetime.utcnow()

        event = TaskEvent(
            id=event_id,
            task_id=task_id,
            event_type="LLMCallStarted",
            timestamp=timestamp,
            data={"model": "gpt-4", "tokens": 150},
            metadata={"source": "workflow"},
            workspace_id="test-workspace",
            created_by="workflow",
        )

        assert event.id == event_id
        assert event.task_id == task_id
        assert event.event_type == "LLMCallStarted"
        assert event.timestamp == timestamp
        assert event.data == {"model": "gpt-4", "tokens": 150}
        assert event.metadata == {"source": "workflow"}
        assert event.workspace_id == "test-workspace"
        assert event.created_by == "workflow"

    def test_create_workflow_event_factory_method(self):
        """Test TaskEvent.create_workflow_event factory method."""
        task_id = uuid4()
        event_type = "LLMCallStarted"
        data = {"model": "gpt-4", "tokens": 150}
        workspace_id = "test-workspace"
        created_by = "workflow"

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id=workspace_id,
            created_by=created_by,
        )

        assert event.task_id == task_id
        assert event.event_type == event_type
        assert event.data == data
        assert event.workspace_id == workspace_id
        assert event.created_by == created_by
        assert isinstance(event.id, UUID)
        assert isinstance(event.timestamp, datetime)
        assert "source" in event.metadata
        assert event.metadata["source"] == "workflow"

    def test_create_workflow_event_with_defaults(self):
        """Test TaskEvent.create_workflow_event with default parameters."""
        task_id = uuid4()
        event_type = "TaskCompleted"
        data = {"result": "success"}

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id="default",
            created_by="workflow",
        )

        assert event.workspace_id == "default"
        assert event.created_by == "workflow"
        assert event.metadata["source"] == "workflow"
