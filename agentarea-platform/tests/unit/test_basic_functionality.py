"""Basic functionality tests to verify the setup works."""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import TaskEvent


class TestBasicFunctionality:
    """Basic tests to verify the domain models work correctly."""

    def test_task_event_creation(self):
        """Test that TaskEvent can be created successfully."""
        task_id = uuid4()
        event_id = uuid4()
        timestamp = datetime.utcnow()

        event = TaskEvent(
            id=event_id,
            task_id=task_id,
            event_type="LLMCallStarted",
            timestamp=timestamp,
            data={"model": "gpt-4", "tokens": 150},
            metadata={"source": "workflow"},
            workspace_id="test-workspace",
            created_by="workflow",
        )

        # Verify all fields are set correctly
        assert event.id == event_id
        assert event.task_id == task_id
        assert event.event_type == "LLMCallStarted"
        assert event.timestamp == timestamp
        assert event.data == {"model": "gpt-4", "tokens": 150}
        assert event.metadata == {"source": "workflow"}
        assert event.workspace_id == "test-workspace"
        assert event.created_by == "workflow"

    def test_task_event_factory_method(self):
        """Test TaskEvent.create_workflow_event factory method."""
        task_id = uuid4()
        event_type = "LLMCallCompleted"
        data = {"tokens": 150, "cost": 0.001}

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
            workspace_id="test-workspace",
            created_by="test",
        )

        # Verify factory method sets fields correctly
        assert event.task_id == task_id
        assert event.event_type == event_type
        assert event.data == data
        assert event.workspace_id == "test-workspace"
        assert event.created_by == "test"

        # Verify auto-generated fields
        assert event.id is not None
        assert isinstance(event.timestamp, datetime)
        assert event.metadata["source"] == "workflow"

    def test_task_event_with_defaults(self):
        """Test TaskEvent creation with default values."""
        task_id = uuid4()

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type="TaskStarted",
            data={"agent_id": str(uuid4())},
            workspace_id="default",
            created_by="workflow",
        )

        # Verify defaults are applied
        assert event.workspace_id == "default"
        assert event.created_by == "workflow"
        assert event.metadata["source"] == "workflow"

    def test_task_event_json_serialization(self):
        """Test that TaskEvent can be serialized to JSON."""
        task_id = uuid4()

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_type="LLMCallStarted",
            data={"model": "gpt-4", "temperature": 0.7},
            workspace_id="test-workspace",
            created_by="workflow",
        )

        # Test JSON serialization
        event_dict = event.model_dump()

        # Verify all fields are present
        assert "id" in event_dict
        assert "task_id" in event_dict
        assert "event_type" in event_dict
        assert "timestamp" in event_dict
        assert "data" in event_dict
        assert "metadata" in event_dict
        assert "workspace_id" in event_dict
        assert "created_by" in event_dict

        # Verify values (UUIDs are kept as UUID objects in model_dump)
        assert str(event_dict["task_id"]) == str(task_id)
        assert event_dict["event_type"] == "LLMCallStarted"
        assert event_dict["data"] == {"model": "gpt-4", "temperature": 0.7}
        assert event_dict["workspace_id"] == "test-workspace"

    def test_task_event_validation(self):
        """Test TaskEvent validation."""
        # Test with valid data
        valid_event = TaskEvent(
            id=uuid4(),
            task_id=uuid4(),
            event_type="ValidEvent",
            timestamp=datetime.utcnow(),
            data={"key": "value"},
            metadata={},
            workspace_id="workspace",
            created_by="user",
        )

        # Should not raise any validation errors
        assert valid_event.event_type == "ValidEvent"

        # Test that required fields are enforced by Pydantic
        from pydantic import ValidationError

        # Missing required field should raise ValidationError (Pydantic v2)
        with pytest.raises(ValidationError):
            TaskEvent(
                # Missing event_type
                id=uuid4(),
                task_id=uuid4(),
                timestamp=datetime.utcnow(),
                data={},
                workspace_id="workspace",
                created_by="user",
            )
