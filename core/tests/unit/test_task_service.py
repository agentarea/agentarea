"""
Unit Tests for TaskService
==========================

Tests TaskService methods in isolation using mocks.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agentarea.modules.tasks.domain.models import Task, TaskPriority, TaskType
from agentarea.modules.tasks.task_service import TaskService


class TestTaskService:
    """Unit tests for TaskService"""

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker"""
        return AsyncMock()

    @pytest.fixture
    def task_service(self, mock_event_broker):
        """Create TaskService with mocked event broker"""
        return TaskService(event_broker=mock_event_broker)

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing"""
        return uuid4()

    @patch("agentarea.modules.tasks.task_service.TaskFactory")
    async def test_create_and_start_test_task_success(
        self, mock_task_factory, task_service, mock_event_broker, sample_agent_id
    ):
        """Test successful creation and starting of test task"""
        # Setup mock task
        mock_task = Task(
            id="test-task-123",
            agent_id=sample_agent_id,
            description="Test task for agent",
            task_type=TaskType.TEST,
            priority=TaskPriority.MEDIUM,
            parameters={"test": True},
            metadata={"created_by": "test"},
        )
        mock_task_factory.create_test_task.return_value = mock_task

        # Execute
        result = await task_service.create_and_start_test_task(sample_agent_id)

        # Verify
        assert result == mock_task
        mock_task_factory.create_test_task.assert_called_once_with(sample_agent_id)
        mock_event_broker.publish.assert_called_once()

        # Verify the published event
        published_event = mock_event_broker.publish.call_args[0][0]
        assert published_event.task_id == mock_task.id
        assert published_event.agent_id == sample_agent_id
        assert published_event.description == mock_task.description

    @patch("agentarea.modules.tasks.task_service.TaskFactory")
    async def test_create_and_start_test_task_factory_error(
        self, mock_task_factory, task_service, mock_event_broker, sample_agent_id
    ):
        """Test handling of TaskFactory error"""
        # Setup mock to raise exception
        mock_task_factory.create_test_task.side_effect = Exception("Task creation failed")

        # Execute and verify exception is raised
        with pytest.raises(Exception) as exc_info:
            await task_service.create_and_start_test_task(sample_agent_id)

        assert str(exc_info.value) == "Task creation failed"
        mock_task_factory.create_test_task.assert_called_once_with(sample_agent_id)
        mock_event_broker.publish.assert_not_called()

    @patch("agentarea.modules.tasks.task_service.TaskFactory")
    async def test_create_and_start_test_task_event_publish_error(
        self, mock_task_factory, task_service, mock_event_broker, sample_agent_id
    ):
        """Test handling of event publishing error"""
        # Setup mock task
        mock_task = Task(
            id="test-task-123",
            agent_id=sample_agent_id,
            description="Test task for agent",
            task_type=TaskType.TEST,
            priority=TaskPriority.MEDIUM,
            parameters={"test": True},
            metadata={"created_by": "test"},
        )
        mock_task_factory.create_test_task.return_value = mock_task

        # Setup event broker to raise exception
        mock_event_broker.publish.side_effect = Exception("Event publishing failed")

        # Execute and verify exception is raised
        with pytest.raises(Exception) as exc_info:
            await task_service.create_and_start_test_task(sample_agent_id)

        assert str(exc_info.value) == "Event publishing failed"
        mock_task_factory.create_test_task.assert_called_once_with(sample_agent_id)
        mock_event_broker.publish.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
