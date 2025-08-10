"""Integration tests for trigger service dependency injection."""

from unittest.mock import AsyncMock, patch

import pytest
from agentarea_api.api.deps.services import (
    TRIGGERS_AVAILABLE,
    get_trigger_execution_repository,
    get_trigger_health_check,
    get_trigger_repository,
    get_trigger_service,
    get_webhook_manager,
)
from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class TestTriggerServiceIntegration:
    """Test trigger service dependency injection integration."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker."""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_secret_manager(self):
        """Mock secret manager."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_trigger_repository_success(self, mock_db_session):
        """Test successful trigger repository creation."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        repository = await get_trigger_repository(mock_db_session)

        assert repository is not None
        assert hasattr(repository, 'create_from_model')
        assert hasattr(repository, 'get_by_id') or hasattr(repository, 'get')
        assert hasattr(repository, 'list_all') or hasattr(repository, 'list')

    @pytest.mark.asyncio
    async def test_get_trigger_execution_repository_success(self, mock_db_session):
        """Test successful trigger execution repository creation."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        repository = await get_trigger_execution_repository(mock_db_session)

        assert repository is not None
        assert hasattr(repository, 'create')
        assert hasattr(repository, 'get_by_trigger_id') or hasattr(repository, 'list_by_trigger_id') or hasattr(repository, 'list')

    @pytest.mark.asyncio
    async def test_get_trigger_service_success(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test successful trigger service creation with all dependencies."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        # Mock the dependencies that get_trigger_service calls
        with patch('agentarea_api.api.deps.services.get_trigger_repository') as mock_get_trigger_repo, \
             patch('agentarea_api.api.deps.services.get_trigger_execution_repository') as mock_get_exec_repo, \
             patch('agentarea_api.api.deps.services.get_agent_repository') as mock_get_agent_repo, \
             patch('agentarea_api.api.deps.services.get_task_service') as mock_get_task_service, \
             patch('agentarea_api.api.deps.services.get_model_instance_service') as mock_get_model_service:

            # Setup mocks
            mock_get_trigger_repo.return_value = AsyncMock()
            mock_get_exec_repo.return_value = AsyncMock()
            mock_get_agent_repo.return_value = AsyncMock()
            mock_get_task_service.return_value = AsyncMock()
            mock_get_model_service.return_value = AsyncMock()

            service = await get_trigger_service(
                mock_db_session,
                mock_event_broker,
                mock_secret_manager
            )

            assert service is not None
            assert hasattr(service, 'create_trigger')
            assert hasattr(service, 'get_trigger')
            assert hasattr(service, 'list_triggers')
            assert hasattr(service, 'execute_trigger')

    @pytest.mark.asyncio
    async def test_get_trigger_service_unavailable(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test trigger service creation when triggers are unavailable."""
        if TRIGGERS_AVAILABLE:
            # Temporarily mock TRIGGERS_AVAILABLE as False
            with patch('agentarea_api.api.deps.services.TRIGGERS_AVAILABLE', False):
                with pytest.raises(HTTPException) as exc_info:
                    await get_trigger_service(
                        mock_db_session,
                        mock_event_broker,
                        mock_secret_manager
                    )

                assert exc_info.value.status_code == 503
                assert "Triggers service not available" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_webhook_manager_success(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test successful webhook manager creation."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        # Mock the trigger service dependency
        with patch('agentarea_api.api.deps.services.get_trigger_service') as mock_get_service:
            mock_trigger_service = AsyncMock()
            mock_get_service.return_value = mock_trigger_service

            webhook_manager = await get_webhook_manager(
                mock_event_broker,
                mock_db_session,
                mock_secret_manager
            )

            assert webhook_manager is not None
            assert hasattr(webhook_manager, 'handle_webhook_request')

    @pytest.mark.asyncio
    async def test_get_webhook_manager_unavailable(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test webhook manager creation when triggers are unavailable."""
        if TRIGGERS_AVAILABLE:
            # Temporarily mock TRIGGERS_AVAILABLE as False
            with patch('agentarea_api.api.deps.services.TRIGGERS_AVAILABLE', False):
                webhook_manager = await get_webhook_manager(
                    mock_event_broker,
                    mock_db_session,
                    mock_secret_manager
                )

                # Should return mock webhook manager
                assert webhook_manager is not None
                assert hasattr(webhook_manager, 'handle_webhook_request')

                # Test that it returns unavailable status
                result = await webhook_manager.handle_webhook_request()
                assert result["status_code"] == 503
                assert "not available" in result["body"]["message"]

    @pytest.mark.asyncio
    async def test_get_trigger_health_check_success(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test successful trigger health check creation."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        # Mock all the dependencies
        with patch('agentarea_api.api.deps.services.get_trigger_repository') as mock_get_trigger_repo, \
             patch('agentarea_api.api.deps.services.get_trigger_execution_repository') as mock_get_exec_repo, \
             patch('agentarea_api.api.deps.services.get_webhook_manager') as mock_get_webhook:

            mock_get_trigger_repo.return_value = AsyncMock()
            mock_get_exec_repo.return_value = AsyncMock()
            mock_get_webhook.return_value = AsyncMock()

            health_checker = await get_trigger_health_check(
                mock_db_session,
                mock_event_broker,
                mock_secret_manager
            )

            assert health_checker is not None
            assert hasattr(health_checker, 'check_all_components')

    @pytest.mark.asyncio
    async def test_get_trigger_health_check_unavailable(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test trigger health check creation when triggers are unavailable."""
        if TRIGGERS_AVAILABLE:
            # Temporarily mock TRIGGERS_AVAILABLE as False
            with patch('agentarea_api.api.deps.services.TRIGGERS_AVAILABLE', False):
                health_checker = await get_trigger_health_check(
                    mock_db_session,
                    mock_event_broker,
                    mock_secret_manager
                )

                # Should return mock health checker
                assert health_checker is not None
                assert hasattr(health_checker, 'check_all_components')

                # Test that it returns unavailable status
                result = await health_checker.check_all_components()
                assert result["overall_status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_trigger_service_configuration_integration(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test that trigger service uses configuration settings correctly."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        settings = get_settings()

        # Verify trigger settings are loaded
        assert hasattr(settings, 'triggers')
        assert hasattr(settings.triggers, 'TRIGGER_FAILURE_THRESHOLD')
        assert hasattr(settings.triggers, 'WEBHOOK_BASE_URL')
        assert hasattr(settings.triggers, 'TEMPORAL_SCHEDULE_NAMESPACE')

        # Test that settings have reasonable defaults
        assert settings.triggers.TRIGGER_FAILURE_THRESHOLD > 0
        assert settings.triggers.WEBHOOK_BASE_URL.startswith('/')
        assert settings.triggers.TEMPORAL_SCHEDULE_NAMESPACE is not None

    @pytest.mark.asyncio
    async def test_service_dependency_chain(
        self,
        mock_db_session,
        mock_event_broker,
        mock_secret_manager
    ):
        """Test that all services in the dependency chain work together."""
        if not TRIGGERS_AVAILABLE:
            pytest.skip("Triggers not available")

        # Mock all intermediate dependencies
        with patch('agentarea_api.api.deps.services.get_trigger_repository') as mock_get_trigger_repo, \
             patch('agentarea_api.api.deps.services.get_trigger_execution_repository') as mock_get_exec_repo, \
             patch('agentarea_api.api.deps.services.get_agent_repository') as mock_get_agent_repo, \
             patch('agentarea_api.api.deps.services.get_task_service') as mock_get_task_service, \
             patch('agentarea_api.api.deps.services.get_model_instance_service') as mock_get_model_service:

            # Setup mocks
            mock_trigger_repo = AsyncMock()
            mock_exec_repo = AsyncMock()
            mock_agent_repo = AsyncMock()
            mock_task_service = AsyncMock()
            mock_model_service = AsyncMock()

            mock_get_trigger_repo.return_value = mock_trigger_repo
            mock_get_exec_repo.return_value = mock_exec_repo
            mock_get_agent_repo.return_value = mock_agent_repo
            mock_get_task_service.return_value = mock_task_service
            mock_get_model_service.return_value = mock_model_service

            # Test trigger service creation
            trigger_service = await get_trigger_service(
                mock_db_session,
                mock_event_broker,
                mock_secret_manager
            )

            # Test webhook manager creation (depends on trigger service)
            webhook_manager = await get_webhook_manager(
                mock_event_broker,
                mock_db_session,
                mock_secret_manager
            )

            # Test health check creation (depends on both)
            health_checker = await get_trigger_health_check(
                mock_db_session,
                mock_event_broker,
                mock_secret_manager
            )

            # Verify all services were created successfully
            assert trigger_service is not None
            assert webhook_manager is not None
            assert health_checker is not None

            # Verify dependencies were called
            mock_get_trigger_repo.assert_called()
            mock_get_exec_repo.assert_called()
            mock_get_agent_repo.assert_called()
            mock_get_task_service.assert_called()


class TestTriggerServiceConfigurationIntegration:
    """Test trigger service configuration integration."""

    def test_trigger_settings_loaded(self):
        """Test that trigger settings are properly loaded."""
        settings = get_settings()

        # Verify trigger settings exist
        assert hasattr(settings, 'triggers')

        # Verify key settings are present
        trigger_settings = settings.triggers
        assert hasattr(trigger_settings, 'TRIGGER_FAILURE_THRESHOLD')
        assert hasattr(trigger_settings, 'WEBHOOK_BASE_URL')
        assert hasattr(trigger_settings, 'TEMPORAL_SCHEDULE_NAMESPACE')
        assert hasattr(trigger_settings, 'ENABLE_LLM_CONDITIONS')

        # Verify settings have reasonable values
        assert trigger_settings.TRIGGER_FAILURE_THRESHOLD >= 1
        assert trigger_settings.WEBHOOK_BASE_URL.startswith('/')
        assert len(trigger_settings.TEMPORAL_SCHEDULE_NAMESPACE) > 0
        assert isinstance(trigger_settings.ENABLE_LLM_CONDITIONS, bool)

    def test_trigger_settings_environment_override(self):
        """Test that trigger settings support environment variable overrides."""
        from agentarea_common.config.triggers import TriggerSettings

        # Test that the settings class has the correct env_prefix
        trigger_settings = TriggerSettings()

        # Verify the model config has the correct env_prefix
        assert trigger_settings.model_config["env_prefix"] == "TRIGGER_"

        # Test that the settings can be instantiated properly
        assert trigger_settings.TRIGGER_FAILURE_THRESHOLD == 5  # Default value

    def test_trigger_settings_defaults(self):
        """Test that trigger settings have sensible defaults."""
        settings = get_settings()
        trigger_settings = settings.triggers

        # Test default values
        assert trigger_settings.TRIGGER_FAILURE_THRESHOLD == 5
        assert trigger_settings.TRIGGER_MAX_EXECUTIONS_PER_HOUR == 60
        assert trigger_settings.WEBHOOK_RATE_LIMIT_PER_MINUTE == 100
        assert trigger_settings.TRIGGER_EXECUTION_TIMEOUT_SECONDS == 300
        assert trigger_settings.WEBHOOK_BASE_URL == "/v1/webhooks"
        assert trigger_settings.ENABLE_LLM_CONDITIONS is True
        assert trigger_settings.ENABLE_WEBHOOK_VALIDATION is True
