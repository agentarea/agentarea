"""Integration test for A2A task management endpoints.

This test verifies that the enhanced A2A task management endpoints:
1. handle_task_get() retrieves tasks with current workflow status
2. handle_task_cancel() uses TaskService cancellation properly
3. Task status reflects actual Temporal workflow state
"""

import asyncio
import logging
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1.agents_a2a import handle_task_cancel, handle_task_get
from agentarea_tasks.domain.models import SimpleTask

logger = logging.getLogger(__name__)


class MockTaskServiceWithWorkflowStatus:
    """Mock TaskService that supports workflow status enrichment."""

    def __init__(self):
        self.tasks = {}
        self.cancelled_tasks = []
        self.workflow_statuses = {}

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        """Get task without workflow status enrichment."""
        return self.tasks.get(task_id)

    async def get_task_with_workflow_status(self, task_id: UUID) -> SimpleTask | None:
        """Get task with current workflow status."""
        task = self.tasks.get(task_id)
        if not task:
            return None

        # Simulate workflow status enrichment
        workflow_status = self.workflow_statuses.get(task_id, {})
        if workflow_status:
            # Update task with workflow status
            task.status = workflow_status.get("status", task.status)
            if workflow_status.get("result"):
                task.result = workflow_status["result"]

        return task

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task through TaskService."""
        task = self.tasks.get(task_id)
        if not task:
            return False

        # Check if task can be cancelled
        if task.status in ["completed", "failed", "cancelled"]:
            return False

        # Simulate successful cancellation
        task.status = "cancelled"
        self.cancelled_tasks.append(task_id)
        return True

    def add_task(self, task: SimpleTask):
        """Add a task to the mock service."""
        self.tasks[task.id] = task

    def set_workflow_status(self, task_id: UUID, status: str, result: dict = None):
        """Set workflow status for a task."""
        self.workflow_statuses[task_id] = {"status": status, "result": result}


@pytest.mark.asyncio
async def test_handle_task_get_with_workflow_status():
    """Test that handle_task_get retrieves tasks with current workflow status."""
    # Setup
    task_service = MockTaskServiceWithWorkflowStatus()
    task_id = uuid4()

    # Create a task with database status "running"
    task = SimpleTask(
        id=task_id,
        title="Test Task",
        description="Test task for workflow status",
        query="Test query",
        user_id="test-user",
        agent_id=uuid4(),
        status="running",  # Database status
    )
    task_service.add_task(task)

    # Set workflow status to "completed" (different from database)
    task_service.set_workflow_status(
        task_id, "completed", {"output": "Task completed successfully"}
    )

    # Test handle_task_get
    params = {"id": str(task_id)}
    response = await handle_task_get("test-request", params, task_service)

    # Verify response structure
    assert response.jsonrpc == "2.0"
    assert response.id == "test-request"
    assert response.result is not None

    # Verify task data includes workflow status
    a2a_task = response.result
    assert a2a_task.id == str(task_id)
    assert (
        a2a_task.status.state.value == "completed"
    )  # Should reflect workflow status, not database status
    assert "metadata" in a2a_task.metadata or a2a_task.metadata == {}


@pytest.mark.asyncio
async def test_handle_task_get_task_not_found():
    """Test handle_task_get with non-existent task."""
    task_service = MockTaskServiceWithWorkflowStatus()
    non_existent_id = uuid4()

    params = {"id": str(non_existent_id)}
    response = await handle_task_get("test-request", params, task_service)

    # Verify error response
    assert response.jsonrpc == "2.0"
    assert response.id == "test-request"
    assert response.error is not None
    assert response.error.code == -32001
    assert "Task not found" in response.error.message


@pytest.mark.asyncio
async def test_handle_task_cancel_success():
    """Test successful task cancellation through TaskService."""
    # Setup
    task_service = MockTaskServiceWithWorkflowStatus()
    task_id = uuid4()

    # Create a running task
    task = SimpleTask(
        id=task_id,
        title="Cancellable Task",
        description="Task that can be cancelled",
        query="Test query",
        user_id="test-user",
        agent_id=uuid4(),
        status="running",
    )
    task_service.add_task(task)

    # Test handle_task_cancel
    params = {"id": str(task_id)}
    response = await handle_task_cancel("cancel-request", params, task_service)

    # Verify successful cancellation response
    assert response.jsonrpc == "2.0"
    assert response.id == "cancel-request"
    assert response.result is not None

    # Verify the returned task shows cancelled status
    cancelled_task_result = response.result
    assert cancelled_task_result.id == str(task_id)
    assert (
        cancelled_task_result.status.state.value == "canceled"
    )  # A2A protocol uses "canceled" (one 'l')

    # Verify task was actually cancelled
    assert task_id in task_service.cancelled_tasks
    cancelled_task = await task_service.get_task(task_id)
    assert cancelled_task.status == "cancelled"


@pytest.mark.asyncio
async def test_handle_task_cancel_already_completed():
    """Test task cancellation when task is already completed."""
    # Setup
    task_service = MockTaskServiceWithWorkflowStatus()
    task_id = uuid4()

    # Create a completed task
    task = SimpleTask(
        id=task_id,
        title="Completed Task",
        description="Task that is already completed",
        query="Test query",
        user_id="test-user",
        agent_id=uuid4(),
        status="completed",
    )
    task_service.add_task(task)

    # Test handle_task_cancel
    params = {"id": str(task_id)}
    response = await handle_task_cancel("cancel-request", params, task_service)

    # Verify error response
    assert response.jsonrpc == "2.0"
    assert response.id == "cancel-request"
    assert response.error is not None
    assert response.error.code == -32002
    assert "cannot be cancelled" in response.error.message
    assert "completed" in response.error.message


@pytest.mark.asyncio
async def test_handle_task_cancel_with_workflow_status():
    """Test task cancellation uses current workflow status for validation."""
    # Setup
    task_service = MockTaskServiceWithWorkflowStatus()
    task_id = uuid4()

    # Create a task with database status "running"
    task = SimpleTask(
        id=task_id,
        title="Workflow Status Task",
        description="Task with different workflow status",
        query="Test query",
        user_id="test-user",
        agent_id=uuid4(),
        status="running",  # Database status
    )
    task_service.add_task(task)

    # Set workflow status to "completed" (different from database)
    task_service.set_workflow_status(task_id, "completed")

    # Test handle_task_cancel
    params = {"id": str(task_id)}
    response = await handle_task_cancel("cancel-request", params, task_service)

    # Verify error response based on workflow status
    assert response.jsonrpc == "2.0"
    assert response.id == "cancel-request"
    assert response.error is not None
    assert response.error.code == -32002
    assert "cannot be cancelled" in response.error.message
    assert "completed" in response.error.message  # Should reflect workflow status


@pytest.mark.asyncio
async def test_handle_task_cancel_task_not_found():
    """Test task cancellation with non-existent task."""
    task_service = MockTaskServiceWithWorkflowStatus()
    non_existent_id = uuid4()

    params = {"id": str(non_existent_id)}
    response = await handle_task_cancel("cancel-request", params, task_service)

    # Verify error response
    assert response.jsonrpc == "2.0"
    assert response.id == "cancel-request"
    assert response.error is not None
    assert response.error.code == -32001
    assert "Task not found" in response.error.message


@pytest.mark.asyncio
async def test_task_status_reflects_workflow_state():
    """Test that task status properly reflects actual Temporal workflow state."""
    # Setup
    task_service = MockTaskServiceWithWorkflowStatus()
    task_id = uuid4()

    # Create a task with initial status
    task = SimpleTask(
        id=task_id,
        title="Workflow State Task",
        description="Task to test workflow state reflection",
        query="Test query",
        user_id="test-user",
        agent_id=uuid4(),
        status="submitted",  # Initial database status
    )
    task_service.add_task(task)

    # Test 1: Get task without workflow status (should return database status)
    task_without_workflow = await task_service.get_task(task_id)
    assert task_without_workflow.status == "submitted"

    # Test 2: Set workflow status and get task with workflow status
    task_service.set_workflow_status(task_id, "running")
    task_with_workflow = await task_service.get_task_with_workflow_status(task_id)
    assert task_with_workflow.status == "running"  # Should reflect workflow status

    # Test 3: Update workflow status to completed
    task_service.set_workflow_status(task_id, "completed", {"final_result": "success"})
    task_completed = await task_service.get_task_with_workflow_status(task_id)
    assert task_completed.status == "completed"
    assert task_completed.result == {"final_result": "success"}

    # Test 4: Verify A2A endpoint uses workflow status
    params = {"id": str(task_id)}
    response = await handle_task_get("workflow-test", params, task_service)

    a2a_task = response.result
    assert a2a_task.status.state.value == "completed"  # A2A response should reflect workflow status


if __name__ == "__main__":
    # Run the integration tests
    asyncio.run(test_handle_task_get_with_workflow_status())
    asyncio.run(test_handle_task_cancel_success())
    asyncio.run(test_task_status_reflects_workflow_state())
    print("✅ A2A task management integration tests passed!")
