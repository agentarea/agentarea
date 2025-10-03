"""Tests for the enhanced SimpleTask model."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import SimpleTask


class TestSimpleTaskModel:
    """Test cases for the enhanced SimpleTask model."""

    def test_simple_task_creation_with_required_fields(self):
        """Test creating a SimpleTask with only required fields."""
        task_id = uuid4()
        agent_id = uuid4()

        task = SimpleTask(
            id=task_id,
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=agent_id,
        )

        # Verify required fields
        assert task.id == task_id
        assert task.title == "Test Task"
        assert task.description == "Test Description"
        assert task.query == "test query"
        assert task.user_id == "test_user"
        assert task.agent_id == agent_id

        # Verify default values
        assert task.status == "submitted"
        assert task.task_parameters == {}
        assert task.result is None
        assert task.error_message is None
        assert task.metadata == {}

        # Verify enhanced fields defaults
        assert task.started_at is None
        assert task.completed_at is None
        assert task.execution_id is None

        # Verify timestamps
        assert isinstance(task.created_at, datetime)
        assert task.updated_at == task.created_at  # Should be set in post_init

    def test_simple_task_creation_with_all_fields(self):
        """Test creating a SimpleTask with all fields specified."""
        task_id = uuid4()
        agent_id = uuid4()
        created_at = datetime.utcnow()
        started_at = created_at + timedelta(minutes=1)
        completed_at = started_at + timedelta(minutes=5)
        updated_at = completed_at

        task = SimpleTask(
            id=task_id,
            title="Complete Task",
            description="Complete Description",
            query="complete query",
            user_id="complete_user",
            agent_id=agent_id,
            status="completed",
            task_parameters={"param1": "value1"},
            result={"output": "success"},
            error_message=None,
            created_at=created_at,
            updated_at=updated_at,
            started_at=started_at,
            completed_at=completed_at,
            execution_id="exec_123",
            metadata={"priority": "high"},
        )

        # Verify all fields are set correctly
        assert task.id == task_id
        assert task.title == "Complete Task"
        assert task.description == "Complete Description"
        assert task.query == "complete query"
        assert task.user_id == "complete_user"
        assert task.agent_id == agent_id
        assert task.status == "completed"
        assert task.task_parameters == {"param1": "value1"}
        assert task.result == {"output": "success"}
        assert task.error_message is None
        assert task.created_at == created_at
        assert task.updated_at == updated_at
        assert task.started_at == started_at
        assert task.completed_at == completed_at
        assert task.execution_id == "exec_123"
        assert task.metadata == {"priority": "high"}

    def test_datetime_validation_started_at_before_created_at(self):
        """Test validation fails when started_at is before created_at."""
        created_at = datetime.utcnow()
        started_at = created_at - timedelta(minutes=1)  # Invalid: before created_at

        with pytest.raises(ValueError, match="started_at cannot be before created_at"):
            SimpleTask(
                id=uuid4(),
                title="Test Task",
                description="Test Description",
                query="test query",
                user_id="test_user",
                agent_id=uuid4(),
                created_at=created_at,
                started_at=started_at,
            )

    def test_datetime_validation_completed_at_before_started_at(self):
        """Test validation fails when completed_at is before started_at."""
        created_at = datetime.utcnow()
        started_at = created_at + timedelta(minutes=1)
        completed_at = started_at - timedelta(seconds=30)  # Invalid: before started_at

        with pytest.raises(ValueError, match="completed_at cannot be before started_at"):
            SimpleTask(
                id=uuid4(),
                title="Test Task",
                description="Test Description",
                query="test query",
                user_id="test_user",
                agent_id=uuid4(),
                created_at=created_at,
                started_at=started_at,
                completed_at=completed_at,
            )

    def test_datetime_validation_completed_at_before_created_at(self):
        """Test validation fails when completed_at is before created_at."""
        created_at = datetime.utcnow()
        completed_at = created_at - timedelta(minutes=1)  # Invalid: before created_at

        with pytest.raises(ValueError, match="completed_at cannot be before created_at"):
            SimpleTask(
                id=uuid4(),
                title="Test Task",
                description="Test Description",
                query="test query",
                user_id="test_user",
                agent_id=uuid4(),
                created_at=created_at,
                completed_at=completed_at,
            )

    def test_is_completed_method(self):
        """Test the is_completed method for various statuses."""
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
        )

        # Test non-completed statuses
        task.status = "submitted"
        assert not task.is_completed()

        task.status = "running"
        assert not task.is_completed()

        task.status = "pending"
        assert not task.is_completed()

        # Test completed statuses
        task.status = "completed"
        assert task.is_completed()

        task.status = "failed"
        assert task.is_completed()

        task.status = "cancelled"
        assert task.is_completed()

    def test_is_running_method(self):
        """Test the is_running method."""
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
        )

        # Test non-running statuses
        task.status = "submitted"
        assert not task.is_running()

        task.status = "completed"
        assert not task.is_running()

        task.status = "failed"
        assert not task.is_running()

        # Test running status
        task.status = "running"
        assert task.is_running()

    def test_update_status_method_basic(self):
        """Test the update_status method with basic status change."""
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
        )

        original_updated_at = task.updated_at

        # Update status
        task.update_status("running")

        assert task.status == "running"
        assert task.updated_at > original_updated_at

    def test_update_status_method_with_automatic_timestamps(self):
        """Test the update_status method automatically sets timestamps."""
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
        )

        # Update to running - should set started_at
        task.update_status("running")
        assert task.status == "running"
        assert task.started_at is not None
        assert task.completed_at is None

        started_at = task.started_at

        # Update to completed - should set completed_at
        task.update_status("completed")
        assert task.status == "completed"
        assert task.started_at == started_at  # Should not change
        assert task.completed_at is not None
        assert task.completed_at >= task.started_at

    def test_update_status_method_with_additional_fields(self):
        """Test the update_status method with additional field updates."""
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
        )

        # Update status with additional fields
        task.update_status("completed", result={"output": "success"}, execution_id="exec_456")

        assert task.status == "completed"
        assert task.result == {"output": "success"}
        assert task.execution_id == "exec_456"
        assert task.completed_at is not None

    def test_update_status_method_does_not_override_existing_timestamps(self):
        """Test that update_status doesn't override existing timestamps."""
        created_at = datetime.utcnow()
        started_at = created_at + timedelta(minutes=1)

        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="test query",
            user_id="test_user",
            agent_id=uuid4(),
            created_at=created_at,
            started_at=started_at,
            status="running",
        )

        # Update to completed - should not change existing started_at
        task.update_status("completed")

        assert task.status == "completed"
        assert task.started_at == started_at  # Should remain unchanged
        assert task.completed_at is not None

    def test_backward_compatibility_with_original_fields(self):
        """Test that the enhanced model maintains backward compatibility."""
        # This test ensures that code using the original SimpleTask fields
        # continues to work without modification

        task = SimpleTask(
            id=uuid4(),
            title="Legacy Task",
            description="Legacy Description",
            query="legacy query",
            user_id="legacy_user",
            agent_id=uuid4(),
            status="submitted",
            task_parameters={"legacy": "param"},
            result={"legacy": "result"},
            error_message="legacy error",
        )

        # All original fields should work as before
        assert task.title == "Legacy Task"
        assert task.description == "Legacy Description"
        assert task.query == "legacy query"
        assert task.user_id == "legacy_user"
        assert task.status == "submitted"
        assert task.task_parameters == {"legacy": "param"}
        assert task.result == {"legacy": "result"}
        assert task.error_message == "legacy error"

        # New fields should have sensible defaults
        assert task.metadata == {}
        assert task.started_at is None
        assert task.completed_at is None
        assert task.execution_id is None
        assert task.updated_at == task.created_at

    def test_metadata_field_functionality(self):
        """Test the metadata field can store arbitrary data."""
        task = SimpleTask(
            id=uuid4(),
            title="Metadata Task",
            description="Task with metadata",
            query="metadata query",
            user_id="metadata_user",
            agent_id=uuid4(),
            metadata={
                "priority": "high",
                "tags": ["urgent", "customer"],
                "retry_count": 0,
                "custom_config": {"timeout": 300},
            },
        )

        assert task.metadata["priority"] == "high"
        assert task.metadata["tags"] == ["urgent", "customer"]
        assert task.metadata["retry_count"] == 0
        assert task.metadata["custom_config"]["timeout"] == 300

        # Test metadata can be updated
        task.metadata["retry_count"] = 1
        task.metadata["last_retry"] = datetime.utcnow()

        assert task.metadata["retry_count"] == 1
        assert "last_retry" in task.metadata
