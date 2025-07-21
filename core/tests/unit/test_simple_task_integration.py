"""Integration test to verify SimpleTask works with existing code patterns."""

import pytest
from uuid import uuid4
from datetime import datetime

from agentarea_tasks.domain.models import SimpleTask


class TestSimpleTaskIntegration:
    """Test SimpleTask integration with existing code patterns."""
    
    def test_a2a_bridge_pattern(self):
        """Test the pattern used in A2A bridge."""
        agent_id = uuid4()
        task_id = uuid4()
        
        # This mimics the pattern from a2a_bridge.py
        task = SimpleTask(
            title=f"A2A Task {task_id}",
            description="Test content",
            query="Test content",
            user_id="a2a_user",
            agent_id=agent_id,
            task_parameters={
                "session_id": "test_session",
                "a2a_request": True,
                "metadata": {"test": "data"},
            },
            status="submitted",
        )
        
        # Verify the task was created correctly
        assert task.title == f"A2A Task {task_id}"
        assert task.description == "Test content"
        assert task.query == "Test content"
        assert task.user_id == "a2a_user"
        assert task.agent_id == agent_id
        assert task.task_parameters["session_id"] == "test_session"
        assert task.task_parameters["a2a_request"] is True
        assert task.status == "submitted"
        
        # Verify enhanced fields work
        assert task.metadata == {}  # Default value
        assert task.execution_id is None
        assert task.started_at is None
        assert task.completed_at is None
    
    def test_a2a_api_pattern(self):
        """Test the pattern used in A2A API."""
        agent_id = uuid4()
        message_id = uuid4()
        
        # This mimics the pattern from agents_a2a.py
        task = SimpleTask(
            id=message_id,
            title=f"A2A Message Task",
            description=f"Task created from A2A message",
            query="Test message content",
            user_id="a2a_user",
            agent_id=agent_id,
            status="submitted",
            task_parameters={}
        )
        
        # Verify the task was created correctly
        assert task.id == message_id
        assert task.title == "A2A Message Task"
        assert task.description == "Task created from A2A message"
        assert task.query == "Test message content"
        assert task.user_id == "a2a_user"
        assert task.agent_id == agent_id
        assert task.status == "submitted"
        assert task.task_parameters == {}
        
        # Test the conversion pattern used in the API
        response_dict = {
            "id": str(task.id),
            "status": task.status,
            "result": task.result,
            "error": task.error_message,
        }
        
        assert response_dict["id"] == str(message_id)
        assert response_dict["status"] == "submitted"
        assert response_dict["result"] is None
        assert response_dict["error"] is None
    
    def test_enhanced_fields_in_existing_patterns(self):
        """Test that enhanced fields work well with existing patterns."""
        agent_id = uuid4()
        
        # Create task using existing pattern
        task = SimpleTask(
            title="Enhanced Test",
            description="Test enhanced fields",
            query="test query",
            user_id="test_user",
            agent_id=agent_id,
        )
        
        # Use the new update_status method
        task.update_status("running", execution_id="temporal_123")
        
        assert task.status == "running"
        assert task.execution_id == "temporal_123"
        assert task.started_at is not None
        assert task.completed_at is None
        
        # Complete the task
        task.update_status("completed", result={"output": "success"})
        
        assert task.status == "completed"
        assert task.result == {"output": "success"}
        assert task.completed_at is not None
        assert task.is_completed()
        
        # Test metadata usage
        task.metadata["processing_time"] = 5.2
        task.metadata["worker_id"] = "worker_001"
        
        assert task.metadata["processing_time"] == 5.2
        assert task.metadata["worker_id"] == "worker_001"
    
    def test_temporal_execution_pattern(self):
        """Test pattern that might be used with Temporal workflows."""
        agent_id = uuid4()
        
        task = SimpleTask(
            title="Temporal Task",
            description="Task for Temporal execution",
            query="Execute with Temporal",
            user_id="temporal_user",
            agent_id=agent_id,
        )
        
        # Simulate Temporal workflow submission
        workflow_id = "workflow_123"
        task.update_status("running", execution_id=workflow_id)
        
        assert task.execution_id == workflow_id
        assert task.status == "running"
        assert task.started_at is not None
        
        # Simulate workflow completion
        task.update_status(
            "completed",
            result={"workflow_result": "success"},
            metadata={"workflow_duration": 30.5}
        )
        
        assert task.status == "completed"
        assert task.result == {"workflow_result": "success"}
        assert task.metadata == {"workflow_duration": 30.5}
        assert task.completed_at is not None
        assert task.is_completed()
    
    def test_error_handling_pattern(self):
        """Test error handling patterns with enhanced fields."""
        agent_id = uuid4()
        
        task = SimpleTask(
            title="Error Test",
            description="Task that will fail",
            query="This will fail",
            user_id="error_user",
            agent_id=agent_id,
        )
        
        # Start execution
        task.update_status("running", execution_id="exec_456")
        
        # Simulate failure
        task.update_status(
            "failed",
            error_message="Execution failed",
            metadata={"error_code": "E001", "retry_count": 1}
        )
        
        assert task.status == "failed"
        assert task.error_message == "Execution failed"
        assert task.metadata["error_code"] == "E001"
        assert task.metadata["retry_count"] == 1
        assert task.is_completed()  # Failed tasks are considered completed
        assert task.completed_at is not None