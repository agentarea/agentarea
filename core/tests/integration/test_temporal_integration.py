#!/usr/bin/env python3
"""
Integration tests for Temporal workflow system.

These tests verify that our workflow implementation works correctly with
a real Temporal server, including end-to-end task execution.

Run with: pytest tests/integration/test_temporal_integration.py -v
"""

import asyncio
import pytest
import time
from uuid import uuid4

from agentarea.modules.agents.application.workflow_task_execution_service import WorkflowTaskExecutionService
from agentarea.config import get_settings


@pytest.mark.asyncio
@pytest.mark.integration
class TestTemporalWorkflowIntegration:
    """Integration tests for Temporal workflow execution."""
    
    async def test_mock_executor_fallback(self):
        """Test that mock executor works when Temporal is not available."""
        # Force mock mode by creating service with mock engine
        from agentarea.modules.agents.application.workflow_task_execution_service import MockTaskExecutor
        mock_executor = MockTaskExecutor()
        service = WorkflowTaskExecutionService(task_executor=mock_executor)
        
        # Test basic execution
        execution_id = await service.execute_task_async(
            task_id="mock-test",
            agent_id=uuid4(),
            description="Test mock execution"
        )
        
        assert execution_id.startswith("mock-")
        
        # Test status monitoring
        status = await service.get_task_status(execution_id)
        assert status["status"] == "running"
        assert status["task_id"] == "mock-test"
    
    async def test_temporal_workflow_execution(self):
        """Test basic workflow execution with Temporal."""
        settings = get_settings()
        
        # Skip if workflow execution is not enabled
        if not settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is not enabled")
        
        service = WorkflowTaskExecutionService()
        
        # Test basic task execution
        start_time = time.time()
        execution_id = await service.execute_task_async(
            task_id=f"integration-test-{int(start_time)}",
            agent_id=uuid4(),
            description="Integration test task",
            user_id="test-user",
            task_parameters={"test": True},
            metadata={"integration_test": True}
        )
        execution_time = time.time() - start_time
        
        # Should return immediately (non-blocking)
        assert execution_time < 1.0
        assert execution_id.startswith("agent-task-")
        
        # Test status monitoring
        status = await service.get_task_status(execution_id)
        assert "status" in status
        assert "workflow_id" in status
    
    async def test_concurrent_task_execution(self):
        """Test that multiple tasks can be started concurrently."""
        settings = get_settings()
        
        if not settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is not enabled")
        
        service = WorkflowTaskExecutionService()
        
        # Start multiple tasks concurrently
        timestamp = int(time.time())
        
        task1 = service.execute_task_async(
            task_id=f"concurrent-0-{timestamp}",
            agent_id=uuid4(),
            description="Concurrent test task 0"
        )
        task2 = service.execute_task_async(
            task_id=f"concurrent-1-{timestamp}",
            agent_id=uuid4(),
            description="Concurrent test task 1"
        )
        task3 = service.execute_task_async(
            task_id=f"concurrent-2-{timestamp}",
            agent_id=uuid4(),
            description="Concurrent test task 2"
        )
        
        # All should complete quickly (non-blocking)
        start_time = time.time()
        execution_ids = await asyncio.gather(task1, task2, task3)
        execution_time = time.time() - start_time
        
        assert execution_time < 2.0  # Should be very fast
        assert len(execution_ids) == 3
        assert all(str(eid).startswith("agent-task-") for eid in execution_ids)
        assert len(set(execution_ids)) == 3  # All unique
    
    async def test_legacy_compatibility(self):
        """Test that legacy execute_task method still works."""
        settings = get_settings()
        
        if not settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is not enabled")
        
        service = WorkflowTaskExecutionService()
        
        # Test legacy method (should be non-blocking now)
        start_time = time.time()
        await service.execute_task(
            task_id=f"legacy-{int(start_time)}",
            agent_id=uuid4(),
            description="Legacy compatibility test"
        )
        execution_time = time.time() - start_time
        
        # Should still be non-blocking
        assert execution_time < 1.0
    
    async def test_task_cancellation(self):
        """Test task cancellation functionality."""
        settings = get_settings()
        
        if not settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is not enabled")
        
        service = WorkflowTaskExecutionService()
        
        # Start a task
        execution_id = await service.execute_task_async(
            task_id=f"cancel-test-{int(time.time())}",
            agent_id=uuid4(),
            description="Task to be cancelled"
        )
        
        # Try to cancel it
        # Note: This might not actually cancel if the workflow completed quickly
        cancelled = await service.cancel_task(execution_id)
        
        # The result depends on timing, but the call should not fail
        assert isinstance(cancelled, bool)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_workflow_configuration():
    """Test that workflow configuration is loaded correctly."""
    settings = get_settings()
    
    # Test configuration structure
    assert hasattr(settings, 'workflow')
    assert hasattr(settings.workflow, 'USE_WORKFLOW_EXECUTION')
    assert hasattr(settings.workflow, 'WORKFLOW_ENGINE')
    assert hasattr(settings.workflow, 'TEMPORAL_SERVER_URL')
    assert hasattr(settings.workflow, 'TEMPORAL_TASK_QUEUE')
    
    # Test that we can create a service
    service = WorkflowTaskExecutionService()
    assert service is not None
    assert hasattr(service, 'execute_task_async')
    assert hasattr(service, 'get_task_status')
    assert hasattr(service, 'cancel_task')


if __name__ == "__main__":
    # Allow running this test directly
    import sys
    import os
    
    # Add project root to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    
    # Run the tests
    pytest.main([__file__, "-v"]) 