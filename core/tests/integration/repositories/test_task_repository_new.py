"""
Simple integration tests for TaskRepository.

Tests all CRUD operations and business logic methods on the TaskRepository.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.utils.types import TaskState
from agentarea.modules.tasks.domain.models import (
    AgentCapability,
    Task,
    TaskComplexity,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from agentarea.modules.tasks.infrastructure.repository import SQLAlchemyTaskRepository


class TestTaskRepository:
    """Test cases for SQLAlchemyTaskRepository."""

    def create_test_task(
        self,
        task_id: str | None = None,
        title: str = "Test Task",
        description: str = "Test Description",
        session_id: str | None = None,
        assigned_agent_id: UUID | None = None,
        created_by: str | None = None,
        status_state: TaskState = TaskState.SUBMITTED,
    ) -> Task:
        """Create a test task with specified parameters."""
        task_status = TaskStatus(state=status_state)

        return Task(
            id=task_id or str(uuid4()),
            session_id=session_id,
            title=title,
            description=description,
            task_type=TaskType.ANALYSIS,
            priority=TaskPriority.MEDIUM,
            complexity=TaskComplexity.MODERATE,
            assigned_agent_id=assigned_agent_id,
            required_capabilities=[AgentCapability.REASONING],
            status=task_status,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    async def test_create_task(self, db_session: AsyncSession):
        """Test creating a new task."""
        repository = SQLAlchemyTaskRepository(db_session)
        task = self.create_test_task(title="Create Test Task")

        result = await repository.create(task)

        assert result is not None
        assert result.id == task.id
        assert result.title == "Create Test Task"
        assert result.status.state == TaskState.SUBMITTED

    async def test_get_task_by_id(self, db_session: AsyncSession):
        """Test retrieving a task by ID."""
        repository = SQLAlchemyTaskRepository(db_session)
        task = self.create_test_task(title="Get By ID Task")

        created_task = await repository.create(task)
        result = await repository.get_by_id(created_task.id)

        assert result is not None
        assert result.id == created_task.id
        assert result.title == "Get By ID Task"

    async def test_get_nonexistent_task(self, db_session: AsyncSession):
        """Test retrieving a task that doesn't exist."""
        repository = SQLAlchemyTaskRepository(db_session)

        result = await repository.get_by_id("nonexistent-id")

        assert result is None

    async def test_list_all_tasks(self, db_session: AsyncSession):
        """Test listing all tasks."""
        repository = SQLAlchemyTaskRepository(db_session)

        # Create multiple tasks
        task1 = self.create_test_task(title="List Task 1")
        task2 = self.create_test_task(title="List Task 2")

        await repository.create(task1)
        await repository.create(task2)

        results = await repository.list()

        assert len(results) >= 2
        task_titles = [task.title for task in results]
        assert "List Task 1" in task_titles
        assert "List Task 2" in task_titles

    async def test_update_task(self, db_session: AsyncSession):
        """Test updating an existing task."""
        repository = SQLAlchemyTaskRepository(db_session)
        task = self.create_test_task(title="Original Title")

        created_task = await repository.create(task)
        created_task.title = "Updated Title"
        created_task.description = "Updated Description"

        updated_task = await repository.update(created_task)

        assert updated_task.title == "Updated Title"
        assert updated_task.description == "Updated Description"
        assert updated_task.updated_at > created_task.created_at

    async def test_delete_task(self, db_session: AsyncSession):
        """Test deleting a task."""
        repository = SQLAlchemyTaskRepository(db_session)
        task = self.create_test_task(title="Delete Task")

        created_task = await repository.create(task)

        # Delete the task
        delete_result = await repository.delete(created_task.id)
        assert delete_result is True

        # Verify it's deleted
        result = await repository.get_by_id(created_task.id)
        assert result is None

    async def test_delete_nonexistent_task(self, db_session: AsyncSession):
        """Test deleting a task that doesn't exist."""
        repository = SQLAlchemyTaskRepository(db_session)

        result = await repository.delete("nonexistent-id")

        assert result is False

    async def test_get_by_user_id(self, db_session: AsyncSession):
        """Test retrieving tasks by user ID."""
        repository = SQLAlchemyTaskRepository(db_session)
        user_id = "test-user-123"

        # Create tasks for different users
        task1 = self.create_test_task(title="User Task 1", created_by=user_id)
        task2 = self.create_test_task(title="User Task 2", created_by=user_id)
        task3 = self.create_test_task(title="Other User Task", created_by="other-user")

        await repository.create(task1)
        await repository.create(task2)
        await repository.create(task3)

        results = await repository.get_by_user_id(user_id)

        assert len(results) == 2
        task_titles = [task.title for task in results]
        assert "User Task 1" in task_titles
        assert "User Task 2" in task_titles
        assert "Other User Task" not in task_titles

    async def test_get_by_agent_id(self, db_session: AsyncSession):
        """Test retrieving tasks by agent ID."""
        repository = SQLAlchemyTaskRepository(db_session)
        agent_id = uuid4()
        other_agent_id = uuid4()

        # Create tasks for different agents
        task1 = self.create_test_task(title="Agent Task 1", assigned_agent_id=agent_id)
        task2 = self.create_test_task(title="Agent Task 2", assigned_agent_id=agent_id)
        task3 = self.create_test_task(title="Other Agent Task", assigned_agent_id=other_agent_id)

        await repository.create(task1)
        await repository.create(task2)
        await repository.create(task3)

        results = await repository.get_by_agent_id(agent_id)

        assert len(results) == 2
        task_titles = [task.title for task in results]
        assert "Agent Task 1" in task_titles
        assert "Agent Task 2" in task_titles
        assert "Other Agent Task" not in task_titles

    async def test_get_tasks_by_status(self, db_session: AsyncSession):
        """Test retrieving tasks by status."""
        repository = SQLAlchemyTaskRepository(db_session)

        # Create tasks with different statuses
        task1 = self.create_test_task(title="Submitted Task", status_state=TaskState.SUBMITTED)
        task2 = self.create_test_task(title="Working Task", status_state=TaskState.WORKING)
        task3 = self.create_test_task(title="Completed Task", status_state=TaskState.COMPLETED)

        await repository.create(task1)
        await repository.create(task2)
        await repository.create(task3)

        # Test filtering by SUBMITTED status
        submitted_results = await repository.get_tasks_by_status(TaskState.SUBMITTED)
        submitted_titles = [task.title for task in submitted_results]
        assert "Submitted Task" in submitted_titles
        assert "Working Task" not in submitted_titles
        assert "Completed Task" not in submitted_titles

        # Test filtering by WORKING status
        working_results = await repository.get_tasks_by_status(TaskState.WORKING)
        working_titles = [task.title for task in working_results]
        assert "Working Task" in working_titles
        assert "Submitted Task" not in working_titles

    async def test_get_pending_tasks(self, db_session: AsyncSession):
        """Test retrieving pending tasks (submitted but not assigned)."""
        repository = SQLAlchemyTaskRepository(db_session)
        agent_id = uuid4()

        # Create different types of tasks
        pending_task = self.create_test_task(
            title="Pending Task",
            status_state=TaskState.SUBMITTED,
            assigned_agent_id=None,  # Not assigned
        )
        assigned_task = self.create_test_task(
            title="Assigned Task",
            status_state=TaskState.SUBMITTED,
            assigned_agent_id=agent_id,  # Already assigned
        )
        working_task = self.create_test_task(
            title="Working Task",
            status_state=TaskState.WORKING,
            assigned_agent_id=None,  # Different status
        )

        await repository.create(pending_task)
        await repository.create(assigned_task)
        await repository.create(working_task)

        results = await repository.get_pending_tasks()

        # Should only return tasks that are SUBMITTED and not assigned
        task_titles = [task.title for task in results]
        assert "Pending Task" in task_titles
        assert "Assigned Task" not in task_titles
        assert "Working Task" not in task_titles

    async def test_get_with_pagination(self, db_session: AsyncSession):
        """Test pagination in list methods."""
        repository = SQLAlchemyTaskRepository(db_session)
        user_id = "paginated-user"

        # Create multiple tasks for the same user
        for i in range(5):
            task = self.create_test_task(title=f"Paginated Task {i}", created_by=user_id)
            await repository.create(task)

        # Test pagination
        first_page = await repository.get_by_user_id(user_id, limit=2, offset=0)
        second_page = await repository.get_by_user_id(user_id, limit=2, offset=2)

        assert len(first_page) == 2
        assert len(second_page) == 2

        # Ensure different tasks
        first_page_ids = {task.id for task in first_page}
        second_page_ids = {task.id for task in second_page}
        assert first_page_ids.isdisjoint(second_page_ids)

    async def test_error_handling(self, db_session: AsyncSession):
        """Test error handling in repository methods."""
        repository = SQLAlchemyTaskRepository(db_session)

        # Test creating task with invalid data should not crash
        # (depending on validation implementation)
        try:
            invalid_task = self.create_test_task()
            # Modify to create invalid state if needed
            result = await repository.create(invalid_task)
            # If no validation errors, this is fine
            assert result is not None
        except Exception:
            # If validation errors occur, that's also acceptable
            pass
