"""Unit tests for the simplified TaskService."""

import pytest
from uuid import uuid4

from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService


class MockTaskRepository:
    """Mock task repository for testing."""
    
    def __init__(self):
        self.tasks: dict[str, SimpleTask] = {}
    
    async def create(self, task: SimpleTask) -> SimpleTask:
        task.id = uuid4()
        self.tasks[str(task.id)] = task
        return task
    
    async def get(self, task_id) -> SimpleTask | None:
        return self.tasks.get(str(task_id))
    
    async def update(self, task: SimpleTask) -> SimpleTask:
        self.tasks[str(task.id)] = task
        return task
    
    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        return [task for task in self.tasks.values() if task.user_id == user_id]
    
    async def get_by_agent_id(self, agent_id, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        return [task for task in self.tasks.values() if task.agent_id == agent_id]


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
def task_service():
    """Create a TaskService instance with mocked dependencies."""
    repository = MockTaskRepository()
    event_broker = MockEventBroker()
    task_manager = MockTaskManager()
    
    return TaskService(
        task_repository=repository,
        event_broker=event_broker,
        task_manager=task_manager,
    )


@pytest.mark.asyncio
async def test_create_task(task_service):
    """Test creating a simple task."""
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
    assert task.user_id == "user123"
    assert task.agent_id == agent_id
    assert task.task_parameters == {"param1": "value1"}
    assert task.status == "submitted"
    assert task.id is not None


@pytest.mark.asyncio
async def test_get_task(task_service):
    """Test retrieving a task by ID."""
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
    assert retrieved_task.title == "Test Task"


@pytest.mark.asyncio
async def test_get_user_tasks(task_service):
    """Test retrieving tasks for a specific user."""
    agent_id = uuid4()
    
    # Create tasks for different users
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
    
    # Get tasks for user1
    user1_tasks = await task_service.get_user_tasks("user1")
    
    assert len(user1_tasks) == 2
    assert all(task.user_id == "user1" for task in user1_tasks)


@pytest.mark.asyncio
async def test_get_agent_tasks(task_service):
    """Test retrieving tasks for a specific agent."""
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


@pytest.mark.asyncio
async def test_create_and_execute_task(task_service):
    """Test creating and executing a task."""
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
    assert submitted_task.user_id == "user123"
    assert submitted_task.query == "Execute this test" 