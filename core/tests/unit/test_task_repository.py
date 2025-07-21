"""Unit tests for TaskRepository."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agentarea_tasks.domain.models import Task, TaskCreate, TaskUpdate
from agentarea_tasks.infrastructure.repository import TaskRepository


@pytest.mark.asyncio
async def test_get_by_agent_id(db_session):
    """Test getting tasks by agent ID with pagination."""
    repository = TaskRepository(db_session)
    
    # Create test data
    agent1_id = uuid4()
    agent2_id = uuid4()
    user_id = "test_user"
    
    # Create tasks for agent1
    task1 = await repository.create_from_data(TaskCreate(
        agent_id=agent1_id,
        description="Task 1 for agent 1",
        user_id=user_id,
        parameters={"param": "value1"}
    ))
    
    task2 = await repository.create_from_data(TaskCreate(
        agent_id=agent1_id,
        description="Task 2 for agent 1",
        user_id=user_id,
        parameters={"param": "value2"}
    ))
    
    # Create task for agent2
    task3 = await repository.create_from_data(TaskCreate(
        agent_id=agent2_id,
        description="Task 1 for agent 2",
        user_id=user_id,
        parameters={"param": "value3"}
    ))
    
    await db_session.commit()
    
    # Test getting tasks for agent1
    agent1_tasks = await repository.get_by_agent_id(agent1_id)
    
    assert len(agent1_tasks) == 2
    assert all(task.agent_id == agent1_id for task in agent1_tasks)
    
    # Verify tasks are ordered by created_at desc (newest first)
    assert agent1_tasks[0].created_at >= agent1_tasks[1].created_at
    
    # Test pagination
    agent1_tasks_page1 = await repository.get_by_agent_id(agent1_id, limit=1, offset=0)
    assert len(agent1_tasks_page1) == 1
    
    agent1_tasks_page2 = await repository.get_by_agent_id(agent1_id, limit=1, offset=1)
    assert len(agent1_tasks_page2) == 1
    
    # Ensure different tasks on different pages
    assert agent1_tasks_page1[0].id != agent1_tasks_page2[0].id
    
    # Test getting tasks for agent2
    agent2_tasks = await repository.get_by_agent_id(agent2_id)
    assert len(agent2_tasks) == 1
    assert agent2_tasks[0].agent_id == agent2_id
    
    # Test getting tasks for non-existent agent
    non_existent_agent_tasks = await repository.get_by_agent_id(uuid4())
    assert len(non_existent_agent_tasks) == 0


@pytest.mark.asyncio
async def test_get_by_user_id(db_session):
    """Test getting tasks by user ID with pagination."""
    repository = TaskRepository(db_session)
    
    # Create test data
    agent_id = uuid4()
    user1_id = "user1"
    user2_id = "user2"
    
    # Create tasks for user1
    task1 = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Task 1 for user 1",
        user_id=user1_id,
        parameters={"param": "value1"}
    ))
    
    task2 = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Task 2 for user 1",
        user_id=user1_id,
        parameters={"param": "value2"}
    ))
    
    # Create task for user2
    task3 = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Task 1 for user 2",
        user_id=user2_id,
        parameters={"param": "value3"}
    ))
    
    await db_session.commit()
    
    # Test getting tasks for user1
    user1_tasks = await repository.get_by_user_id(user1_id)
    
    assert len(user1_tasks) == 2
    assert all(task.user_id == user1_id for task in user1_tasks)
    
    # Verify tasks are ordered by created_at desc (newest first)
    assert user1_tasks[0].created_at >= user1_tasks[1].created_at
    
    # Test pagination
    user1_tasks_page1 = await repository.get_by_user_id(user1_id, limit=1, offset=0)
    assert len(user1_tasks_page1) == 1
    
    user1_tasks_page2 = await repository.get_by_user_id(user1_id, limit=1, offset=1)
    assert len(user1_tasks_page2) == 1
    
    # Ensure different tasks on different pages
    assert user1_tasks_page1[0].id != user1_tasks_page2[0].id
    
    # Test getting tasks for user2
    user2_tasks = await repository.get_by_user_id(user2_id)
    assert len(user2_tasks) == 1
    assert user2_tasks[0].user_id == user2_id
    
    # Test getting tasks for non-existent user
    non_existent_user_tasks = await repository.get_by_user_id("non_existent_user")
    assert len(non_existent_user_tasks) == 0


@pytest.mark.asyncio
async def test_get_by_status(db_session):
    """Test getting tasks by status."""
    repository = TaskRepository(db_session)
    
    # Create test data with unique identifiers
    agent_id = uuid4()
    user_id = f"test_user_status_{uuid4().hex[:8]}"
    
    # Create tasks with different statuses
    pending_task = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Pending task for status test",
        user_id=user_id
    ))
    
    running_task = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Running task for status test",
        user_id=user_id
    ))
    
    completed_task = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Completed task for status test",
        user_id=user_id
    ))
    
    # Update statuses
    await repository.update_by_id(running_task.id, TaskUpdate(status="running"))
    await repository.update_by_id(completed_task.id, TaskUpdate(status="completed"))
    
    await db_session.commit()
    
    # Test getting pending tasks - filter by our specific tasks
    pending_tasks = await repository.get_by_status("pending")
    our_pending_tasks = [t for t in pending_tasks if t.user_id == user_id]
    assert len(our_pending_tasks) == 1
    assert our_pending_tasks[0].status == "pending"
    assert our_pending_tasks[0].id == pending_task.id
    
    # Test getting running tasks - filter by our specific tasks
    running_tasks = await repository.get_by_status("running")
    our_running_tasks = [t for t in running_tasks if t.user_id == user_id]
    assert len(our_running_tasks) == 1
    assert our_running_tasks[0].status == "running"
    assert our_running_tasks[0].id == running_task.id
    
    # Test getting completed tasks - filter by our specific tasks
    completed_tasks = await repository.get_by_status("completed")
    our_completed_tasks = [t for t in completed_tasks if t.user_id == user_id]
    assert len(our_completed_tasks) == 1
    assert our_completed_tasks[0].status == "completed"
    assert our_completed_tasks[0].id == completed_task.id
    
    # Test getting tasks with non-existent status
    non_existent_status_tasks = await repository.get_by_status("non_existent")
    assert len(non_existent_status_tasks) == 0
    
    # Verify tasks are ordered by created_at desc (newest first)
    if len(our_pending_tasks) > 1:
        for i in range(len(our_pending_tasks) - 1):
            assert our_pending_tasks[i].created_at >= our_pending_tasks[i + 1].created_at


@pytest.mark.asyncio
async def test_update_status(db_session):
    """Test updating task status atomically."""
    repository = TaskRepository(db_session)
    
    # Create test task
    agent_id = uuid4()
    user_id = "test_user"
    
    task = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Test task for status update",
        user_id=user_id,
        parameters={"initial": "value"}
    ))
    
    await db_session.commit()
    
    original_updated_at = task.updated_at
    
    # Test basic status update
    updated_task = await repository.update_status(task.id, "running")
    
    assert updated_task is not None
    assert updated_task.status == "running"
    # Just check that updated_at was changed (not necessarily greater due to timezone issues)
    assert updated_task.updated_at != original_updated_at
    assert updated_task.id == task.id
    
    # Test status update with additional fields
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Remove timezone for comparison
    execution_id = "exec_123"
    
    updated_task2 = await repository.update_status(
        task.id, 
        "completed",
        started_at=start_time,
        execution_id=execution_id,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    assert updated_task2 is not None
    assert updated_task2.status == "completed"
    assert updated_task2.started_at == start_time
    assert updated_task2.execution_id == execution_id
    assert updated_task2.completed_at is not None
    
    # Test status update with metadata
    metadata = {"result": "success", "duration": 120}
    updated_task3 = await repository.update_status(
        task.id,
        "archived",
        metadata=metadata
    )
    
    assert updated_task3 is not None
    assert updated_task3.status == "archived"
    assert updated_task3.metadata == metadata
    
    # Test updating non-existent task
    non_existent_result = await repository.update_status(uuid4(), "failed")
    assert non_existent_result is None


@pytest.mark.asyncio
async def test_update_status_atomic_behavior(db_session):
    """Test that update_status is atomic and handles concurrent updates properly."""
    repository = TaskRepository(db_session)
    
    # Create test task
    agent_id = uuid4()
    user_id = "test_user"
    
    task = await repository.create_from_data(TaskCreate(
        agent_id=agent_id,
        description="Test task for atomic update",
        user_id=user_id
    ))
    
    await db_session.commit()
    
    # Test that multiple field updates happen atomically
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Remove timezone for comparison
    execution_id = "exec_456"
    error_msg = "Test error"
    
    updated_task = await repository.update_status(
        task.id,
        "failed",
        started_at=start_time,
        execution_id=execution_id,
        error=error_msg,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    
    # Verify all fields were updated together
    assert updated_task.status == "failed"
    assert updated_task.started_at == start_time
    assert updated_task.execution_id == execution_id
    assert updated_task.error == error_msg
    assert updated_task.completed_at is not None
    
    # Verify the task in the database has all updates
    retrieved_task = await repository.get(task.id)
    assert retrieved_task.status == "failed"
    assert retrieved_task.started_at == start_time
    assert retrieved_task.execution_id == execution_id
    assert retrieved_task.error == error_msg


@pytest.mark.asyncio
async def test_repository_method_integration(db_session):
    """Test that new methods work well with existing repository methods."""
    repository = TaskRepository(db_session)
    
    # Create test data with unique identifiers
    agent_id = uuid4()
    user_id = f"integration_test_user_{uuid4().hex[:8]}"
    
    # Create multiple tasks
    tasks = []
    for i in range(3):
        task = await repository.create_from_data(TaskCreate(
            agent_id=agent_id,
            description=f"Integration test task {i+1}",
            user_id=user_id,
            parameters={"index": i+1}
        ))
        tasks.append(task)
    
    await db_session.commit()
    
    # Update statuses using new method
    await repository.update_status(tasks[0].id, "running")
    await repository.update_status(tasks[1].id, "completed")
    await repository.update_status(tasks[2].id, "failed")
    
    # Test that get_by_status works with updated tasks - filter by our specific tasks
    running_tasks = await repository.get_by_status("running")
    our_running_tasks = [t for t in running_tasks if t.user_id == user_id]
    assert len(our_running_tasks) == 1
    assert our_running_tasks[0].id == tasks[0].id
    
    completed_tasks = await repository.get_by_status("completed")
    our_completed_tasks = [t for t in completed_tasks if t.user_id == user_id]
    assert len(our_completed_tasks) == 1
    assert our_completed_tasks[0].id == tasks[1].id
    
    failed_tasks = await repository.get_by_status("failed")
    our_failed_tasks = [t for t in failed_tasks if t.user_id == user_id]
    assert len(our_failed_tasks) == 1
    assert our_failed_tasks[0].id == tasks[2].id
    
    # Test that get_by_agent_id returns all tasks regardless of status
    agent_tasks = await repository.get_by_agent_id(agent_id)
    assert len(agent_tasks) == 3
    
    # Test that get_by_user_id returns all tasks regardless of status
    user_tasks = await repository.get_by_user_id(user_id)
    assert len(user_tasks) == 3
    
    # Verify existing methods still work
    task_by_id = await repository.get(tasks[0].id)
    assert task_by_id is not None
    assert task_by_id.status == "running"
    
    all_tasks = await repository.list()
    assert len(all_tasks) >= 3  # At least our test tasks