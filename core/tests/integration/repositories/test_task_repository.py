"""
Integration tests for SQLAlchemyTaskRepository.

Tests all CRUD operations and custom task-specific methods.
"""

from uuid import uuid4, UUID

import pytest
from agentarea_common.utils.types import TaskState, TaskStatus
from agentarea_tasks.infrastructure.repository import SQLAlchemyTaskRepository


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
        assert created_task.assigned_agent_id == task.assigned_agent_id
        assert created_task.status.state == task.status.state
        assert created_task.description == task.description
        assert created_task.parameters == task.parameters
        assert created_task.result == task.result
        assert created_task.error_message == task.error_message

    @pytest.mark.asyncio
    async def test_get_task_by_id(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test retrieving a task by ID."""
        # Arrange
        task = model_factory.create_task()
        created_task = await task_repository.create(task)

        # Act
        retrieved_task = await task_repository.get_by_id(created_task.id)

        # Assert
        assert retrieved_task is not None
        assert retrieved_task.id == created_task.id
        assert retrieved_task.session_id == created_task.session_id
        assert retrieved_task.assigned_agent_id == created_task.assigned_agent_id
        assert retrieved_task.status.state == created_task.status.state

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, task_repository: SQLAlchemyTaskRepository):
        """Test getting a non-existent task returns None."""
        # Arrange
        nonexistent_id = str(uuid4())

        # Act
        result = await task_repository.get_by_id(nonexistent_id)

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
            description="Original description"
        )
        created_task = await task_repository.create(task)

        # Modify the task
        created_task.description = "Updated description"
        created_task.status.state = TaskState.WORKING
        created_task.result = {"output": "test result"}

        # Act
        updated_task = await task_repository.update(created_task)

        # Assert
        assert updated_task.id == created_task.id
        assert updated_task.description == "Updated description"
        assert updated_task.status.state == TaskState.WORKING
        assert updated_task.result == {"output": "test result"}

        # Verify the update persisted
        retrieved_task = await task_repository.get_by_id(created_task.id)
        assert retrieved_task.description == "Updated description"
        assert retrieved_task.status.state == TaskState.WORKING
        assert retrieved_task.result == {"output": "test result"}

    @pytest.mark.asyncio
    async def test_delete_task(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test deleting an existing task."""
        # Arrange
        task = model_factory.create_task()
        created_task = await task_repository.create(task)

        # Verify task exists
        retrieved_task = await task_repository.get_by_id(created_task.id)
        assert retrieved_task is not None

        # Act
        delete_result = await task_repository.delete(created_task.id)

        # Assert
        assert delete_result is True

        # Verify task no longer exists
        deleted_task = await task_repository.get_by_id(created_task.id)
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
    async def test_get_by_user_id(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test finding tasks by user/creator ID."""
        # Arrange
        user_id = f"user-{uuid4().hex[:8]}"
        other_user_id = f"user-{uuid4().hex[:8]}"

        task1 = model_factory.create_task(created_by=user_id, description="Task 1")
        task2 = model_factory.create_task(created_by=user_id, description="Task 2")
        task3 = model_factory.create_task(created_by=other_user_id, description="Task 3")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        user_tasks = await task_repository.get_by_user_id(user_id)

        # Assert
        assert len(user_tasks) == 2
        user_task_descriptions = [task.description for task in user_tasks]
        assert "Task 1" in user_task_descriptions
        assert "Task 2" in user_task_descriptions
        assert "Task 3" not in user_task_descriptions

        # Verify all tasks have correct created_by
        for task in user_tasks:
            assert task.created_by == user_id

    @pytest.mark.asyncio
    async def test_get_by_agent_id(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test finding tasks by agent ID."""
        # Arrange
        agent_id = UUID(str(uuid4()))
        other_agent_id = UUID(str(uuid4()))

        task1 = model_factory.create_task(assigned_agent_id=agent_id, description="Task 1")
        task2 = model_factory.create_task(assigned_agent_id=agent_id, description="Task 2")
        task3 = model_factory.create_task(assigned_agent_id=other_agent_id, description="Task 3")

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        agent_tasks = await task_repository.get_by_agent_id(agent_id)

        # Assert
        assert len(agent_tasks) == 2
        agent_task_descriptions = [task.description for task in agent_tasks]
        assert "Task 1" in agent_task_descriptions
        assert "Task 2" in agent_task_descriptions
        assert "Task 3" not in agent_task_descriptions

        # Verify all tasks have correct agent_id
        for task in agent_tasks:
            assert task.assigned_agent_id == agent_id

    @pytest.mark.asyncio
    async def test_get_tasks_by_status(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test finding tasks by status."""
        # Arrange
        task1 = model_factory.create_task(description="Task 1")
        task1.status.state = TaskState.SUBMITTED
        
        task2 = model_factory.create_task(description="Task 2")
        task2.status.state = TaskState.WORKING
        
        task3 = model_factory.create_task(description="Task 3")
        task3.status.state = TaskState.SUBMITTED

        await task_repository.create(task1)
        await task_repository.create(task2)
        await task_repository.create(task3)

        # Act
        submitted_tasks = await task_repository.get_tasks_by_status(TaskState.SUBMITTED)

        # Assert
        assert len(submitted_tasks) == 2
        submitted_task_descriptions = [task.description for task in submitted_tasks]
        assert "Task 1" in submitted_task_descriptions
        assert "Task 3" in submitted_task_descriptions
        assert "Task 2" not in submitted_task_descriptions

        # Verify all tasks have correct status
        for task in submitted_tasks:
            assert task.status.state == TaskState.SUBMITTED

    @pytest.mark.asyncio
    async def test_get_pending_tasks(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test getting pending tasks."""
        # Arrange - Create tasks with different statuses and assignment states
        # Pending tasks should be SUBMITTED and unassigned
        pending_task1 = model_factory.create_task(
            description="Pending Task 1", 
            assigned_agent_id=None
        )
        pending_task1.status.state = TaskState.SUBMITTED
        
        pending_task2 = model_factory.create_task(
            description="Pending Task 2", 
            assigned_agent_id=None
        )
        pending_task2.status.state = TaskState.SUBMITTED
        
        # Assigned task (not pending)
        assigned_task = model_factory.create_task(
            description="Assigned Task", 
            assigned_agent_id=UUID(str(uuid4()))
        )
        assigned_task.status.state = TaskState.SUBMITTED
        
        # Working task (not pending)
        working_task = model_factory.create_task(
            description="Working Task",
            assigned_agent_id=None
        )
        working_task.status.state = TaskState.WORKING

        await task_repository.create(pending_task1)
        await task_repository.create(pending_task2)
        await task_repository.create(assigned_task)
        await task_repository.create(working_task)

        # Act
        pending_tasks = await task_repository.get_pending_tasks()

        # Assert
        assert len(pending_tasks) == 2
        pending_descriptions = [task.description for task in pending_tasks]
        assert "Pending Task 1" in pending_descriptions
        assert "Pending Task 2" in pending_descriptions
        assert "Assigned Task" not in pending_descriptions
        assert "Working Task" not in pending_descriptions

        # Verify all pending tasks have correct properties
        for task in pending_tasks:
            assert task.status.state == TaskState.SUBMITTED
            assert task.assigned_agent_id is None

    @pytest.mark.asyncio
    async def test_task_with_complex_parameters(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test creating and retrieving a task with complex parameters."""
        # Arrange
        complex_params = {
            "workflow_steps": [
                {"step": 1, "action": "analyze", "target": "data.csv"},
                {"step": 2, "action": "transform", "params": {"format": "json"}},
            ],
            "metadata": {
                "source": "api",
                "priority": "high",
                "tags": ["analysis", "transformation"],
            },
        }
        
        task = model_factory.create_task(
            description="Complex Task",
            parameters=complex_params
        )

        # Act
        created_task = await task_repository.create(task)
        retrieved_task = await task_repository.get_by_id(created_task.id)

        # Assert
        assert retrieved_task is not None
        assert retrieved_task.parameters == complex_params
        assert retrieved_task.parameters["workflow_steps"][0]["action"] == "analyze"
        assert retrieved_task.parameters["metadata"]["tags"] == ["analysis", "transformation"]

    @pytest.mark.asyncio
    async def test_task_with_error(self, task_repository: SQLAlchemyTaskRepository, model_factory):
        """Test creating and updating a task with error information."""
        # Arrange
        task = model_factory.create_task(description="Task with Error")
        created_task = await task_repository.create(task)

        # Simulate task failure
        created_task.status.state = TaskState.ERROR
        created_task.error_message = "Connection timeout after 30 seconds"
        created_task.result = None

        # Act
        updated_task = await task_repository.update(created_task)
        retrieved_task = await task_repository.get_by_id(created_task.id)

        # Assert
        assert retrieved_task is not None
        assert retrieved_task.status.state == TaskState.ERROR
        assert retrieved_task.error_message == "Connection timeout after 30 seconds"
        assert retrieved_task.result is None

    @pytest.mark.asyncio
    async def test_task_status_lifecycle(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test task status transitions through lifecycle."""
        # Arrange
        task = model_factory.create_task(description="Lifecycle Task")
        task.status.state = TaskState.SUBMITTED
        created_task = await task_repository.create(task)

        # Simulate status transitions
        # SUBMITTED -> WORKING
        created_task.status.state = TaskState.WORKING
        await task_repository.update(created_task)
        
        working_task = await task_repository.get_by_id(created_task.id)
        assert working_task.status.state == TaskState.WORKING

        # WORKING -> COMPLETED
        working_task.status.state = TaskState.COMPLETED
        working_task.result = {"output": "Task completed successfully"}
        await task_repository.update(working_task)
        
        completed_task = await task_repository.get_by_id(created_task.id)
        assert completed_task.status.state == TaskState.COMPLETED
        assert completed_task.result == {"output": "Task completed successfully"}

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(
        self, task_repository: SQLAlchemyTaskRepository, model_factory
    ):
        """Test that tasks from different sessions are properly isolated."""
        # Arrange
        session1_id = f"session-{uuid4().hex[:8]}"
        session2_id = f"session-{uuid4().hex[:8]}"
        user_id = f"user-{uuid4().hex[:8]}"

        # Create tasks for different sessions but same user
        task1 = model_factory.create_task(
            session_id=session1_id,
            created_by=user_id,
            description="Session 1 Task"
        )
        task2 = model_factory.create_task(
            session_id=session2_id,
            created_by=user_id,
            description="Session 2 Task"
        )

        await task_repository.create(task1)
        await task_repository.create(task2)

        # Act - Get tasks by user (should get both)
        user_tasks = await task_repository.get_by_user_id(user_id)

        # Assert
        assert len(user_tasks) == 2
        
        # Verify tasks have different sessions
        sessions = {task.session_id for task in user_tasks}
        assert session1_id in sessions
        assert session2_id in sessions
        assert len(sessions) == 2

        # Verify we can distinguish tasks by session
        session1_tasks = [task for task in user_tasks if task.session_id == session1_id]
        session2_tasks = [task for task in user_tasks if task.session_id == session2_id]
        
        assert len(session1_tasks) == 1
        assert len(session2_tasks) == 1
        assert session1_tasks[0].description == "Session 1 Task"
        assert session2_tasks[0].description == "Session 2 Task"
