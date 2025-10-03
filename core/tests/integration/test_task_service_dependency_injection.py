"""
Integration tests for task service dependency injection in API endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service, get_event_broker, get_task_service
from agentarea_tasks.task_service import TaskService
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestTaskServiceDependencyInjectionIntegration:
    """Integration tests for task service dependency injection."""

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service."""
        service = AsyncMock(spec=TaskService)
        return service

    @pytest.fixture
    def mock_agent_service(self):
        """Mock agent service."""
        service = AsyncMock(spec=AgentService)
        return service

    @pytest.fixture
    def test_app(self, mock_task_service, mock_agent_service):
        """Create a test FastAPI app with mocked dependencies."""
        app = FastAPI()

        # Override dependencies
        app.dependency_overrides[get_task_service] = lambda: mock_task_service
        app.dependency_overrides[get_agent_service] = lambda: mock_agent_service

        # Add a simple test endpoint that uses the task service
        from fastapi import Depends

        @app.get("/test-task-service")
        async def test_task_service_endpoint(
            task_service: TaskService = Depends(get_task_service),
            agent_service: AgentService = Depends(get_agent_service),
        ):
            """Test endpoint that uses task service dependency injection."""
            return {
                "task_service_type": type(task_service).__name__,
                "agent_service_type": type(agent_service).__name__,
                "has_task_repository": hasattr(task_service, "task_repository"),
                "has_event_broker": hasattr(task_service, "event_broker"),
                "has_task_manager": hasattr(task_service, "task_manager"),
                "has_agent_repository": hasattr(task_service, "agent_repository"),
            }

        return app

    def test_task_service_dependency_injection_in_endpoint(
        self, test_app, mock_task_service, mock_agent_service
    ):
        """Test that task service dependency injection works in API endpoints."""
        client = TestClient(test_app)

        # Setup mock attributes
        mock_task_service.task_repository = MagicMock()
        mock_task_service.event_broker = MagicMock()
        mock_task_service.task_manager = MagicMock()
        mock_task_service.agent_repository = MagicMock()

        # Call the test endpoint
        response = client.get("/test-task-service")

        # Verify the response
        assert response.status_code == 200
        data = response.json()

        assert data["task_service_type"] == "AsyncMock"
        assert data["agent_service_type"] == "AsyncMock"
        assert data["has_task_repository"] is True
        assert data["has_event_broker"] is True
        assert data["has_task_manager"] is True
        assert data["has_agent_repository"] is True

    @pytest.mark.asyncio
    async def test_task_service_can_be_instantiated_with_real_dependencies(self):
        """Test that TaskService can be instantiated with real dependencies using dependency injection."""
        from agentarea_api.api.deps.services import get_event_broker

        # This test verifies that the dependency injection chain works with real components
        # We'll mock the database session but use real service instantiation
        with patch("agentarea_common.infrastructure.database.get_db_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value = mock_session

            # Get event broker (this should work with real implementation)
            event_broker = await get_event_broker()

            # Get task service with mocked session but real dependency chain
            task_service = await get_task_service(mock_session, event_broker)

            # Verify the service is properly instantiated
            assert isinstance(task_service, TaskService)
            assert hasattr(task_service, "task_repository")
            assert hasattr(task_service, "event_broker")
            assert hasattr(task_service, "task_manager")
            assert hasattr(task_service, "agent_repository")

            # Verify the dependencies are of the correct types
            from agentarea_agents.infrastructure.repository import AgentRepository
            from agentarea_common.events.broker import EventBroker
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager

            assert isinstance(task_service.task_repository, TaskRepository)
            assert isinstance(task_service.agent_repository, AgentRepository)
            assert isinstance(task_service.task_manager, TemporalTaskManager)
            assert isinstance(task_service.event_broker, EventBroker)

    @pytest.mark.asyncio
    async def test_task_service_methods_work_with_dependency_injection(self):
        """Test that TaskService methods work correctly with dependency injection."""
        # This test verifies that the dependency injection chain works correctly
        # by testing that we can instantiate the service and access its methods

        with patch("agentarea_common.infrastructure.database.get_db_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value = mock_session

            # Get event broker and task service
            event_broker = await get_event_broker()
            task_service = await get_task_service(mock_session, event_broker)

            # Test that the service has all required methods and attributes
            assert hasattr(task_service, "create_task")
            assert hasattr(task_service, "get_task")
            assert hasattr(task_service, "update_task")
            assert hasattr(task_service, "submit_task")
            assert hasattr(task_service, "cancel_task")

            # Test that dependencies are properly injected
            assert task_service.task_repository is not None
            assert task_service.event_broker is not None
            assert task_service.task_manager is not None
            assert task_service.agent_repository is not None

    def test_dependency_injection_type_annotations_are_correct(self):
        """Test that the dependency injection type annotations are correct."""
        from agentarea_api.api.deps.services import (
            AgentRepositoryDep,
            TaskManagerDep,
            TaskRepositoryDep,
            TaskServiceDep,
        )

        # Verify that the type annotations exist and are properly defined
        assert TaskServiceDep is not None
        assert TaskRepositoryDep is not None
        assert AgentRepositoryDep is not None
        assert TaskManagerDep is not None

        # These should be Annotated types with Depends
        from typing import Annotated, get_origin

        assert get_origin(TaskServiceDep) is Annotated
        assert get_origin(TaskRepositoryDep) is Annotated
        assert get_origin(AgentRepositoryDep) is Annotated
        assert get_origin(TaskManagerDep) is Annotated
