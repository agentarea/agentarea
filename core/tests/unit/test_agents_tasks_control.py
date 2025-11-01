"""
Unit tests for agent task control endpoints (pause/resume) and event endpoints
"""

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
        assert result["execution_id"] == f"agent-task-{test_task_id}"
        assert "message" in result

        # Verify service calls
        mock_agent_service.get.assert_called_once_with(test_agent_id)
        mock_workflow_service.get_workflow_status.assert_called_once_with(
            f"agent-task-{test_task_id}"
        )
        mock_workflow_service.pause_task.assert_called_once_with(f"agent-task-{test_task_id}")

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
        assert result["execution_id"] == f"agent-task-{test_task_id}"
        assert "message" in result

        # Verify service calls
        mock_agent_service.get.assert_called_once_with(test_agent_id)
        mock_workflow_service.get_workflow_status.assert_called_once_with(
            f"agent-task-{test_task_id}"
        )
        mock_workflow_service.resume_task.assert_called_once_with(f"agent-task-{test_task_id}")

    @pytest.mark.asyncio
    async def test_resume_agent_task_not_paused(
        self, mock_agent_service, mock_workflow_service, test_agent_id, test_task_id, mock_agent, test_user_context
    ):
        """Test resume task when task is not paused."""
        # Setup mocks
        mock_agent_service.get.return_value = mock_agent
        mock_workflow_service.get_workflow_status.return_value = {
            "status": "running",
        }

        # Call the endpoint and expect exception
        with pytest.raises(HTTPException) as exc_info:
            await resume_agent_task(
                agent_id=test_agent_id,
                task_id=test_task_id,
                user_context=test_user_context,
                agent_service=mock_agent_service,
                workflow_task_service=mock_workflow_service,
            )

        assert exc_info.value.status_code == 400
        assert "Cannot resume task that is not paused" in exc_info.value.detail

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
        assert "Failed to pause task: Test error" in exc_info.value.detail

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
        assert "Failed to resume task: Test error" in exc_info.value.detail


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


