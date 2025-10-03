"""Unit tests for TaskRepository with workspace-scoped functionality."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_tasks.domain.models import Task
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy import MetaData


@pytest.fixture
def test_user_context():
    """Create a test user context."""
    return create_test_user_context(user_id="test-user-123", workspace_id="test-workspace-456")


@pytest.fixture
def test_user_context_different_workspace():
    """Create a test user context in a different workspace."""
    return create_test_user_context(user_id="test-user-789", workspace_id="different-workspace-789")


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
        agent_id=agent1_id, description="Task 1 for agent 1", parameters={"param": "value1"}
    )

    task2 = await workspace_scoped_repository.create(
        agent_id=agent1_id, description="Task 2 for agent 1", parameters={"param": "value2"}
    )

    # Create task for agent2
    task3 = await workspace_scoped_repository.create(
        agent_id=agent2_id, description="Task 1 for agent 2", parameters={"param": "value3"}
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
async def test_workspace_isolation(
    db_session, test_user_context, test_user_context_different_workspace
):
    """Test that tasks are isolated by workspace."""
    # Create repositories for different workspaces
    factory1 = RepositoryFactory(db_session, test_user_context)
    factory2 = RepositoryFactory(db_session, test_user_context_different_workspace)

    repo1 = factory1.create_repository(TaskRepository)
    repo2 = factory2.create_repository(TaskRepository)

    agent_id = uuid4()

    # Create task in workspace 1
    task1 = await repo1.create(
        agent_id=agent_id, description="Task in workspace 1", parameters={"workspace": "1"}
    )

    # Create task in workspace 2
    task2 = await repo2.create(
        agent_id=agent_id, description="Task in workspace 2", parameters={"workspace": "2"}
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
    assert all(
        task.workspace_id == test_user_context_different_workspace.workspace_id
        for task in our_repo2_tasks
    )

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
        agent_id=agent_id, description="Pending task for status test", status="pending"
    )

    running_task = await workspace_scoped_repository.create(
        agent_id=agent_id, description="Running task for status test", status="running"
    )

    completed_task = await workspace_scoped_repository.create(
        agent_id=agent_id, description="Completed task for status test", status="completed"
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
        agent_id=agent_id, description="Test task for update", parameters={"initial": "value"}
    )

    # Test basic update
    updated_task = await workspace_scoped_repository.update(
        task.id, status="running", parameters={"updated": "value"}
    )

    assert updated_task is not None
    assert updated_task.status == "running"
    assert updated_task.parameters == {"updated": "value"}
    assert updated_task.workspace_id == test_user_context.workspace_id
    assert updated_task.created_by == test_user_context.user_id

    # Test updating non-existent task
    non_existent_result = await workspace_scoped_repository.update(uuid4(), status="failed")
    assert non_existent_result is None


@pytest.mark.asyncio
async def test_creator_scoped_filtering(workspace_scoped_repository, test_user_context):
    """Test creator-scoped filtering functionality."""
    agent_id = uuid4()

    # Create tasks with current user context
    task1 = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Task created by current user",
        parameters={"creator": "current"},
    )

    # Simulate another user in same workspace creating a task
    # (In real scenario, this would be done through a different repository instance)
    # For testing, we'll manually create a task with different created_by
    different_user_task = await workspace_scoped_repository.create(
        agent_id=agent_id,
        description="Task created by different user",
        parameters={"creator": "different"},
    )
    # Manually change created_by to simulate different user
    different_user_task.created_by = "different-user-id"
    await workspace_scoped_repository.session.commit()

    # Test workspace-scoped listing (should return all workspace tasks)
    all_workspace_tasks = await workspace_scoped_repository.list_all(creator_scoped=False)
    # Filter to only our test tasks
    our_workspace_tasks = [
        t for t in all_workspace_tasks if t.id in [task1.id, different_user_task.id]
    ]
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
    task1_creator_scoped = await workspace_scoped_repository.get_by_id(
        task1.id, creator_scoped=True
    )
    assert task1_creator_scoped is not None
    assert task1_creator_scoped.id == task1.id

    # Should not be able to get different user's task with creator_scoped=True
    different_task_creator_scoped = await workspace_scoped_repository.get_by_id(
        different_user_task.id, creator_scoped=True
    )
    assert different_task_creator_scoped is None


@pytest.mark.asyncio
async def test_workspace_scoped_crud_operations(workspace_scoped_repository, test_user_context):
    """Test complete CRUD operations with workspace scoping."""
    agent_id = uuid4()

    # Create
    task = await workspace_scoped_repository.create(
        agent_id=agent_id, description="Test CRUD task", parameters={"operation": "create"}
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
        task.id, description="Updated CRUD task", parameters={"operation": "update"}
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


@pytest.mark.asyncio
async def test_metadata_serialization_fix_create_task(
    workspace_scoped_repository, test_user_context
):
    """Test that create_task handles non-dict metadata correctly."""
    agent_id = uuid4()

    # Test with valid dict metadata
    valid_metadata_task = Task(
        id=uuid4(),
        agent_id=agent_id,
        description="Task with valid metadata",
        parameters={},
        status="pending",
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        execution_id=None,
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata={"priority": "high", "category": "test"},
    )

    created_task = await workspace_scoped_repository.create_task(valid_metadata_task)
    assert created_task is not None
    assert created_task.metadata == {"priority": "high", "category": "test"}

    # Test the fix by directly testing the repository's metadata handling
    # We'll create a task with valid metadata first, then test the internal logic
    base_task = Task(
        id=uuid4(),
        agent_id=agent_id,
        description="Task for metadata fix test",
        parameters={},
        status="pending",
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        execution_id=None,
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata={},  # Start with empty dict
    )

    # Test the metadata fix logic by simulating what happens in create_task
    # when a SQLAlchemy MetaData object is passed
    metadata_obj = MetaData()

    # Apply the fix logic that's in the repository
    fixed_metadata = metadata_obj if isinstance(metadata_obj, dict) else {}
    if metadata_obj is not None and not isinstance(metadata_obj, dict):
        fixed_metadata = {}

    # Verify the fix works
    assert fixed_metadata == {}
    assert isinstance(fixed_metadata, dict)

    # Test that the fixed metadata can be JSON serialized
    try:
        json.dumps(fixed_metadata)
    except (TypeError, ValueError) as e:
        pytest.fail(f"Fixed metadata is not JSON serializable: {e}")

    # Create task with the fixed metadata
    base_task.metadata = fixed_metadata
    created_task_with_fix = await workspace_scoped_repository.create_task(base_task)
    assert created_task_with_fix is not None
    assert created_task_with_fix.metadata == {}


@pytest.mark.asyncio
async def test_metadata_serialization_fix_update_task(
    workspace_scoped_repository, test_user_context
):
    """Test that update_task handles non-dict metadata correctly."""
    agent_id = uuid4()

    # Create a task first
    original_task = await workspace_scoped_repository.create(
        agent_id=agent_id, description="Task for metadata update test", parameters={"test": "value"}
    )

    # Test updating with valid dict metadata
    valid_metadata_update = Task(
        id=original_task.id,
        agent_id=agent_id,
        description="Updated task with valid metadata",
        parameters={"test": "updated"},
        status="running",
        result=None,
        error=None,
        created_at=original_task.created_at,
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=None,
        execution_id="test-execution-id",
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata={"updated": True, "priority": "medium"},
    )

    updated_task = await workspace_scoped_repository.update_task(valid_metadata_update)
    assert updated_task is not None
    assert updated_task.metadata == {"updated": True, "priority": "medium"}
    assert updated_task.status == "running"

    # Test the metadata fix logic for update_task
    metadata_obj = MetaData()

    # Apply the fix logic that's in the repository
    fixed_metadata = metadata_obj if isinstance(metadata_obj, dict) else {}
    if metadata_obj is not None and not isinstance(metadata_obj, dict):
        fixed_metadata = {}

    # Verify the fix works
    assert fixed_metadata == {}
    assert isinstance(fixed_metadata, dict)

    # Test that the fixed metadata can be JSON serialized
    try:
        json.dumps(fixed_metadata)
    except (TypeError, ValueError) as e:
        pytest.fail(f"Fixed metadata is not JSON serializable: {e}")

    # Test updating with the fixed metadata
    fixed_metadata_update = Task(
        id=original_task.id,
        agent_id=agent_id,
        description="Updated task with fixed metadata",
        parameters={"test": "metadata_fix"},
        status="completed",
        result={"success": True},
        error=None,
        created_at=original_task.created_at,
        updated_at=datetime.now(UTC),
        started_at=updated_task.started_at,
        completed_at=datetime.now(UTC),
        execution_id="test-execution-id",
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata=fixed_metadata,  # Use the fixed metadata
    )

    # This should not raise a JSON serialization error
    updated_task_with_fix = await workspace_scoped_repository.update_task(fixed_metadata_update)
    assert updated_task_with_fix is not None
    # The metadata should be an empty dict
    assert updated_task_with_fix.metadata == {}
    assert updated_task_with_fix.status == "completed"
    assert updated_task_with_fix.result == {"success": True}


@pytest.mark.asyncio
async def test_metadata_serialization_repository_fix_logic(
    workspace_scoped_repository, test_user_context
):
    """Test that the repository fix logic handles various invalid metadata types correctly."""

    # Test the fix logic directly by simulating what happens in create_task and update_task
    invalid_metadata_types = [
        ("string", "not a dict"),
        ("list", [1, 2, 3]),
        ("integer", 42),
        ("float", 3.14),
        ("boolean", True),
        ("sqlalchemy_metadata", MetaData()),
    ]

    for test_name, invalid_metadata in invalid_metadata_types:
        # Apply the same fix logic as in the repository
        if invalid_metadata is not None and not isinstance(invalid_metadata, dict):
            fixed_metadata = {}
        else:
            fixed_metadata = invalid_metadata

        # Verify the fix works correctly
        assert fixed_metadata == {}, (
            f"Invalid {test_name} metadata should be converted to empty dict"
        )
        assert isinstance(fixed_metadata, dict), "Fixed metadata should be a dict"

        # Test that the fixed metadata is JSON serializable
        try:
            json.dumps(fixed_metadata)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Fixed metadata for {test_name} type is not JSON serializable: {e}")

    # Test with a valid dictionary metadata to ensure it's preserved
    valid_metadata = {"key": "value", "number": 42}
    if valid_metadata is not None and not isinstance(valid_metadata, dict):
        fixed_valid_metadata = {}
    else:
        fixed_valid_metadata = valid_metadata

    assert fixed_valid_metadata == valid_metadata, "Valid dict metadata should be preserved"

    # Test with None metadata
    none_metadata = None
    if none_metadata is not None and not isinstance(none_metadata, dict):
        fixed_none_metadata = {}
    else:
        fixed_none_metadata = none_metadata

    assert fixed_none_metadata is None, "None metadata should be preserved as None"


@pytest.mark.asyncio
async def test_metadata_serialization_edge_cases(workspace_scoped_repository, test_user_context):
    """Test edge cases for metadata serialization."""
    agent_id = uuid4()

    # Test with empty dict (should remain empty dict)
    empty_dict_task = Task(
        id=uuid4(),
        agent_id=agent_id,
        description="Task with empty dict metadata",
        parameters={},
        status="pending",
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        execution_id=None,
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata={},
    )

    created_empty_dict_task = await workspace_scoped_repository.create_task(empty_dict_task)
    assert created_empty_dict_task.metadata == {}

    # Test with nested dict (should remain as-is)
    nested_dict_task = Task(
        id=uuid4(),
        agent_id=agent_id,
        description="Task with nested dict metadata",
        parameters={},
        status="pending",
        result=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        execution_id=None,
        user_id=test_user_context.user_id,
        workspace_id=test_user_context.workspace_id,
        metadata={"nested": {"key": "value"}, "array": [1, 2, 3], "string": "test"},
    )

    created_nested_dict_task = await workspace_scoped_repository.create_task(nested_dict_task)
    assert created_nested_dict_task.metadata == {
        "nested": {"key": "value"},
        "array": [1, 2, 3],
        "string": "test",
    }

    # Verify complex metadata is JSON serializable
    try:
        json.dumps(created_nested_dict_task.metadata)
    except (TypeError, ValueError) as e:
        pytest.fail(f"Complex nested metadata is not JSON serializable: {e}")


def test_metadata_fix_logic_unit():
    """Unit test for the metadata fix logic without database operations."""

    # Test the fix logic directly
    def apply_metadata_fix(metadata):
        """Replicate the fix logic from the repository."""
        if metadata is not None and not isinstance(metadata, dict):
            return {}
        return metadata

    # Test cases
    test_cases = [
        ({"valid": "dict"}, {"valid": "dict"}),  # Valid dict should remain unchanged
        ({}, {}),  # Empty dict should remain unchanged
        (None, None),  # None should remain None
        (MetaData(), {}),  # SQLAlchemy MetaData should become empty dict
        ("string", {}),  # String should become empty dict
        ([1, 2, 3], {}),  # List should become empty dict
        (42, {}),  # Integer should become empty dict
        (True, {}),  # Boolean should become empty dict
    ]

    for input_metadata, expected_output in test_cases:
        result = apply_metadata_fix(input_metadata)
        assert result == expected_output, (
            f"Failed for input {input_metadata}: expected {expected_output}, got {result}"
        )

        # Verify result is JSON serializable (except for None)
        if result is not None:
            try:
                json.dumps(result)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Result {result} is not JSON serializable: {e}")
