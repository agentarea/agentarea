"""
Integration tests for SQLAlchemyTaskRepository.

Tests all CRUD operations and custom task-specific methods.
"""

from uuid import uuid4

import pytest

from agentarea.modules.tasks.domain.models import TaskStatus
from agentarea.modules.tasks.infrastructure.repository import SQLAlchemyTaskRepository


class TestTaskRepository:
    """Test cases for SQLAlchemyTaskRepository."""

    @pytest.mark.asyncio
    async def test_create_task(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test creating a new task."""
        # Arrange
        task = model_factory.create_task()

        # Act
        created_task = await task_repository.create(task)

        # Assert
        assert created_task is not None
        assert created_task.id == task.id
        assert created_task.session_id == task.session_id
        assert created_task.agent_id == task.agent_id
        assert created_task.status == task.status
        assert created_task.description == task.description
        assert created_task.parameters == task.parameters
        assert created_task.result == task.result
        assert created_task.error == task.error

    @pytest.mark.asyncio
    async def test_get_task_by_id(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test retrieving a task by ID."""
        # Arrange
        task = model_factory.create_task()
        created_task = await task_repository.create(task)

        # Act
        retrieved_task = await task_repository.get(created_task.id)

        # Assert
        assert retrieved_task is not None
        assert retrieved_task.id == created_task.id
        assert retrieved_task.session_id == created_task.session_id
        assert retrieved_task.agent_id == created_task.agent_id
        assert retrieved_task.status == created_task.status

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, task_repository: SQLAlchemyTaskRepository):
        """Test getting a non-existent task returns None."""
        # Arrange
        nonexistent_id = str(uuid4())

        # Act
        result = await task_repository.get(nonexistent_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, task_repository: SQLAlchemyTaskRepository):
        """Test listing tasks when none exist."""
        # Act
        tasks = await task_repository.list()

        # Assert
        assert tasks == []

    @pytest.mark.asyncio
    async def test_list_tasks_with_data(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test listing tasks when some exist."""
        # Arrange
        task1 = model_factory.create_task(description="Task 1")
        task2 = model_factory.create_task(description="Task 2")
        task3 = model_factory.create_task(description="Task 3")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        tasks = await task_repository.list()

        # Assert
        assert len(tasks) == 3
        task_descriptions = [task.description for task in tasks]
        assert "Task 1" in task_descriptions
        assert "Task 2" in task_descriptions
        assert "Task 3" in task_descriptions

    @pytest.mark.asyncio
    async def test_update_task(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test updating an existing task."""
        # Arrange
        task = model_factory.create_task(
            description="Original description", status=TaskStatus.CREATED
        )
        created_task = await task_repository.create(task)

        # Modify the task
        created_task.description = "Updated description"
        created_task.status = TaskStatus.RUNNING
        created_task.result = {"output": "test result"}

        # Act
        updated_task = await task_repository.update(created_task)

        # Assert
        assert updated_task.id == created_task.id
        assert updated_task.description == "Updated description"
        assert updated_task.status == TaskStatus.RUNNING
        assert updated_task.result == {"output": "test result"}

        # Verify the update persisted
        retrieved_task = await task_repository.get(created_task.id)
        assert retrieved_task.description == "Updated description"
        assert retrieved_task.status == TaskStatus.RUNNING
        assert retrieved_task.result == {"output": "test result"}

    @pytest.mark.asyncio
    async def test_delete_task(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test deleting an existing task."""
        # Arrange
        task = model_factory.create_task()
        created_task = await task_repository.create(task)

        # Verify task exists
        retrieved_task = await task_repository.get(created_task.id)
        assert retrieved_task is not None

        # Act
        delete_result = await task_repository.delete(created_task.id)

        # Assert
        assert delete_result is True

        # Verify task no longer exists
        deleted_task = await task_repository.get(created_task.id)
        assert deleted_task is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, task_repository: SQLAlchemyTaskRepository):
        """Test deleting a non-existent task returns False."""
        # Arrange
        nonexistent_id = str(uuid4())

        # Act
        result = await task_repository.delete(nonexistent_id)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_find_by_session_id(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test finding tasks by session ID."""
        # Arrange
        session_id = f"session-{uuid4().hex[:8]}"
        other_session_id = f"session-{uuid4().hex[:8]}"

        task1 = model_factory.create_task(session_id=session_id, description="Task 1")
        task2 = model_factory.create_task(session_id=session_id, description="Task 2")
        task3 = model_factory.create_task(session_id=other_session_id, description="Task 3")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        session_tasks = await task_repository.find_by_session_id(session_id)

        # Assert
        assert len(session_tasks) == 2
        session_task_descriptions = [task.description for task in session_tasks]
        assert "Task 1" in session_task_descriptions
        assert "Task 2" in session_task_descriptions
        assert "Task 3" not in session_task_descriptions

        # Verify all tasks have correct session_id
        for task in session_tasks:
            assert task.session_id == session_id

    @pytest.mark.asyncio
    async def test_find_by_agent_id(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test finding tasks by agent ID."""
        # Arrange
        agent_id = str(uuid4())
        other_agent_id = str(uuid4())

        task1 = model_factory.create_task(agent_id=agent_id, description="Task 1")
        task2 = model_factory.create_task(agent_id=agent_id, description="Task 2")
        task3 = model_factory.create_task(agent_id=other_agent_id, description="Task 3")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        agent_tasks = await task_repository.find_by_agent_id(agent_id)

        # Assert
        assert len(agent_tasks) == 2
        agent_task_descriptions = [task.description for task in agent_tasks]
        assert "Task 1" in agent_task_descriptions
        assert "Task 2" in agent_task_descriptions
        assert "Task 3" not in agent_task_descriptions

        # Verify all tasks have correct agent_id
        for task in agent_tasks:
            assert task.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_find_by_status(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test finding tasks by status."""
        # Arrange
        task1 = model_factory.create_task(status=TaskStatus.CREATED, description="Task 1")
        task2 = model_factory.create_task(status=TaskStatus.RUNNING, description="Task 2")
        task3 = model_factory.create_task(status=TaskStatus.CREATED, description="Task 3")
        task4 = model_factory.create_task(status=TaskStatus.COMPLETED, description="Task 4")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)
        await task_repository.create(task4)

        # Act
        created_tasks = await task_repository.find_by_status(TaskStatus.CREATED)
        running_tasks = await task_repository.find_by_status(TaskStatus.RUNNING)
        completed_tasks = await task_repository.find_by_status(TaskStatus.COMPLETED)

        # Assert
        assert len(created_tasks) == 2
        assert len(running_tasks) == 1
        assert len(completed_tasks) == 1

        created_descriptions = [task.description for task in created_tasks]
        assert "Task 1" in created_descriptions
        assert "Task 3" in created_descriptions

        assert running_tasks[0].description == "Task 2"
        assert completed_tasks[0].description == "Task 4"

    @pytest.mark.asyncio
    async def test_update_status(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test updating task status using the custom method."""
        # Arrange
        task = model_factory.create_task(status=TaskStatus.CREATED)
        created_task = await task_repository.create(task)

        # Act
        await task_repository.update_status(created_task.id, TaskStatus.RUNNING)

        # Assert
        updated_task = await task_repository.get(created_task.id)
        assert updated_task.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_task_with_complex_parameters(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test creating task with complex parameters."""
        # Arrange
        complex_parameters = {
            "prompt": "Write a Python function",
            "context": {"language": "python", "framework": "fastapi"},
            "settings": {"temperature": 0.7, "max_tokens": 1000},
            "tools": ["code_execution", "file_operations"],
        }

        task = model_factory.create_task(parameters=complex_parameters)

        # Act
        created_task = await task_repository.create(task)

        # Assert
        assert created_task.parameters == complex_parameters

        # Verify persistence
        retrieved_task = await task_repository.get(created_task.id)
        assert retrieved_task.parameters == complex_parameters

    @pytest.mark.asyncio
    async def test_task_with_error(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test creating task with error information."""
        # Arrange
        error_info = {
            "type": "ValueError",
            "message": "Invalid input parameter",
            "traceback": "Traceback (most recent call last)...",
        }

        task = model_factory.create_task(status=TaskStatus.FAILED, error=error_info)

        # Act
        created_task = await task_repository.create(task)

        # Assert
        assert created_task.error == error_info
        assert created_task.status == TaskStatus.FAILED

        # Verify persistence
        retrieved_task = await task_repository.get(created_task.id)
        assert retrieved_task.error == error_info
        assert retrieved_task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_task_status_lifecycle(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test complete task status lifecycle."""
        # Arrange
        task = model_factory.create_task(status=TaskStatus.CREATED)
        created_task = await task_repository.create(task)

        # Test status progression
        statuses = [TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.COMPLETED]

        for status in statuses:
            # Act
            await task_repository.update_status(created_task.id, status)

            # Assert
            retrieved_task = await task_repository.get(created_task.id)
            assert retrieved_task.status == status

            # Also verify using find_by_status
            status_tasks = await task_repository.find_by_status(status)
            assert any(t.id == created_task.id for t in status_tasks)

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test that tasks are properly isolated by session."""
        # Arrange
        session1 = f"session-{uuid4().hex[:8]}"
        session2 = f"session-{uuid4().hex[:8]}"
        agent_id = str(uuid4())

        # Create tasks in different sessions for the same agent
        task1 = model_factory.create_task(session_id=session1, agent_id=agent_id)
        task2 = model_factory.create_task(session_id=session2, agent_id=agent_id)

        await task_repository.create(task1)
        await task_repository.create(task2)

        # Act & Assert
        session1_tasks = await task_repository.find_by_session_id(session1)
        session2_tasks = await task_repository.find_by_session_id(session2)
        agent_tasks = await task_repository.find_by_agent_id(agent_id)

        assert len(session1_tasks) == 1
        assert len(session2_tasks) == 1
        assert len(agent_tasks) == 2  # Both tasks belong to same agent

        assert session1_tasks[0].id == task1.id
        assert session2_tasks[0].id == task2.id
