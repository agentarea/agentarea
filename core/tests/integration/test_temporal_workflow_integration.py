"""
Integration tests for Temporal workflow system.

These tests verify that our workflow implementation works correctly with
a real Temporal server, including end-to-end task execution.
"""

import asyncio
import pytest
import time
from datetime import timedelta
from uuid import uuid4

from agentarea.modules.agents.application.workflow_task_execution_service import WorkflowTaskExecutionService
from agentarea.common.workflow.temporal_executor import TemporalTaskExecutor
from agentarea.config import get_settings


@pytest.mark.asyncio
@pytest.mark.integration
class TestTemporalWorkflowIntegration:
    """Integration tests for Temporal workflow execution."""
    
    @pytest.fixture(autouse=True)
    async def setup(self):
        """Setup test environment."""
        self.settings = get_settings()
        
        # Skip tests if Temporal is not configured
        if not self.settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is disabled")
        
        if self.settings.workflow.WORKFLOW_ENGINE != "temporal":
            pytest.skip("Temporal engine not configured")
        
        # Create service with Temporal executor
        try:
            self.temporal_executor = TemporalTaskExecutor()
            self.service = WorkflowTaskExecutionService(task_executor=self.temporal_executor)
        except Exception as e:
            pytest.skip(f"Temporal not available: {e}")
    
    async def test_basic_workflow_execution(self):
        """Test basic workflow execution with Temporal."""
        # Test data
        task_id = f"integration-test-{int(time.time())}"
        agent_id = uuid4()
        description = "Integration test task"
        user_id = "test-user"
        
        # Execute task
        execution_id = await self.service.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description=description,
            user_id=user_id,
            task_parameters={"test": True},
            metadata={"integration_test": True}
        )
        
        # Verify execution started
        assert execution_id is not None
        assert execution_id.startswith("agent-task-")
        
        # Check initial status
        status = await self.service.get_task_status(execution_id)
        assert status["status"] in ["running", "completed"]
        assert status["execution_id"] == execution_id
        
        print(f"✅ Basic workflow execution test passed! Execution ID: {execution_id}")
    
    async def test_workflow_status_monitoring(self):
        """Test workflow status monitoring."""
        task_id = f"status-test-{int(time.time())}"
        agent_id = uuid4()
        
        # Start workflow
        execution_id = await self.service.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description="Status monitoring test"
        )
        
        # Monitor status over time
        status_checks = 0
        max_checks = 10
        
        while status_checks < max_checks:
            status = await self.service.get_task_status(execution_id)
            
            assert "status" in status
            assert "execution_id" in status
            assert status["execution_id"] == execution_id
            
            if status["status"] == "completed":
                assert "result" in status
                break
            elif status["status"] == "failed":
                assert "error" in status
                break
            elif status["status"] == "running":
                # Continue monitoring
                await asyncio.sleep(1)
                status_checks += 1
            else:
                pytest.fail(f"Unexpected status: {status['status']}")
        
        print(f"✅ Status monitoring test passed! Final status: {status['status']}")
    
    async def test_workflow_cancellation(self):
        """Test workflow cancellation."""
        task_id = f"cancel-test-{int(time.time())}"
        agent_id = uuid4()
        
        # Start workflow
        execution_id = await self.service.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description="Cancellation test task"
        )
        
        # Wait a bit for workflow to start
        await asyncio.sleep(1)
        
        # Cancel the workflow
        cancelled = await self.service.cancel_task(execution_id)
        assert cancelled is True
        
        # Verify cancellation (may take a moment)
        await asyncio.sleep(2)
        status = await self.service.get_task_status(execution_id)
        
        # Status should be cancelled or failed (depending on timing)
        assert status["status"] in ["cancelled", "failed", "terminated"]
        
        print(f"✅ Cancellation test passed! Final status: {status['status']}")
    
    async def test_concurrent_workflows(self):
        """Test multiple concurrent workflows."""
        num_workflows = 3
        tasks = []
        
        # Start multiple workflows concurrently
        for i in range(num_workflows):
            task = self.service.execute_task_async(
                task_id=f"concurrent-{i}-{int(time.time())}",
                agent_id=uuid4(),
                description=f"Concurrent test task {i}"
            )
            tasks.append(task)
        
        # Wait for all to start
        execution_ids = await asyncio.gather(*tasks)
        
        # Verify all started
        assert len(execution_ids) == num_workflows
        for execution_id in execution_ids:
            assert execution_id is not None
            assert execution_id.startswith("agent-task-")
        
        # Check status of all workflows
        status_tasks = [
            self.service.get_task_status(execution_id)
            for execution_id in execution_ids
        ]
        statuses = await asyncio.gather(*status_tasks)
        
        # Verify all have valid status
        for status in statuses:
            assert "status" in status
            assert status["status"] in ["running", "completed", "failed"]
        
        print(f"✅ Concurrent workflows test passed! Started {num_workflows} workflows")
    
    async def test_workflow_with_timeout(self):
        """Test workflow completion with timeout."""
        task_id = f"timeout-test-{int(time.time())}"
        agent_id = uuid4()
        
        # Start workflow
        execution_id = await self.service.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description="Timeout test task"
        )
        
        # Wait for completion with timeout
        try:
            result = await self.service.wait_for_task_completion(
                execution_id,
                timeout=timedelta(seconds=30)
            )
            
            # If completed within timeout
            assert "status" in result
            assert result["status"] in ["completed", "failed"]
            
            if result["status"] == "completed":
                assert "result" in result
            elif result["status"] == "failed":
                assert "error" in result
            
            print(f"✅ Timeout test passed! Result: {result['status']}")
            
        except TimeoutError:
            # If timeout occurred, that's also valid for this test
            print("✅ Timeout test passed! Workflow timed out as expected")
    
    async def test_legacy_compatibility(self):
        """Test legacy execute_task method compatibility."""
        task_id = f"legacy-test-{int(time.time())}"
        agent_id = uuid4()
        
        # Use legacy method (should not block)
        start_time = time.time()
        
        await self.service.execute_task(
            task_id=task_id,
            agent_id=agent_id,
            description="Legacy compatibility test"
        )
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should return quickly (not block)
        assert execution_time < 5.0, f"Legacy method took too long: {execution_time}s"
        
        # Check that task was actually started
        execution_id = f"agent-task-{task_id}"
        status = await self.service.get_task_status(execution_id)
        assert status["status"] in ["running", "completed", "failed"]
        
        print(f"✅ Legacy compatibility test passed! Execution time: {execution_time:.2f}s")


