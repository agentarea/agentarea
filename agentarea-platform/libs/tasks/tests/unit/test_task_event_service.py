"""Unit tests for TaskEventService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.base import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import TaskEvent
from agentarea_tasks.infrastructure.repository import TaskEventRepository


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
    async def test_create_workflow_event_keeps_the_workflow_identity(
        self,
        task_event_service,
        mock_repository_factory,
        mock_task_event_repository,
        sample_task_event,
    ):
        """The stored row carries the id and timestamp the workflow minted."""
        task_id, event_id = uuid4(), uuid4()
        minted_at = datetime(2026, 9, 29, 12, 0, 0, 654321, tzinfo=UTC)
        data = {"model": "gpt-4", "tokens": 150}

        mock_repository_factory.create_repository.return_value = mock_task_event_repository
        mock_task_event_repository.create_event.return_value = sample_task_event

        result = await task_event_service.create_workflow_event(
            task_id=task_id,
            event_id=event_id,
            event_type="llm.call.started",
            data=data,
            timestamp=minted_at,
            workspace_id="test-workspace",
            created_by="workflow",
        )

        assert result == sample_task_event
        mock_repository_factory.create_repository.assert_called_once_with(TaskEventRepository)
        event = mock_task_event_repository.create_event.call_args[0][0]
        assert event.id == event_id
        assert event.timestamp == minted_at
        assert event.task_id == task_id
        assert event.event_type == "llm.call.started"
        assert event.data == data
        assert event.workspace_id == "test-workspace"
        assert event.created_by == "workflow"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("workspace_id", "created_by", "missing"),
        [("", "workflow", "workspace_id"), ("test-workspace", "", "created_by")],
    )
    async def test_create_workflow_event_requires_attribution(
        self,
        task_event_service,
        mock_repository_factory,
        workspace_id,
        created_by,
        missing,
    ):
        with pytest.raises(ValueError, match=missing):
            await task_event_service.create_workflow_event(
                task_id=uuid4(),
                event_id=uuid4(),
                event_type="task.completed",
                data={},
                timestamp=datetime.now(UTC),
                workspace_id=workspace_id,
                created_by=created_by,
            )

        mock_repository_factory.create_repository.assert_not_called()
