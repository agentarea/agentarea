"""Simple integration tests for trigger management API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_secret_manager, get_trigger_health_check, get_trigger_service
from agentarea_api.api.v1.triggers import require_a2a_execute_auth
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_trigger_service():
    """Create mock trigger service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_auth_context():
    """Create mock authentication context."""
    context = MagicMock()
    context.user_id = "test_user"
    return context


@pytest.fixture
def mock_health_checker():
    checker = AsyncMock()
    checker.check_all_components = AsyncMock()
    return checker


@pytest.fixture(autouse=True)
def override_user_context(mock_auth_context):
    async def _override():
        return mock_auth_context

    app.dependency_overrides[get_user_context] = _override
    yield
    app.dependency_overrides.pop(get_user_context, None)


@pytest.fixture(autouse=True)
def override_trigger_dependencies(mock_trigger_service, mock_auth_context, mock_health_checker):
    async def _override_trigger_service():
        return mock_trigger_service

    async def _override_auth():
        return mock_auth_context

    async def _override_health_checker():
        return mock_health_checker

    async def _override_secret_manager():
        return AsyncMock()

    app.dependency_overrides[get_trigger_service] = _override_trigger_service
    app.dependency_overrides[require_a2a_execute_auth] = _override_auth
    app.dependency_overrides[get_trigger_health_check] = _override_health_checker
    app.dependency_overrides[get_secret_manager] = _override_secret_manager
    yield
    app.dependency_overrides.pop(get_trigger_service, None)
    app.dependency_overrides.pop(require_a2a_execute_auth, None)
    app.dependency_overrides.pop(get_trigger_health_check, None)
    app.dependency_overrides.pop(get_secret_manager, None)


def create_mock_trigger():
    """Create a mock trigger object without rate limiting fields."""
    mock_trigger = MagicMock()
    mock_trigger.id = uuid4()
    mock_trigger.name = "Test Trigger"
    mock_trigger.trigger_type = "cron"
    mock_trigger.is_active = True
    mock_trigger.cron_expression = "0 9 * * *"
    mock_trigger.agent_id = uuid4()
    mock_trigger.description = "A test trigger"
    mock_trigger.task_parameters = {"param1": "value1"}
    mock_trigger.conditions = {"condition1": "value1"}
    mock_trigger.created_at = datetime.utcnow()
    mock_trigger.updated_at = datetime.utcnow()
    mock_trigger.created_by = "test_user"
    mock_trigger.failure_threshold = 5
    mock_trigger.consecutive_failures = 0
    mock_trigger.last_execution_at = None
    mock_trigger.timezone = "UTC"
    mock_trigger.next_run_time = None
    mock_trigger.webhook_id = None
    mock_trigger.allowed_methods = None
    mock_trigger.webhook_type = None
    mock_trigger.validation_rules = None
    mock_trigger.webhook_config = None
    return mock_trigger


class TestTriggersAPISimple:
    """Simple test class for triggers API endpoints."""

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_create_trigger_success_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger creation using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Mock trigger object
        mock_trigger = create_mock_trigger()
        mock_trigger_service.create_trigger.return_value = mock_trigger

        # Test data
        request_data = {
            "name": "Test Trigger",
            "description": "A test trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "cron",
            "task_parameters": {"param1": "value1"},
            "conditions": {"condition1": "value1"},
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        }

        # Make request
        response = client.post("/v1/triggers/", json=request_data)

        # Assertions
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Trigger"
        assert data["trigger_type"] == "cron"
        assert data["cron_expression"] == "0 9 * * *"
        assert data["is_active"] is True

        # Verify service was called
        mock_trigger_service.create_trigger.assert_called_once()

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_list_triggers_success_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger listing using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Mock trigger objects
        mock_trigger = create_mock_trigger()
        triggers = [mock_trigger]
        mock_trigger_service.list_triggers.return_value = triggers

        # Make request
        response = client.get("/v1/triggers/")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Trigger"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_get_trigger_success_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger retrieval using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        mock_trigger = create_mock_trigger()
        trigger_id = mock_trigger.id
        mock_trigger_service.get_trigger.return_value = mock_trigger

        # Make request
        response = client.get(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Trigger"
        assert data["id"] == str(trigger_id)

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_get_trigger_not_found_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger retrieval when not found using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.get_trigger.return_value = None

        # Make request
        trigger_id = str(uuid4())
        response = client.get(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_delete_trigger_success_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger deletion using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.delete_trigger.return_value = True

        # Make request
        trigger_id = str(uuid4())
        response = client.delete(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 204

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    def test_enable_trigger_success_sync(
        self, mock_auth, mock_get_service, client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger enabling using sync client."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.enable_trigger.return_value = True

        # Make request
        trigger_id = str(uuid4())
        response = client.post(f"/v1/triggers/{trigger_id}/enable")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is True

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    def test_triggers_health_check_success_sync(
        self, mock_get_service, client, mock_trigger_service, mock_health_checker
    ):
        """Test successful triggers health check using sync client."""
        # Setup mocks
        mock_get_service.return_value = mock_trigger_service
        mock_health_checker.check_all_components.return_value = {
            "overall_status": "healthy",
            "components": {},
        }

        # Make request
        response = client.get("/v1/triggers/health")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "healthy"
        assert data["service"] == "triggers"

    def test_invalid_trigger_type_sync(self, client):
        """Test trigger creation with invalid trigger type using sync client."""
        request_data = {
            "name": "Test Trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "invalid_type",
        }

        response = client.post("/v1/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422
        assert "Invalid trigger type" in str(response.json())

    def test_missing_required_fields_sync(self, client):
        """Test trigger creation with missing required fields using sync client."""
        request_data = {"description": "Missing required fields"}

        response = client.post("/v1/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422

    @patch("agentarea_api.api.v1.triggers.TRIGGERS_AVAILABLE", False)
    def test_triggers_not_available_sync(self, client):
        """Test API behavior when triggers service is not available using sync client."""
        response = client.get("/v1/triggers/health")

        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "unavailable"
        assert "not available" in data["message"]


if __name__ == "__main__":
    pytest.main([__file__])
