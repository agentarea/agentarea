"""
Unit tests for dependency injection configuration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_api.api.deps.services import (
    get_task_service,
    get_task_repository,
    get_agent_repository,
    get_task_manager,
    get_event_broker,
)
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from agentarea_common.events.broker import EventBroker


class TestDependencyInjection:
    """Test cases for dependency injection configuration."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        session = AsyncMock(spec=AsyncSession)
        return session

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker."""
        broker = AsyncMock(spec=EventBroker)
        return broker

    @pytest.mark.asyncio
    async def test_get_task_repository(self, mock_db_session):
        """Test that get_task_repository returns a TaskRepository instance."""
        repository = await get_task_repository(mock_db_session)
        
        assert isinstance(repository, TaskRepository)
        assert repository.session == mock_db_session

    @pytest.mark.asyncio
    async def test_get_agent_repository(self, mock_db_session):
        """Test that get_agent_repository returns an AgentRepository instance."""
        repository = await get_agent_repository(mock_db_session)
        
        assert isinstance(repository, AgentRepository)
        assert repository.session == mock_db_session

    @pytest.mark.asyncio
    async def test_get_task_manager(self, mock_db_session):
        """Test that get_task_manager returns a TemporalTaskManager instance."""
        with patch('agentarea_api.api.deps.services.get_task_repository') as mock_get_repo:
            mock_task_repo = AsyncMock(spec=TaskRepository)
            mock_get_repo.return_value = mock_task_repo
            
            task_manager = await get_task_manager(mock_db_session)
            
            assert isinstance(task_manager, TemporalTaskManager)
            assert task_manager.task_repository == mock_task_repo
            mock_get_repo.assert_called_once_with(mock_db_session)

    @pytest.mark.asyncio
    async def test_get_task_service(self, mock_db_session, mock_event_broker):
        """Test that get_task_service returns a TaskService instance with all dependencies."""
        with patch('agentarea_api.api.deps.services.get_task_repository') as mock_get_task_repo, \
             patch('agentarea_api.api.deps.services.get_agent_repository') as mock_get_agent_repo:
            
            # Setup mocks
            mock_task_repo = AsyncMock(spec=TaskRepository)
            mock_agent_repo = AsyncMock(spec=AgentRepository)
            mock_get_task_repo.return_value = mock_task_repo
            mock_get_agent_repo.return_value = mock_agent_repo
            
            # Call the function
            task_service = await get_task_service(mock_db_session, mock_event_broker)
            
            # Verify the result
            assert isinstance(task_service, TaskService)
            assert task_service.task_repository == mock_task_repo
            assert task_service.event_broker == mock_event_broker
            assert task_service.agent_repository == mock_agent_repo
            assert isinstance(task_service.task_manager, TemporalTaskManager)
            
            # Verify dependencies were called correctly
            mock_get_task_repo.assert_called_once_with(mock_db_session)
            mock_get_agent_repo.assert_called_once_with(mock_db_session)

    @pytest.mark.asyncio
    async def test_task_service_dependencies_are_properly_injected(self, mock_db_session, mock_event_broker):
        """Test that TaskService can be instantiated with all required dependencies."""
        with patch('agentarea_api.api.deps.services.get_task_repository') as mock_get_task_repo, \
             patch('agentarea_api.api.deps.services.get_agent_repository') as mock_get_agent_repo:
            
            # Setup mocks
            mock_task_repo = AsyncMock(spec=TaskRepository)
            mock_agent_repo = AsyncMock(spec=AgentRepository)
            mock_get_task_repo.return_value = mock_task_repo
            mock_get_agent_repo.return_value = mock_agent_repo
            
            # Call the function
            task_service = await get_task_service(mock_db_session, mock_event_broker)
            
            # Test that the service can perform basic operations
            # This verifies that all dependencies are properly wired
            assert hasattr(task_service, 'task_repository')
            assert hasattr(task_service, 'event_broker')
            assert hasattr(task_service, 'task_manager')
            assert hasattr(task_service, 'agent_repository')
            
            # Test that the service inherits from BaseTaskService
            from agentarea_tasks.domain.base_service import BaseTaskService
            assert isinstance(task_service, BaseTaskService)

    @pytest.mark.asyncio
    async def test_event_broker_dependency(self):
        """Test that get_event_broker returns an EventBroker instance."""
        # This test verifies that get_event_broker can be called successfully
        # The actual implementation details are tested elsewhere
        event_broker = await get_event_broker()
        
        # Verify the result is an EventBroker instance
        assert hasattr(event_broker, 'publish')
        assert isinstance(event_broker, EventBroker)

    @pytest.mark.asyncio
    async def test_dependency_injection_chain(self, mock_db_session):
        """Test the complete dependency injection chain works correctly."""
        with patch('agentarea_api.api.deps.services.get_event_broker') as mock_get_broker:
            # Setup event broker mock
            mock_broker = AsyncMock(spec=EventBroker)
            mock_get_broker.return_value = mock_broker
            
            # Test the complete chain: get_task_service should work with real dependencies
            task_service = await get_task_service(mock_db_session, mock_broker)
            
            # Verify all components are properly instantiated
            assert isinstance(task_service, TaskService)
            assert isinstance(task_service.task_repository, TaskRepository)
            assert isinstance(task_service.agent_repository, AgentRepository)
            assert isinstance(task_service.task_manager, TemporalTaskManager)
            assert task_service.event_broker == mock_broker
            
            # Verify that the task manager has the same task repository as the service
            assert task_service.task_manager.task_repository == task_service.task_repository