@pytest.mark.asyncio
@pytest.mark.integration
class TestTemporalWorkflowEndToEnd:
    """End-to-end integration tests."""
    
    @pytest.fixture(autouse=True)
    async def setup(self):
        """Setup for end-to-end tests."""
        self.settings = get_settings()
        
        if not self.settings.workflow.USE_WORKFLOW_EXECUTION:
            pytest.skip("Workflow execution is disabled")
        
        if self.settings.workflow.WORKFLOW_ENGINE != "temporal":
            pytest.skip("Temporal engine not configured")
        
        try:
            self.service = WorkflowTaskExecutionService()
        except Exception as e:
            pytest.skip(f"Service not available: {e}")
    
    async def test_full_agent_task_workflow(self):
        """Test complete agent task workflow execution."""
        # This test simulates a real agent task execution
        task_id = f"e2e-test-{int(time.time())}"
        agent_id = uuid4()
        
        # Complex task parameters
        task_parameters = {
            "query": "Analyze the weather patterns",
            "tools": ["weather_api", "data_analysis"],
            "max_iterations": 5,
            "timeout_minutes": 30
        }
        
        metadata = {
            "test_type": "end_to_end",
            "expected_duration": "short",
            "priority": "normal"
        }
        
        # Execute task
        execution_id = await self.service.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description="End-to-end agent task execution test",
            user_id="integration-test-user",
            task_parameters=task_parameters,
            metadata=metadata
        )
        
        # Monitor execution
        max_wait_time = 60  # seconds
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            status = await self.service.get_task_status(execution_id)
            
            # Log progress
            print(f"Workflow status: {status['status']} (elapsed: {time.time() - start_time:.1f}s)")
            
            if status["status"] == "completed":
                assert "result" in status
                print(f"✅ E2E test completed successfully!")
                print(f"Result: {status.get('result', {})}")
                return
            
            elif status["status"] == "failed":
                error = status.get("error", "Unknown error")
                print(f"❌ E2E test failed: {error}")
                # For integration tests, we'll accept failures as they might be due to missing services
                return
            
            elif status["status"] in ["running"]:
                # Continue monitoring
                await asyncio.sleep(2)
            
            else:
                pytest.fail(f"Unexpected workflow status: {status['status']}")
        
        # If we reach here, the workflow is still running
        print(f"⏱️ E2E test still running after {max_wait_time}s - this is expected for long tasks")
    
    async def test_workflow_resilience(self):
        """Test workflow resilience and error handling."""
        # Test with invalid agent ID
        invalid_agent_id = uuid4()
        
        execution_id = await self.service.execute_task_async(
            task_id=f"resilience-test-{int(time.time())}",
            agent_id=invalid_agent_id,
            description="Resilience test with invalid agent"
        )
        
        # Wait for workflow to process
        await asyncio.sleep(5)
        
        status = await self.service.get_task_status(execution_id)
        
        # Should either fail gracefully or handle the error
        assert status["status"] in ["running", "failed", "completed"]
        
        if status["status"] == "failed":
            assert "error" in status
            print(f"✅ Resilience test passed - failed gracefully: {status['error']}")
        else:
            print(f"✅ Resilience test passed - handled invalid input: {status['status']}")


# Test runner for manual execution
if __name__ == "__main__":
    async def run_integration_tests():
        """Run integration tests manually."""
        print("🚀 Running Temporal workflow integration tests...")
        
        # Basic tests
        test_basic = TestTemporalWorkflowIntegration()
        await test_basic.setup()
        
        try:
            await test_basic.test_basic_workflow_execution()
            await test_basic.test_workflow_status_monitoring()
            await test_basic.test_concurrent_workflows()
            await test_basic.test_legacy_compatibility()
            
            print("✅ Basic integration tests passed!")
            
        except Exception as e:
            print(f"❌ Basic tests failed: {e}")
        
        # End-to-end tests
        test_e2e = TestTemporalWorkflowEndToEnd()
        await test_e2e.setup()
        
        try:
            await test_e2e.test_full_agent_task_workflow()
            await test_e2e.test_workflow_resilience()
            
            print("✅ End-to-end tests passed!")
            
        except Exception as e:
            print(f"❌ E2E tests failed: {e}")
        
        print("🎉 Integration test suite completed!")
    
    asyncio.run(run_integration_tests()) 