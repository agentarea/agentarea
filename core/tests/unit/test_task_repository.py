"""Unit tests for TaskRepository with workspace-scoped functionality."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_tasks.domain.models import Task, TaskCreate, TaskUpdate
from agentarea_tasks.infrastructure.repository import TaskRepository


@pytest.fixture
def test_user_context():
    """Create a test user context."""
    return create_test_user_context(
        user_id="test-user-123",
        workspace_id="test-workspace-456"
    )


@pytest.fixture
def test_user_context_different_workspace():
    """Create a test user context in a different workspace."""
    return create_test_user_context(
        user_id="test-user-789",
        workspace_id="different-workspace-789"
    )


@pytest.fixture
def workspace_scoped_repository(db_session, test_user_context):
    """Create a workspace-scoped task repository."""
    factory = RepositoryFactory(db_session, test_user_context)
    return factory.create_repository(TaskRepository)


@pytest.mark.asyncio
async def test_get_by_agent_id_workspace_scoped(workspace_scoped_repository, test_user_context):
    """Test getting tasks by agent ID with workspace isolation."""
    # Create test data
    agent1_id = uuid4()
    agent2_id = uuid4()
    
    # Create tasks for agent1 - these will be automatically scoped to workspace
    task1 = await workspace_scoped_repository.create(
        agent_id=agent1_id,
        description="Task 1 for agent 1",
        parameters={"param": "value1"}
    )
    
    task2 = await workspace_scoped_repository.create(
        agent_id=agent1_id,
        description="Task 2 for agent 1",
        parameters={"param": "value2"}
    )
    
    # Create task for agent2
    task3 = await workspace_scoped_repository.create(
        agent_id=agent2_id,
        description="Task 1 for agent 2",
        parameters={"param": "value3"}
    )
    
    # Test getting tasks for agent1 - should only return workspace tasks
    agent1_tasks = await workspace_scoped_repository.find_by(agent_id=agent1_id)
    
    assert len(agent1_tasks) == 2
    assert all(task.agent_id == agent1_id for task in agent1_tasks)
    assert all(task.workspace_id == test_user_context.workspace_id for task in agent1_tasks)
    assert all(task.created_by == test_user_context.user_id for task in agent1_tasks)
    
    # Test getting tasks for agent2
    agent2_tasks = await workspace_scoped_repository.find_by(agent_id=agent2_id)
    assert len(agent2_tasks) == 1
    assert agent2_tasks[0].agent_id == agent2_id
    assert agent2_tasks[0].workspace_id == test_user_context.workspace_id
    
    # Test getting tasks for non-existent agent
    non_existent_agent_tasks = await workspace_scoped_repository.find_by(agent_id=uuid4())
    assert len(non_existent_agent_tasks) == 0


@pytest.mark.asyncio
async def test_workspace_isolation(db_session, test_user_context, test_user_context_different_workspace):
    """Test that tasks are isolated by workspace."""
    # Create repositories for different workspaces
    factory1 = RepositoryFactory(db_session, test_user_context)
    factory2 = RepositoryFactory(db_session, test_user_context_different_workspace)
    
    repo1 = factory1.create_repository(TaskRepository)
    repo2 = factory2.create_repository(TaskRepository)
    
    agent_id = uuid4()
    
    # Create task in workspace 1
    task1 = await repo1.create(
        agent_id=agent_id,
        description="Task in workspace 1",
        parameters={"workspace": "1"}
    )
    
    # Create task in workspace 2
    task2 = await repo2.create(
        agent_id=agent_id,
        description="Task in workspace 2",
        parameters={"workspace": "2"}
    )
    
    # Verify workspace isolation
    assert task1.workspace_id == test_user_context.workspace_id
    assert task2.workspace_id == test_user_context_different_workspace.workspace_id
    
    # Repository 1 should only see its workspace tasks
    repo1_tasks = await repo1.list_all()
    # Filter to only our test task
    our_repo1_tasks = [t for t in repo1_tasks if t.id == task1.id]
    assert len(our_repo1_tasks) == 1
    assert our_repo1_tasks[0].id == task1.id
    assert all(task.workspace_id == test_user_context.workspace_id for task in our_repo1_tasks)
    
    # Repository 2 should only see its workspace tasks
    repo2_tasks = await repo2.list_all()
    # Filter to only our test task
    our_repo2_tasks = [t for t in repo2_tasks if t.id == task2.id]
    assert len(our_repo2_tasks) == 1
    assert our_repo2_tasks[0].id == task2.id
    assert all(task.workspace_id == test_user_context_different_workspace.workspace_id for task in our_repo2_tasks)
    
    # Cross-workspace access should return None
    task1_from_repo2 = await repo2.get_by_id(task1.id)
    task2_from_repo1 = await repo1.get_by_id(task2.id)
    
    assert task1_from_repo2 is None
    assert task2_from_repo1 is None


@pytest.mark.asyncio
async def test_get_by_status_workspace_scoped(workspace_scoped_repository, test_user_context):
    """Test getting tasks by status with workspace isolation."""
    agent_id = uuid4()
    
    # Create tasks with different statuses - all automatically scoped to workspace
    pending_task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Pending task for status test",
        status="pending"
    )
    
    running_task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Running task for status test",
        status="running"
    )
    
    completed_task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Completed task for status test",
        status="completed"
    )
    
    # Test getting tasks by status - should only return workspace tasks
    pending_tasks = await workspace_scoped_repository.find_by(status="pending")
    # Filter to only our test tasks
    our_pending_tasks = [t for t in pending_tasks if t.id == pending_task.id]
    assert len(our_pending_tasks) == 1
    assert our_pending_tasks[0].status == "pending"
    assert our_pending_tasks[0].workspace_id == test_user_context.workspace_id
    assert our_pending_tasks[0].id == pending_task.id
    
    running_tasks = await workspace_scoped_repository.find_by(status="running")
    our_running_tasks = [t for t in running_tasks if t.id == running_task.id]
    assert len(our_running_tasks) == 1
    assert our_running_tasks[0].status == "running"
    assert our_running_tasks[0].workspace_id == test_user_context.workspace_id
    assert our_running_tasks[0].id == running_task.id
    
    completed_tasks = await workspace_scoped_repository.find_by(status="completed")
    our_completed_tasks = [t for t in completed_tasks if t.id == completed_task.id]
    assert len(our_completed_tasks) == 1
    assert our_completed_tasks[0].status == "completed"
    assert our_completed_tasks[0].workspace_id == test_user_context.workspace_id
    assert our_completed_tasks[0].id == completed_task.id
    
    # Test getting tasks with non-existent status
    non_existent_status_tasks = await workspace_scoped_repository.find_by(status="non_existent")
    assert len(non_existent_status_tasks) == 0


@pytest.mark.asyncio
async def test_update_workspace_scoped(workspace_scoped_repository, test_user_context):
    """Test updating tasks with workspace isolation."""
    agent_id = uuid4()
    
    # Create test task
    task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Test task for update",
        parameters={"initial": "value"}
    )
    
    # Test basic update
    updated_task = await workspace_scoped_repository.update(
        task.id,
        status="running",
        parameters={"updated": "value"}
    )
    
    assert updated_task is not None
    assert updated_task.status == "running"
    assert updated_task.parameters == {"updated": "value"}
    assert updated_task.workspace_id == test_user_context.workspace_id
    assert updated_task.created_by == test_user_context.user_id
    
    # Test updating non-existent task
    non_existent_result = await workspace_scoped_repository.update(
        uuid4(), 
        status="failed"
    )
    assert non_existent_result is None


@pytest.mark.asyncio
async def test_creator_scoped_filtering(workspace_scoped_repository, test_user_context):
    """Test creator-scoped filtering functionality."""
    agent_id = uuid4()
    
    # Create tasks with current user context
    task1 = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Task created by current user",
        parameters={"creator": "current"}
    )
    
    # Simulate another user in same workspace creating a task
    # (In real scenario, this would be done through a different repository instance)
    # For testing, we'll manually create a task with different created_by
    different_user_task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Task created by different user",
        parameters={"creator": "different"}
    )
    # Manually change created_by to simulate different user
    different_user_task.created_by = "different-user-id"
    await workspace_scoped_repository.session.commit()
    
    # Test workspace-scoped listing (should return all workspace tasks)
    all_workspace_tasks = await workspace_scoped_repository.list_all(creator_scoped=False)
    # Filter to only our test tasks
    our_workspace_tasks = [t for t in all_workspace_tasks if t.id in [task1.id, different_user_task.id]]
    assert len(our_workspace_tasks) == 2
    assert all(task.workspace_id == test_user_context.workspace_id for task in our_workspace_tasks)
    
    # Test creator-scoped listing (should return only current user's tasks)
    creator_tasks = await workspace_scoped_repository.list_all(creator_scoped=True)
    # Filter to only our test tasks
    our_creator_tasks = [t for t in creator_tasks if t.id == task1.id]
    assert len(our_creator_tasks) == 1
    assert our_creator_tasks[0].id == task1.id
    assert our_creator_tasks[0].created_by == test_user_context.user_id
    
    # Test creator-scoped get_by_id
    task1_creator_scoped = await workspace_scoped_repository.get_by_id(task1.id, creator_scoped=True)
    assert task1_creator_scoped is not None
    assert task1_creator_scoped.id == task1.id
    
    # Should not be able to get different user's task with creator_scoped=True
    different_task_creator_scoped = await workspace_scoped_repository.get_by_id(
        different_user_task.id, 
        creator_scoped=True
    )
    assert different_task_creator_scoped is None


@pytest.mark.asyncio
async def test_workspace_scoped_crud_operations(workspace_scoped_repository, test_user_context):
    """Test complete CRUD operations with workspace scoping."""
    agent_id = uuid4()
    
    # Create
    task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Test CRUD task",
        parameters={"operation": "create"}
    )
    
    assert task.id is not None
    assert task.workspace_id == test_user_context.workspace_id
    assert task.created_by == test_user_context.user_id
    
    # Read
    retrieved_task = await workspace_scoped_repository.get_by_id(task.id)
    assert retrieved_task is not None
    assert retrieved_task.id == task.id
    assert retrieved_task.description == "Test CRUD task"
    
    # Update
    updated_task = await workspace_scoped_repository.update(
        task.id,
        description="Updated CRUD task",
        parameters={"operation": "update"}
    )
    
    assert updated_task is not None
    assert updated_task.description == "Updated CRUD task"
    assert updated_task.parameters == {"operation": "update"}
    assert updated_task.workspace_id == test_user_context.workspace_id  # Should remain unchanged
    assert updated_task.created_by == test_user_context.user_id  # Should remain unchanged
    
    # Delete
    delete_result = await workspace_scoped_repository.delete(task.id)
    assert delete_result is True
    
    # Verify deletion
    deleted_task = await workspace_scoped_repository.get_by_id(task.id)
    assert deleted_task is None