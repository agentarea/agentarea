"""Integration test for workspace_id propagation through task creation flow.

This test ensures that workspace_id is properly propagated from API request
through all layers (API -> Service -> TaskManager -> TemporalExecutor -> Workflow).
"""

import logging
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.temporal_task_manager import TemporalTaskManager

logger = logging.getLogger(__name__)


class TestWorkspaceIdPropagation:
    """Test workspace_id propagation through the task execution stack."""

    @pytest.mark.asyncio
    async def test_simple_task_requires_workspace_id(self):
        """Test that SimpleTask requires workspace_id (no fallback)."""
        # Attempting to create SimpleTask without workspace_id should fail
        with pytest.raises(Exception):  # Pydantic validation error
            SimpleTask(
                id=uuid4(),
                title="Test Task",
                description="Test Description",
                query="Test Query",
                user_id="test_user",
                # workspace_id is missing - should fail!
                agent_id=uuid4(),
                status="pending",
            )

    @pytest.mark.asyncio
    async def test_simple_task_with_workspace_id(self):
        """Test that SimpleTask works correctly with workspace_id."""
        workspace_id = "test-workspace-123"
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="Test Query",
            user_id="test_user",
            workspace_id=workspace_id,
            agent_id=uuid4(),
            status="pending",
        )

        assert task.workspace_id == workspace_id
        assert isinstance(task.workspace_id, str)

    @pytest.mark.asyncio
    async def test_task_manager_validates_workspace_id(self, task_repository):
        """Test that TemporalTaskManager validates workspace_id presence."""
        from agentarea_tasks.domain.models import Task

        # Create a task WITHOUT workspace_id
        task_without_workspace = Task(
            id=uuid4(),
            agent_id=uuid4(),
            description="Test task",
            parameters={},
            status="pending",
            result=None,
            error=None,
            created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            updated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            user_id="test_user",
            workspace_id=None,  # Missing workspace_id
            metadata={},
        )

        task_manager = TemporalTaskManager(task_repository)

        # Should raise ValueError when trying to convert to SimpleTask
        with pytest.raises(ValueError, match="missing required workspace_id"):
            task_manager._task_to_simple_task(task_without_workspace)

    @pytest.mark.asyncio
    async def test_args_dict_contains_workspace_id(self, task_repository):
        """Test that args_dict sent to Temporal contains workspace_id."""
        workspace_id = "test-workspace-456"

        # Create a valid task WITH workspace_id
        task = SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test Description",
            query="Test Query",
            user_id="test_user",
            workspace_id=workspace_id,
            agent_id=uuid4(),
            status="pending",
            task_parameters={},
            metadata={
                "enable_agent_communication": False,
                "requires_human_approval": False,
            },
        )

        task_manager = TemporalTaskManager(task_repository)

        # Mock the temporal_executor to capture args_dict
        captured_args = {}

        async def mock_start_workflow(workflow_name, workflow_id, args, config):
            """Capture the args dict."""
            nonlocal captured_args
            captured_args = args
            return "mock-execution-id"

        task_manager.temporal_executor.start_workflow = mock_start_workflow

        # Try to submit the task (will fail at workflow start, but we capture args)
        try:
            await task_manager.submit_task(task)
        except Exception:
            pass  # Expected to fail at some point, we just want to capture args

        # Verify workspace_id is in the args_dict
        assert "workspace_id" in captured_args, "workspace_id missing from args_dict!"
        assert captured_args["workspace_id"] == workspace_id
        logger.info(f"✅ workspace_id correctly propagated: {captured_args['workspace_id']}")

    @pytest.mark.asyncio
    async def test_execution_request_reconstruction_includes_workspace_id(self):
        """Test that AgentExecutionRequest reconstruction includes workspace_id."""
        from uuid import UUID

        from agentarea_execution.models import AgentExecutionRequest

        # Simulate args_dict as it would be sent to Temporal
        args_dict = {
            "task_id": str(uuid4()),
            "agent_id": str(uuid4()),
            "user_id": "test_user",
            "workspace_id": "test-workspace-789",  # Critical field
            "task_query": "Test query",
            "task_parameters": {},
            "timeout_seconds": 300,
            "max_reasoning_iterations": 10,
            "enable_agent_communication": False,
            "requires_human_approval": False,
            "workflow_metadata": {},
        }

        # This is what happens in temporal_executor.py line 207
        execution_request = AgentExecutionRequest(
            task_id=UUID(args_dict["task_id"]),
            agent_id=UUID(args_dict["agent_id"]),
            user_id=args_dict["user_id"],
            workspace_id=args_dict["workspace_id"],  # Must be present!
            task_query=args_dict["task_query"],
            task_parameters=args_dict.get("task_parameters", {}),
            timeout_seconds=args_dict.get("timeout_seconds", 300),
            max_reasoning_iterations=args_dict.get("max_reasoning_iterations", 10),
            enable_agent_communication=args_dict.get("enable_agent_communication", False),
            requires_human_approval=args_dict.get("requires_human_approval", False),
            workflow_metadata=args_dict.get("workflow_metadata", {}),
        )

        # Verify the object was created successfully
        assert execution_request.workspace_id == "test-workspace-789"
        logger.info(f"✅ AgentExecutionRequest correctly reconstructed with workspace_id")

    @pytest.mark.asyncio
    async def test_task_service_requires_workspace_id(self, repository_factory, event_broker):
        """Test that TaskService.create_and_execute_task_with_workflow requires workspace_id."""
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        # Create task repository
        from agentarea_tasks.infrastructure.repository import TaskRepository

        task_repository = repository_factory.create_repository(TaskRepository)
        task_manager = TemporalTaskManager(task_repository)

        # Create mock workflow service
        class MockWorkflowService:
            async def get_workflow_status(self, execution_id):
                return {"status": "running"}

        workflow_service = MockWorkflowService()

        task_service = TaskService(
            repository_factory=repository_factory,
            event_broker=event_broker,
            task_manager=task_manager,
            workflow_service=workflow_service,
        )

        # Test 1: Calling without workspace_id should fail at function signature level
        # (Python will raise TypeError for missing required argument)
        with pytest.raises(TypeError, match="workspace_id"):
            await task_service.create_and_execute_task_with_workflow(
                agent_id=uuid4(),
                description="Test task",
                # workspace_id is missing - should fail!
                parameters={},
                user_id="test_user",
            )

        logger.info("✅ TaskService correctly requires workspace_id parameter")


@pytest.fixture
async def task_repository(repository_factory):
    """Create task repository for tests."""
    from agentarea_tasks.infrastructure.repository import TaskRepository

    return repository_factory.create_repository(TaskRepository)
