"""
Unit tests for agent task control endpoints (pause/resume) and event endpoints
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_api.api.v1.agents_tasks import (
    pause_agent_task,
    resume_agent_task,
)
from fastapi import HTTPException


class TestAgentTaskControl:
    """Test cases for agent task control endpoints."""

    @pytest.fixture
    def mock_agent_service(self):
        """Mock agent service."""
        service = AsyncMock(spec=AgentService)
        return service

    @pytest.fixture
    def mock_workflow_service(self):
        """Mock temporal workflow service."""
        service = AsyncMock(spec=TemporalWorkflowService)
        return service

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service."""
        from agentarea_tasks.task_service import TaskService
        service = AsyncMock(spec=TaskService)
        return service

    @pytest.fixture
    def test_agent_id(self):
        """Test agent ID."""
        return uuid4()

    @pytest.fixture
    def test_task_id(self):
        """Test task ID."""
        return uuid4()

    @pytest.fixture
    def mock_agent(self):
        """Mock agent object."""
        agent = MagicMock()
        agent.id = uuid4()
        agent.name = "Test Agent"
        return agent

    @pytest.mark.asyncio
    async def test_pause_agent_task_success(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test successful task pause."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "running",
            "success": None,
        }
        mock_workflow_service.pause_task.return_value = True

        # Call the endpoint
        result = await pause_agent_task(
            agent_id=test_agent_id,
            task_id=test_task_id,
            user_context=test_user_context,
            agent_service=mock_agent_service,
            workflow_task_service=mock_workflow_service,
        )

        # Verify results
        assert result["status"] == "paused"
        assert result["task_id"] == str(test_task_id)
        assert result["execution_id"] == f"task-{test_task_id}"
        assert "message" in result

        # Verify service calls
        mock_agent_service.get.assert_called_once_with(test_agent_id)
        mock_workflow_service.get_workflow_status.assert_called_once_with(
            f"task-{test_task_id}"
        )
        mock_workflow_service.pause_task.assert_called_once_with(f"task-{test_task_id}")

    @pytest.mark.asyncio
    async def test_pause_agent_task_agent_not_found(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, test_user_context
    ):
        """Test pause task when agent doesn't exist."""
        # Setup mocks
        mock_agent_service.get.return_value = None

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Agent not found"

    @pytest.mark.asyncio
    async def test_pause_agent_task_task_not_found(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test pause task when task doesn't exist."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "unknown",
        }

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Task not found"

    @pytest.mark.asyncio
    async def test_pause_agent_task_already_completed(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test pause task when task is already completed."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "completed",
        }

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 400
        assert "Cannot pause task in 'completed' state" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_pause_agent_task_already_paused(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test pause task when task is already paused."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "paused",
        }

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Task is already paused"

    @pytest.mark.asyncio
    async def test_pause_agent_task_pause_fails(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test pause task when pause operation fails."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "running",
        }
        mock_workflow_service.pause_task.return_value = False

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to pause task"

    @pytest.mark.asyncio
    async def test_resume_agent_task_success(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test successful task resume."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "paused",
        }
        mock_workflow_service.resume_task.return_value = True

        # Call the endpoint
        result = await resume_agent_task(
            agent_id=test_agent_id,
            task_id=test_task_id,
            user_context=test_user_context,
            agent_service=mock_agent_service,
            workflow_task_service=mock_workflow_service,
        )

        # Verify results
        assert result["status"] == "running"
        assert result["task_id"] == str(test_task_id)
        assert result["execution_id"] == f"task-{test_task_id}"
        assert "message" in result

        # Verify service calls
        mock_agent_service.get.assert_called_once_with(test_agent_id)
        mock_workflow_service.get_workflow_status.assert_called_once_with(
            f"task-{test_task_id}"
        )
        mock_workflow_service.resume_task.assert_called_once_with(f"task-{test_task_id}")

    @pytest.mark.asyncio
    async def test_resume_agent_task_running_is_accepted(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Resume from 'running' is accepted: signal-based pause keeps Temporal's
        external status as 'running' while the workflow's internal handler
        waits on the pause flag, so the API can't 400 on 'not paused' here.
        Resume signals are no-ops on workflows that aren't paused.
        """
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "running",
        }
        mock_workflow_service.resume_task.return_value = True

        result = await resume_agent_task(
            agent_id=test_agent_id,
            task_id=test_task_id,
            user_context=test_user_context,
            agent_service=mock_agent_service,
            workflow_task_service=mock_workflow_service,
        )

        assert result["status"] == "running"
        mock_workflow_service.resume_task.assert_called_once_with(f"task-{test_task_id}")

    @pytest.mark.asyncio
    async def test_resume_agent_task_resume_fails(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test resume task when resume operation fails."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "paused",
        }
        mock_workflow_service.resume_task.return_value = False

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await resume_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to resume task"

    @pytest.mark.asyncio
    async def test_pause_agent_task_exception_handling(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test pause task exception handling."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.side_effect = Exception("Test error")

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await pause_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal server error"

    @pytest.mark.asyncio
    async def test_resume_agent_task_exception_handling(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test resume task exception handling."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.side_effect = Exception("Test error")

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await resume_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Internal server error"


class TestTemporalWorkflowServiceControl:
    """Test cases for TemporalWorkflowService pause/resume methods."""

    @pytest.fixture
    def mock_execution_service(self):
        """Mock execution service."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def workflow_service(self, mock_execution_service):
        """Create TemporalWorkflowService with mocked dependencies."""
        return TemporalWorkflowService(mock_execution_service)

    @pytest.mark.asyncio
    async def test_pause_task_success(self, workflow_service, mock_execution_service):
        """Test successful task pause."""
        execution_id = "test-execution-id"
        mock_execution_service.pause_execution.return_value = True

        result = await workflow_service.pause_task(execution_id)

        assert result is True
        mock_execution_service.pause_execution.assert_called_once_with(execution_id)

    @pytest.mark.asyncio
    async def test_pause_task_failure(self, workflow_service, mock_execution_service):
        """Test task pause failure."""
        execution_id = "test-execution-id"
        mock_execution_service.pause_execution.side_effect = Exception("Pause failed")

        result = await workflow_service.pause_task(execution_id)

        assert result is False
        mock_execution_service.pause_execution.assert_called_once_with(execution_id)

    @pytest.mark.asyncio
    async def test_resume_task_success(self, workflow_service, mock_execution_service):
        """Test successful task resume."""
        execution_id = "test-execution-id"
        mock_execution_service.resume_execution.return_value = True

        result = await workflow_service.resume_task(execution_id)

        assert result is True
        mock_execution_service.resume_execution.assert_called_once_with(execution_id)

    @pytest.mark.asyncio
    async def test_resume_task_failure(self, workflow_service, mock_execution_service):
        """Test task resume failure."""
        execution_id = "test-execution-id"
        mock_execution_service.resume_execution.side_effect = Exception("Resume failed")

        result = await workflow_service.resume_task(execution_id)

        assert result is False
        mock_execution_service.resume_execution.assert_called_once_with(execution_id)


class TestTemporalWorkflowOutcomeStatus:
    """Temporal completion describes engine execution, not task success."""

    def _orchestrator_with_result(self, result):
        from agentarea_agents.infrastructure.temporal_orchestrator import (
            TemporalWorkflowOrchestrator,
        )

        description = MagicMock()
        description.status.name = "COMPLETED"
        description.start_time = None
        description.close_time = None
        description.execution_time = None

        handle = MagicMock()
        handle.describe = AsyncMock(return_value=description)
        handle.result = AsyncMock(return_value=result)

        client = MagicMock()
        client.get_workflow_handle.return_value = handle

        orchestrator = TemporalWorkflowOrchestrator(
            temporal_address="localhost:7233",
            task_queue="test-queue",
            max_concurrent_activities=1,
            max_concurrent_workflows=1,
        )
        orchestrator._client = client
        return orchestrator

    @pytest.mark.asyncio
    async def test_completed_execution_preserves_failed_task_outcome(self):
        orchestrator = self._orchestrator_with_result(
            SimpleNamespace(
                success=False,
                status="failed",
                final_response=None,
                conversation_history=[],
                failure_reason="iteration_limit",
                error_message="Maximum iterations reached (10)",
            )
        )

        status = await orchestrator.get_workflow_status("task-1")

        assert status["execution_status"] == "completed"
        assert status["status"] == "failed"
        assert status["success"] is False
        assert status["failure_reason"] == "iteration_limit"
        assert status["error"] == "Maximum iterations reached (10)"

    @pytest.mark.asyncio
    async def test_completed_execution_with_successful_output_is_completed(self):
        orchestrator = self._orchestrator_with_result(
            SimpleNamespace(
                success=True,
                status="completed",
                final_response="Done",
                conversation_history=[],
                failure_reason=None,
                error_message=None,
            )
        )

        status = await orchestrator.get_workflow_status("task-1")

        assert status["execution_status"] == "completed"
        assert status["status"] == "completed"
        assert status["success"] is True
        assert status["result"]["response"] == "Done"

    @pytest.mark.asyncio
    async def test_success_without_final_output_is_failed(self):
        orchestrator = self._orchestrator_with_result(
            SimpleNamespace(
                success=True,
                status="completed",
                final_response=None,
                conversation_history=[],
                failure_reason=None,
                error_message=None,
            )
        )

        status = await orchestrator.get_workflow_status("task-1")

        assert status["status"] == "failed"
        assert status["success"] is False
        assert status["failure_reason"] == "missing_final_response"

    @pytest.mark.asyncio
    async def test_completed_execution_preserves_blocked_task_outcome(self):
        orchestrator = self._orchestrator_with_result(
            SimpleNamespace(
                success=False,
                status="blocked",
                final_response=None,
                conversation_history=[],
                failure_reason="provider_quota_exceeded",
                error_message="Provider quota exceeded",
            )
        )

        status = await orchestrator.get_workflow_status("task-1")

        assert status["execution_status"] == "completed"
        assert status["status"] == "blocked"
        assert status["success"] is False
        assert status["failure_reason"] == "provider_quota_exceeded"


class TestSendWorkflowCommandDelivery:
    """The orchestrator must distinguish "workflow not running" from real
    failures.

    On-the-fly control commands (e.g. the per-task model switch) are signals
    to a live workflow. When the workflow has already closed (completed /
    timed out / history evicted) the signal can't land — that is an expected
    "not delivered" outcome the API maps to 409, NOT a fake success. Any
    other error must propagate so it can't masquerade as "task not running".
    """

    def _orchestrator(self):
        from agentarea_agents.infrastructure.temporal_orchestrator import (
            TemporalWorkflowOrchestrator,
        )

        return TemporalWorkflowOrchestrator(
            temporal_address="localhost:7233",
            task_queue="test-queue",
            max_concurrent_activities=1,
            max_concurrent_workflows=1,
        )

    def _client_with_signal(self, *, side_effect=None):
        handle = MagicMock()
        handle.signal = AsyncMock(side_effect=side_effect)
        client = MagicMock()
        client.get_workflow_handle = MagicMock(return_value=handle)
        return client

    @pytest.mark.asyncio
    async def test_signal_delivered_returns_true(self):
        orch = self._orchestrator()
        orch._client = self._client_with_signal()

        ok = await orch.send_workflow_command(
            "task-1", "change_model", {"model_id": "m"}
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_workflow_not_running_returns_false(self):
        orch = self._orchestrator()
        orch._client = self._client_with_signal(
            side_effect=RuntimeError("workflow not found for ID: task-1")
        )

        ok = await orch.send_workflow_command(
            "task-1", "change_model", {"model_id": "m"}
        )
        # Not running -> False (API turns this into a 409, not a silent 200).
        assert ok is False

    @pytest.mark.asyncio
    async def test_real_error_propagates(self):
        orch = self._orchestrator()
        orch._client = self._client_with_signal(
            side_effect=RuntimeError("temporal connection reset by peer")
        )

        # A genuine failure must NOT be swallowed into "not running".
        with pytest.raises(RuntimeError, match="connection reset"):
            await orch.send_workflow_command(
                "task-1", "change_model", {"model_id": "m"}
            )

    @pytest.mark.asyncio
    async def test_continuation_uses_request_response_update(self):
        orch = self._orchestrator()
        handle = MagicMock()
        handle.execute_update = AsyncMock(
            return_value={"accepted": True, "continuation_count": 2}
        )
        client = MagicMock()
        client.get_workflow_handle.return_value = handle
        orch._client = client

        result = await orch.continue_workflow(
            "task-1", {"additional_iterations": 5, "additional_budget_usd": "1.50"}
        )

        assert result == {"accepted": True, "continuation_count": 2}
        handle.execute_update.assert_awaited_once_with(
            "continue_execution",
            {"additional_iterations": 5, "additional_budget_usd": "1.50"},
        )

    @pytest.mark.asyncio
    async def test_continuation_closed_workflow_is_rejected(self):
        orch = self._orchestrator()
        handle = MagicMock()
        handle.execute_update = AsyncMock(side_effect=RuntimeError("workflow already completed"))
        client = MagicMock()
        client.get_workflow_handle.return_value = handle
        orch._client = client

        result = await orch.continue_workflow("task-1", {"additional_iterations": 5})

        assert result == {"accepted": False, "reason": "workflow_not_running"}
