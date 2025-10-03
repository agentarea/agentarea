"""Unit tests for TaskEventHandler."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_event_handler import TaskEventHandler


@pytest.fixture
def mock_task_repository():
    """Create a mock task repository."""
    return AsyncMock()


@pytest.fixture
def mock_event_broker():
    """Create a mock event broker."""
    return AsyncMock()


@pytest.fixture
def task_event_handler(mock_task_repository, mock_event_broker):
    """Create a TaskEventHandler instance with mocked dependencies."""
    return TaskEventHandler(
        task_repository=mock_task_repository,
        event_broker=mock_event_broker,
    )


@pytest.fixture
def sample_task():
    """Create a sample task for testing."""
    return SimpleTask(
        id=uuid4(),
        title="Test Task",
        description="Test description",
        query="Test query",
        user_id="user123",
        agent_id=uuid4(),
        status="working",
    )


@pytest.mark.asyncio
async def test_setup_event_listeners(task_event_handler, mock_event_broker):
    """Test that event listeners are set up correctly."""
    await task_event_handler.setup_event_listeners()

    # Verify all event subscriptions were called
    assert mock_event_broker.subscribe.call_count == 3

    # Check specific subscription calls
    subscribe_calls = [call[0] for call in mock_event_broker.subscribe.call_args_list]
    event_types = [call[0] for call in subscribe_calls]

    assert "TaskStatusChanged" in event_types
    assert "TaskCompleted" in event_types
    assert "TaskFailed" in event_types


@pytest.mark.asyncio
async def test_handle_task_status_changed(task_event_handler, mock_task_repository, sample_task):
    """Test handling TaskStatusChanged events."""
    # Setup
    mock_task_repository.get.return_value = sample_task
    mock_task_repository.update.return_value = sample_task

    # Create mock event
    mock_event = Mock()
    mock_event.task_id = str(sample_task.id)
    mock_event.new_status = Mock()
    mock_event.new_status.value = "RUNNING"

    # Execute
    await task_event_handler.handle_task_status_changed(mock_event)

    # Verify
    mock_task_repository.get.assert_called_once_with(sample_task.id)
    mock_task_repository.update.assert_called_once()

    # Check that task status was updated
    updated_task = mock_task_repository.update.call_args[0][0]
    assert updated_task.status == "running"


@pytest.mark.asyncio
async def test_handle_task_status_changed_string_status(
    task_event_handler, mock_task_repository, sample_task
):
    """Test handling TaskStatusChanged events with string status."""
    # Setup
    mock_task_repository.get.return_value = sample_task
    mock_task_repository.update.return_value = sample_task

    # Create mock event with string status
    mock_event = Mock()
    mock_event.task_id = str(sample_task.id)
    mock_event.new_status = "COMPLETED"

    # Execute
    await task_event_handler.handle_task_status_changed(mock_event)

    # Verify
    updated_task = mock_task_repository.update.call_args[0][0]
    assert updated_task.status == "completed"


@pytest.mark.asyncio
async def test_handle_task_completed(task_event_handler, mock_task_repository, sample_task):
    """Test handling TaskCompleted events."""
    # Setup
    mock_task_repository.get.return_value = sample_task
    mock_task_repository.update.return_value = sample_task

    # Create mock event
    mock_event = Mock()
    mock_event.task_id = str(sample_task.id)
    mock_event.result = {"answer": "Task completed successfully"}

    # Execute
    await task_event_handler.handle_task_completed(mock_event)

    # Verify
    mock_task_repository.get.assert_called_once_with(sample_task.id)
    mock_task_repository.update.assert_called_once()

    # Check that task was marked as completed with result
    updated_task = mock_task_repository.update.call_args[0][0]
    assert updated_task.status == "completed"
    assert updated_task.result == {"answer": "Task completed successfully"}


@pytest.mark.asyncio
async def test_handle_task_failed(task_event_handler, mock_task_repository, sample_task):
    """Test handling TaskFailed events."""
    # Setup
    mock_task_repository.get.return_value = sample_task
    mock_task_repository.update.return_value = sample_task

    # Create mock event
    mock_event = Mock()
    mock_event.task_id = str(sample_task.id)
    mock_event.error_message = "Agent execution failed"

    # Execute
    await task_event_handler.handle_task_failed(mock_event)

    # Verify
    mock_task_repository.get.assert_called_once_with(sample_task.id)
    mock_task_repository.update.assert_called_once()

    # Check that task was marked as failed with error
    updated_task = mock_task_repository.update.call_args[0][0]
    assert updated_task.status == "failed"
    assert updated_task.error_message == "Agent execution failed"


@pytest.mark.asyncio
async def test_handle_task_not_found(task_event_handler, mock_task_repository):
    """Test handling events for non-existent tasks."""
    # Setup
    mock_task_repository.get.return_value = None

    # Create mock event
    mock_event = Mock()
    mock_event.task_id = str(uuid4())
    mock_event.new_status = "COMPLETED"

    # Execute
    await task_event_handler.handle_task_status_changed(mock_event)

    # Verify - should not call update when task not found
    mock_task_repository.get.assert_called_once()
    mock_task_repository.update.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_with_exception(task_event_handler, mock_task_repository, sample_task):
    """Test that exceptions in event handlers are caught and logged."""
    # Setup
    mock_task_repository.get.side_effect = Exception("Database error")

    # Create mock event
    mock_event = Mock()
    mock_event.task_id = str(sample_task.id)
    mock_event.new_status = "COMPLETED"

    # Execute - should not raise exception
    await task_event_handler.handle_task_status_changed(mock_event)

    # Verify repository was called despite error
    mock_task_repository.get.assert_called_once()
