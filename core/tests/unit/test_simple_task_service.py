"""Unit tests for the simplified TaskService."""

import pytest
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService


class MockTaskRepository:
    """Mock task repository for testing with workspace-scoped behavior."""
    
    def __init__(self, user_context: UserContext):
        self.tasks: dict[str, SimpleTask] = {}
        self.user_context = user_context
    
    async def create(self, task: SimpleTask) -> SimpleTask:
        task.id = uuid4()
        # Automatically set workspace context
        task.user_id = self.user_context.user_id
        task.workspace_id = self.user_context.workspace_id
        self.tasks[str(task.id)] = task
        return task
    
    async def get(self, task_id) -> SimpleTask | None:
        task = self.tasks.get(str(task_id))
        # Only return tasks from current workspace
        if task and task.workspace_id == self.user_context.workspace_id:
            return task
        return None
    
    async def update(self, task: SimpleTask) -> SimpleTask:
        # Only update tasks from current workspace
        if task.workspace_id == self.user_context.workspace_id:
            self.tasks[str(task.id)] = task
            return task
        return None
    
    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        # Filter by workspace and user
        return [
            task for task in self.tasks.values() 
            if task.user_id == user_id and task.workspace_id == self.user_context.workspace_id
        ]
    
    async def get_by_agent_id(self, agent_id, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        # Filter by workspace
        return [
            task for task in self.tasks.values() 
            if task.agent_id == agent_id and task.workspace_id == self.user_context.workspace_id
        ]


class MockEventBroker:
    """Mock event broker for testing."""
    
    def __init__(self):
        self.published_events = []
    
    async def publish(self, event):
        self.published_events.append(event)


class MockTaskManager:
    """Mock task manager for testing."""
    
    def __init__(self):
        self.submitted_tasks = []
        self.cancelled_tasks = []
    
    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        self.submitted_tasks.append(task)
        task.status = "running"
        return task
    
    async def cancel_task(self, task_id) -> bool:
        self.cancelled_tasks.append(task_id)
        return True
    
    async def get_task_status(self, task_id) -> str:
        return "running"
    
    async def get_task_result(self, task_id):
        return {"answer": "Task completed successfully"}
    
    async def list_tasks(self, **filters) -> list[SimpleTask]:
        return self.submitted_tasks


@pytest.fixture
def test_user_context():
    """Create a test user context."""
    return create_test_user_context(
        user_id="test-user-123",
        workspace_id="test-workspace-456"
    )


class MockRepositoryFactory:
    """Mock repository factory for testing."""
    
    def __init__(self, user_context: UserContext):
        self.user_context = user_context
        self.task_repository = MockTaskRepository(user_context)
    
    def create_repository(self, repository_class):
        """Create a repository instance."""
        if repository_class.__name__ == "TaskRepository":
            return self.task_repository
        # For other repositories, return a mock
        return None


@pytest.fixture
def task_service(test_user_context):
    """Create a TaskService instance with mocked dependencies."""
    repository_factory = MockRepositoryFactory(test_user_context)
    event_broker = MockEventBroker()
    task_manager = MockTaskManager()
    
    return TaskService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_manager=task_manager,
    )


@pytest.mark.asyncio
async def test_create_task(task_service, test_user_context):
    """Test creating a simple task with workspace context."""
    agent_id = uuid4()
    
    task = await task_service.create_task_from_params(
        title="Test Task",
        description="This is a test task",
        query="What is 2+2?",
        user_id="user123",
        agent_id=agent_id,
        task_parameters={"param1": "value1"},
    )
    
    assert task.title == "Test Task"
    assert task.description == "This is a test task"
    assert task.query == "What is 2+2?"
    assert task.user_id == test_user_context.user_id  # Should be set from context
    assert task.workspace_id == test_user_context.workspace_id  # Should be set from context
    assert task.agent_id == agent_id
    assert task.task_parameters == {"param1": "value1"}
    assert task.status == "submitted"
    assert task.id is not None


@pytest.mark.asyncio
async def test_get_task(task_service, test_user_context):
    """Test retrieving a task by ID with workspace isolation."""
    agent_id = uuid4()
    
    # Create a task
    created_task = await task_service.create_task_from_params(
        title="Test Task",
        description="Test description",
        query="Test query",
        user_id="user123",
        agent_id=agent_id,
    )
    
    # Retrieve the task
    retrieved_task = await task_service.get_task(created_task.id)
    
    assert retrieved_task is not None
    assert retrieved_task.id == created_task.id
    # Verify the task has the correct workspace context and basic properties
    assert retrieved_task.workspace_id == test_user_context.workspace_id
    assert retrieved_task.user_id == test_user_context.user_id
    assert retrieved_task.agent_id == agent_id
    assert retrieved_task.workspace_id == test_user_context.workspace_id


