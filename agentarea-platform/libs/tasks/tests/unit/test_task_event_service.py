"""Unit tests for TaskEventService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.base import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import TaskEvent
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
        task_id = uuid4()
        event_type = "LLMCallStarted"
        data = {"model": "gpt-4", "tokens": 150}

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.create_event.return_value = sample_task_event

        result = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id="test-workspace",
            created_by="workflow",
        )

        assert result == sample_task_event
        mock_repository_factory.create_repository.assert_called_once_with(TaskEventRepository)
        mock_task_event_repository.create_event.assert_called_once()

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
        task_id = uuid4()
        event_type = "TaskCompleted"
        data = {"result": "success"}

        mock_repository_factory.create_repository.side_effect = [
            mock_task_event_repository,
            mock_task_repository,
        ]
        mock_task_event_repository.create_event.return_value = sample_task_event

        result = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id="test-workspace",
            created_by="workflow",
        )

        assert result == sample_task_event
        assert mock_repository_factory.create_repository.call_count == 1

