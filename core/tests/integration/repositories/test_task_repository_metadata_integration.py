"""Integration tests for TaskRepository metadata serialization fix.

These tests verify that the metadata serialization fix works correctly
with real database operations and full repository integration.
"""

import json
from uuid import uuid4

import pytest
from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy import MetaData


@pytest.mark.integration
class TestTaskRepositoryMetadataIntegration:
    """Integration tests for metadata serialization in TaskRepository."""

    @pytest.fixture
    def test_user_context(self):
        """Create a test user context."""
        return create_test_user_context()

    @pytest.fixture
    def task_repository(self, db_session, test_user_context):
        """Create a TaskRepository instance with test database session."""
        return TaskRepository(session=db_session, user_context=test_user_context)

    @pytest.mark.asyncio
    async def test_create_task_with_sqlalchemy_metadata_integration(
        self, task_repository, test_user_context
    ):
        """Test creating a task with SQLAlchemy MetaData object in real database."""
        agent_id = uuid4()
        metadata_obj = MetaData()

        # Create task with valid metadata first, then test repository's internal logic
        from agentarea_tasks.domain.models import TaskCreate

        task_create = TaskCreate(
            agent_id=agent_id,
            description="Integration test task with SQLAlchemy MetaData",
            parameters={"test": "integration"},
            metadata={},  # Start with valid metadata
        )

        # Manually set the invalid metadata to test repository's fix logic
        task_create.metadata = metadata_obj

        # This should not raise a JSON serialization error
        created_task = await task_repository.create_from_data(task_create)

        # Verify task was created successfully
        assert created_task is not None
        assert created_task.agent_id == agent_id
        assert created_task.description == "Integration test task with SQLAlchemy MetaData"

        # Debug: Check what we actually got
        print(f"DEBUG: created_task.metadata type: {type(created_task.metadata)}")
        print(f"DEBUG: created_task.metadata value: {created_task.metadata}")
        print(f"DEBUG: created_task.metadata == {{}}: {created_task.metadata == {}}")

        # Verify metadata was converted to empty dict
        assert created_task.metadata == {}

        # Verify the task can be retrieved from database
        retrieved_task = await task_repository.get_by_id(created_task.id)
        assert retrieved_task is not None
        assert retrieved_task.metadata == {}

        # Verify metadata is JSON serializable
        try:
            json.dumps(retrieved_task.metadata)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Retrieved task metadata is not JSON serializable: {e}")

    @pytest.mark.asyncio
    async def test_update_task_with_sqlalchemy_metadata_integration(
        self, task_repository, test_user_context
    ):
        """Test updating a task with SQLAlchemy MetaData object in real database."""
        agent_id = uuid4()

        # First create a task with valid metadata
        from agentarea_tasks.domain.models import TaskCreate

        task_create = TaskCreate(
            agent_id=agent_id,
            description="Task for metadata update integration test",
            parameters={"original": "data"},
        )
        original_task = await task_repository.create_from_data(task_create)

        # Create SQLAlchemy MetaData object
        metadata_obj = MetaData()

        # Update task with SQLAlchemy MetaData object using TaskUpdate
        from agentarea_tasks.domain.models import TaskUpdate

        task_update = TaskUpdate(
            metadata={},  # Start with valid metadata
            description="Updated task with SQLAlchemy MetaData",
            parameters={"updated": "data"},
            status="running",
            execution_id="integration-test-execution",
        )

        # Manually set the invalid metadata to test repository's fix logic
        task_update.metadata = metadata_obj

        updated_task = await task_repository.update_by_id(
            task_id=original_task.id, task_update=task_update
        )

        # Verify task was updated successfully
        assert updated_task is not None
        assert updated_task.id == original_task.id
        assert updated_task.description == "Updated task with SQLAlchemy MetaData"
        assert updated_task.status == "running"
        assert updated_task.execution_id == "integration-test-execution"

        # Verify metadata was converted to empty dict
        assert updated_task.metadata == {}

        # Verify the updated task can be retrieved from database
        retrieved_task = await task_repository.get_task(updated_task.id)
        assert retrieved_task is not None
        assert retrieved_task.metadata == {}
        assert retrieved_task.status == "running"

        # Verify metadata is JSON serializable
        try:
            json.dumps(retrieved_task.metadata)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Updated task metadata is not JSON serializable: {e}")

    @pytest.mark.asyncio
    async def test_various_invalid_metadata_types_integration(
        self, task_repository, test_user_context
    ):
        """Test various invalid metadata types in real database operations."""
        agent_id = uuid4()

        invalid_metadata_types = [
            ("string", "not a dict"),
            ("list", [1, 2, 3]),
            ("integer", 42),
            ("float", 3.14),
            ("boolean", True),
            ("sqlalchemy_metadata", MetaData()),
        ]

        created_tasks = []

        for test_name, invalid_metadata in invalid_metadata_types:
            # Create task with valid metadata first, then test repository's internal logic
            from agentarea_tasks.domain.models import TaskCreate

            task_create = TaskCreate(
                agent_id=agent_id,
                description=f"Integration test task with {test_name} metadata",
                parameters={"test_type": test_name},
                metadata={},  # Start with valid metadata
            )

            # Manually set the invalid metadata to test repository's fix logic
            task_create.metadata = invalid_metadata

            # This should not raise a JSON serialization error
            created_task = await task_repository.create_from_data(task_create)
            assert created_task is not None, f"Failed to create task with {test_name} metadata"

            # All invalid metadata types should be converted to empty dict
            assert created_task.metadata == {}, (
                f"Invalid {test_name} metadata was not converted to empty dict"
            )

            created_tasks.append(created_task)

        # Verify all tasks can be retrieved and have valid metadata
        for i, (test_name, _) in enumerate(invalid_metadata_types):
            retrieved_task = await task_repository.get_task(created_tasks[i].id)
            assert retrieved_task is not None
            assert retrieved_task.metadata == {}

            # Verify metadata is JSON serializable
            try:
                json.dumps(retrieved_task.metadata)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Metadata for {test_name} type is not JSON serializable: {e}")

    @pytest.mark.asyncio
    async def test_valid_metadata_preservation_integration(
        self, task_repository, test_user_context
    ):
        """Test that valid dict metadata is preserved correctly in database operations."""
        agent_id = uuid4()

        # Test with complex valid metadata
        complex_metadata = {
            "priority": "high",
            "category": "integration_test",
            "nested": {"level1": {"level2": "deep_value"}},
            "array": [1, 2, 3, {"nested_in_array": True}],
            "boolean": True,
            "number": 42,
            "float": 3.14159,
        }

        # Create task with complex valid metadata using TaskCreate
        from agentarea_tasks.domain.models import TaskCreate

        task_create = TaskCreate(
            agent_id=agent_id,
            description="Integration test task with complex valid metadata",
            parameters={"test": "complex_metadata"},
            metadata=complex_metadata,
        )

        # Create task
        created_task = await task_repository.create_from_data(task_create)
        assert created_task is not None

        # Verify complex metadata is preserved exactly
        assert created_task.metadata == complex_metadata

        # Retrieve from database and verify persistence
        retrieved_task = await task_repository.get_task(created_task.id)
        assert retrieved_task is not None
        assert retrieved_task.metadata == complex_metadata

        # Verify metadata is JSON serializable
        try:
            serialized = json.dumps(retrieved_task.metadata)
            deserialized = json.loads(serialized)
            assert deserialized == complex_metadata
        except (TypeError, ValueError) as e:
            pytest.fail(f"Complex metadata is not JSON serializable: {e}")

        # Test updating with different valid metadata
        updated_metadata = {
            "status": "updated",
            "timestamp": "2024-01-01T00:00:00Z",
            "tags": ["test", "integration", "metadata"],
        }

        # Update task with new metadata using TaskUpdate
        from agentarea_tasks.domain.models import TaskUpdate

        task_update = TaskUpdate(
            metadata=updated_metadata, status="running", execution_id="integration-test-update"
        )

        # Update task
        updated_task = await task_repository.update_by_id(
            task_id=created_task.id, task_update=task_update
        )
        assert updated_task is not None

        # Verify updated metadata is preserved exactly
        assert updated_task.metadata == updated_metadata

        # Retrieve from database and verify updated metadata persistence
        final_retrieved_task = await task_repository.get_task(updated_task.id)
        assert final_retrieved_task is not None
        assert final_retrieved_task.metadata == updated_metadata
        assert final_retrieved_task.status == "running"

    @pytest.mark.asyncio
    async def test_database_transaction_rollback_with_metadata_error(
        self, task_repository, test_user_context
    ):
        """Test that database transactions handle metadata errors gracefully."""
        agent_id = uuid4()

        # Create a task first using TaskCreate
        from agentarea_tasks.domain.models import TaskCreate

        task_create = TaskCreate(
            agent_id=agent_id,
            description="Task for transaction rollback test",
            parameters={"test": "rollback"},
        )
        original_task = await task_repository.create_from_data(task_create)

        # Verify task was created
        assert original_task is not None

        # Try to update with SQLAlchemy MetaData (should be handled gracefully)
        metadata_obj = MetaData()

        # This should succeed with the fix using TaskUpdate
        from agentarea_tasks.domain.models import TaskUpdate

        task_update = TaskUpdate(
            metadata={},  # Start with valid metadata
            description="Updated task for rollback test",
            parameters={"test": "rollback_updated"},
            status="running",
            execution_id="rollback-test",
        )

        # Manually set the invalid metadata to test repository's fix logic
        task_update.metadata = metadata_obj

        updated_task = await task_repository.update_by_id(
            task_id=original_task.id, task_update=task_update
        )

        assert updated_task is not None
        assert updated_task.metadata == {}  # MetaData converted to empty dict

        # Verify the task is still accessible and consistent
        retrieved_task = await task_repository.get_task(original_task.id)
        assert retrieved_task is not None
        assert retrieved_task.id == original_task.id
        assert retrieved_task.metadata == {}
        assert retrieved_task.status == "running"

        # Verify metadata is JSON serializable
        try:
            json.dumps(retrieved_task.metadata)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Task metadata after rollback test is not JSON serializable: {e}")