@pytest.mark.asyncio
async def test_get_user_tasks(task_service, test_user_context):
    """Test retrieving tasks for a specific user with workspace isolation."""
    agent_id = uuid4()
    
    # Create tasks - all will be automatically scoped to current workspace
    await task_service.create_task_from_params(
        title="User 1 Task 1",
        description="Description 1",
        query="Query 1",
        user_id="user1",
        agent_id=agent_id,
    )
    
    await task_service.create_task_from_params(
        title="User 1 Task 2",
        description="Description 2",
        query="Query 2",
        user_id="user1",
        agent_id=agent_id,
    )
    
    await task_service.create_task_from_params(
        title="User 2 Task 1",
        description="Description 3",
        query="Query 3",
        user_id="user2",
        agent_id=agent_id,
    )
    
    # Get tasks for the current user (from context)
    user_tasks = await task_service.get_user_tasks(test_user_context.user_id)
    
    # All tasks should be from the current workspace
    assert len(user_tasks) == 3  # All tasks created in this test
    assert all(task.workspace_id == test_user_context.workspace_id for task in user_tasks)
    assert all(task.user_id == test_user_context.user_id for task in user_tasks)


@pytest.mark.asyncio
async def test_get_agent_tasks(task_service, test_user_context):
    """Test retrieving tasks for a specific agent with workspace isolation."""
    agent1_id = uuid4()
    agent2_id = uuid4()
    
    # Create tasks for different agents
    await task_service.create_task_from_params(
        title="Agent 1 Task 1",
        description="Description 1",
        query="Query 1",
        user_id="user1",
        agent_id=agent1_id,
    )
    
    await task_service.create_task_from_params(
        title="Agent 1 Task 2",
        description="Description 2",
        query="Query 2",
        user_id="user1",
        agent_id=agent1_id,
    )
    
    await task_service.create_task_from_params(
        title="Agent 2 Task 1",
        description="Description 3",
        query="Query 3",
        user_id="user1",
        agent_id=agent2_id,
    )
    
    # Get tasks for agent1
    agent1_tasks = await task_service.get_agent_tasks(agent1_id)
    
    assert len(agent1_tasks) == 2
    assert all(task.agent_id == agent1_id for task in agent1_tasks)
    # Verify workspace isolation
    assert all(task.workspace_id == test_user_context.workspace_id for task in agent1_tasks)


@pytest.mark.asyncio
async def test_create_and_execute_task(task_service, test_user_context):
    """Test creating and executing a task with workspace context."""
    agent_id = uuid4()
    
    events = []
    async for event in task_service.create_and_execute_task(
        title="Execute Test Task",
        description="Test execution",
        query="Execute this test",
        user_id="user123",
        agent_id=agent_id,
    ):
        events.append(event)
    
    # Check that we received the expected events
    assert len(events) >= 1
    assert events[0]["event_type"] == "TaskStarted"
    assert "task_id" in events[0]
    
    # Check that the task manager was called correctly
    mock_task_manager = task_service.task_manager
    assert len(mock_task_manager.submitted_tasks) >= 1
    submitted_task = mock_task_manager.submitted_tasks[-1]
    assert submitted_task.agent_id == agent_id
    assert submitted_task.user_id == test_user_context.user_id  # Should be from context
    assert submitted_task.workspace_id == test_user_context.workspace_id  # Should be from context
    # Verify workspace context and basic properties
    assert submitted_task.workspace_id == test_user_context.workspace_id


@pytest.mark.asyncio
async def test_workspace_isolation():
    """Test that tasks are isolated by workspace."""
    # Create two different user contexts in different workspaces
    user_context_1 = create_test_user_context(
        user_id="user1",
        workspace_id="workspace1"
    )
    user_context_2 = create_test_user_context(
        user_id="user2", 
        workspace_id="workspace2"
    )
    
    # Create repositories for each workspace
    repo1 = MockTaskRepository(user_context_1)
    repo2 = MockTaskRepository(user_context_2)
    
    # Create services for each workspace
    factory1 = MockRepositoryFactory(user_context_1)
    factory2 = MockRepositoryFactory(user_context_2)
    
    service1 = TaskService(
        repository_factory=factory1,
        event_broker=MockEventBroker(),
        task_manager=MockTaskManager(),
    )
    service2 = TaskService(
        repository_factory=factory2,
        event_broker=MockEventBroker(),
        task_manager=MockTaskManager(),
    )
    
    agent_id = uuid4()
    
    # Create task in workspace 1
    task1 = await service1.create_task_from_params(
        title="Workspace 1 Task",
        description="Task in workspace 1",
        query="Query 1",
        user_id="user1",
        agent_id=agent_id,
    )
    
    # Create task in workspace 2
    task2 = await service2.create_task_from_params(
        title="Workspace 2 Task",
        description="Task in workspace 2",
        query="Query 2",
        user_id="user2",
        agent_id=agent_id,
    )
    
    # Verify workspace isolation
    assert task1.workspace_id == "workspace1"
    assert task2.workspace_id == "workspace2"
    
    # Service 1 should not be able to see task from workspace 2
    retrieved_task1_from_service1 = await service1.get_task(task1.id)
    retrieved_task2_from_service1 = await service1.get_task(task2.id)
    
    assert retrieved_task1_from_service1 is not None
    assert retrieved_task2_from_service1 is None  # Should not see cross-workspace task
    
    # Service 2 should not be able to see task from workspace 1
    retrieved_task1_from_service2 = await service2.get_task(task1.id)
    retrieved_task2_from_service2 = await service2.get_task(task2.id)
    
    assert retrieved_task1_from_service2 is None  # Should not see cross-workspace task
    assert retrieved_task2_from_service2 is not None 