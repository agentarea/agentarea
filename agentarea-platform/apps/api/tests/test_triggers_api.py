"""Integration tests for trigger management API endpoints.

This module tests the REST API endpoints for trigger CRUD operations,
lifecycle management, and execution history monitoring.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_secret_manager, get_trigger_health_check, get_trigger_service
from agentarea_api.api.v1.triggers import require_a2a_execute_auth
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Mock trigger system components when not available
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
    from agentarea_triggers.domain.models import (
        CronTrigger,
        Trigger,
        TriggerCreate,
        TriggerExecution,
        TriggerUpdate,
        WebhookTrigger,
    )
    from agentarea_triggers.trigger_service import (
        TriggerNotFoundError,
        TriggerService,
        TriggerValidationError,
    )

    TRIGGERS_AVAILABLE = True
except ImportError:
    # Create mock classes for testing
    class TriggerType:
        CRON = "cron"
        WEBHOOK = "webhook"

    class ExecutionStatus:
        SUCCESS = "success"
        FAILED = "failed"
        TIMEOUT = "timeout"

    class WebhookType:
        GENERIC = "generic"
        TELEGRAM = "telegram"

    class Trigger:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def is_rate_limited(self):
            return False

        def should_disable_due_to_failures(self):
            return False

    class CronTrigger(Trigger):
        pass

    class WebhookTrigger(Trigger):
        pass

    class TriggerExecution:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class TriggerCreate:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class TriggerUpdate:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class TriggerService:
        pass

    class TriggerValidationError(Exception):
        pass

    class TriggerNotFoundError(Exception):
        pass

    TRIGGERS_AVAILABLE = False


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_trigger_service():
    """Create mock trigger service."""
    service = AsyncMock(spec=TriggerService)
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


@pytest.fixture
def sample_trigger_data():
    """Sample trigger data for testing."""
    return {
        "id": uuid4(),
        "name": "Test Trigger",
        "description": "A test trigger",
        "agent_id": uuid4(),
        "trigger_type": TriggerType.CRON,
        "is_active": True,
        "task_parameters": {"param1": "value1"},
        "conditions": {"condition1": "value1"},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "test_user",
        "max_executions_per_hour": 60,
        "failure_threshold": 5,
        "consecutive_failures": 0,
        "last_execution_at": None,
        "cron_expression": "0 9 * * *",
        "timezone": "UTC",
        "next_run_time": None,
    }


@pytest.fixture
def sample_webhook_trigger_data():
    """Sample webhook trigger data for testing."""
    return {
        "id": uuid4(),
        "name": "Test Webhook Trigger",
        "description": "A test webhook trigger",
        "agent_id": uuid4(),
        "trigger_type": TriggerType.WEBHOOK,
        "is_active": True,
        "task_parameters": {"param1": "value1"},
        "conditions": {"condition1": "value1"},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "test_user",
        "max_executions_per_hour": 60,
        "failure_threshold": 5,
        "consecutive_failures": 0,
        "last_execution_at": None,
        "webhook_id": "test_webhook_123",
        "allowed_methods": ["POST"],
        "webhook_type": WebhookType.GENERIC,
        "validation_rules": {},
        "webhook_config": None,
    }


@pytest.fixture
def sample_execution_data():
    """Sample execution data for testing."""
    return {
        "id": uuid4(),
        "trigger_id": uuid4(),
        "executed_at": datetime.utcnow(),
        "status": ExecutionStatus.SUCCESS,
        "task_id": uuid4(),
        "execution_time_ms": 1500,
        "error_message": None,
        "trigger_data": {"event": "test"},
        "workflow_id": "workflow_123",
        "run_id": "run_456",
    }


class TestTriggersAPI:
    """Test class for triggers API endpoints."""

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    @pytest.mark.asyncio
    async def test_create_trigger_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test successful trigger creation."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Create trigger object
        trigger = CronTrigger(**sample_trigger_data)
        mock_trigger_service.create_trigger.return_value = trigger

        # Test data
        request_data = {
            "name": "Test Trigger",
            "description": "A test trigger",
            "agent_id": str(sample_trigger_data["agent_id"]),
            "trigger_type": "cron",
            "task_parameters": {"param1": "value1"},
            "conditions": {"condition1": "value1"},
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        }

        # Make request
        response = await async_client.post("/v1/triggers/", json=request_data)

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
    @pytest.mark.asyncio
    async def test_create_webhook_trigger_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_webhook_trigger_data,
    ):
        """Test successful webhook trigger creation."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Create trigger object
        trigger = WebhookTrigger(**sample_webhook_trigger_data)
        mock_trigger_service.create_trigger.return_value = trigger

        # Test data
        request_data = {
            "name": "Test Webhook Trigger",
            "description": "A test webhook trigger",
            "agent_id": str(sample_webhook_trigger_data["agent_id"]),
            "trigger_type": "webhook",
            "webhook_id": "test_webhook_123",
            "allowed_methods": ["POST"],
            "webhook_type": "generic",
        }

        # Make request
        response = await async_client.post("/v1/triggers/", json=request_data)

        # Assertions
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Webhook Trigger"
        assert data["trigger_type"] == "webhook"
        assert data["webhook_id"] == "test_webhook_123"
        assert data["allowed_methods"] == ["POST"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    @pytest.mark.asyncio
    async def test_create_trigger_validation_error(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger creation with validation error."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.create_trigger.side_effect = TriggerValidationError(
            "Invalid cron expression"
        )

        # Test data with invalid cron expression
        request_data = {
            "name": "Test Trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "cron",
            "cron_expression": "invalid cron",
        }

        # Make request
        response = await async_client.post("/v1/triggers/", json=request_data)

        # Assertions
        assert response.status_code == 400
        assert "Invalid cron expression" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    @pytest.mark.asyncio
    async def test_list_triggers_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test successful trigger listing."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Create trigger objects
        triggers = [CronTrigger(**sample_trigger_data)]
        mock_trigger_service.list_triggers.return_value = triggers

        # Make request
        response = await async_client.get("/v1/triggers/")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Trigger"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_list_triggers_with_filters(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger listing with filters."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.list_triggers.return_value = []

        # Make request with filters
        agent_id = str(uuid4())
        response = await async_client.get(
            f"/v1/triggers/?agent_id={agent_id}&trigger_type=cron&active_only=true&limit=50"
        )

        # Assertions
        assert response.status_code == 200

        # Verify service was called with correct parameters
        mock_trigger_service.list_triggers.assert_called_once()
        call_args = mock_trigger_service.list_triggers.call_args
        assert str(call_args.kwargs["agent_id"]) == agent_id
        assert call_args.kwargs["active_only"] is True
        assert call_args.kwargs["limit"] == 50

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_get_trigger_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test successful trigger retrieval."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        trigger = CronTrigger(**sample_trigger_data)
        mock_trigger_service.get_trigger.return_value = trigger

        # Make request
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.get(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Trigger"
        assert data["id"] == trigger_id

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_get_trigger_not_found(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger retrieval when not found."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.get_trigger.return_value = None

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.get(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_update_trigger_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test successful trigger update."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        # Create updated trigger
        updated_data = sample_trigger_data.copy()
        updated_data["name"] = "Updated Trigger"
        updated_data["description"] = "Updated description"
        updated_trigger = CronTrigger(**updated_data)
        mock_trigger_service.update_trigger.return_value = updated_trigger

        # Test data
        request_data = {
            "name": "Updated Trigger",
            "description": "Updated description",
            "is_active": False,
        }

        # Make request
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.put(f"/v1/triggers/{trigger_id}", json=request_data)

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Trigger"
        assert data["description"] == "Updated description"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_update_trigger_not_found(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger update when not found."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.update_trigger.side_effect = TriggerNotFoundError("Trigger not found")

        # Test data
        request_data = {"name": "Updated Trigger"}

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.put(f"/v1/triggers/{trigger_id}", json=request_data)

        # Assertions
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_delete_trigger_success(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger deletion."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.delete_trigger.return_value = True

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.delete(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 204

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_delete_trigger_not_found(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger deletion when not found."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.delete_trigger.return_value = False

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.delete(f"/v1/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 404

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_enable_trigger_success(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger enabling."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.enable_trigger.return_value = True

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.post(f"/v1/triggers/{trigger_id}/enable")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is True

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_disable_trigger_success(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test successful trigger disabling."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.disable_trigger.return_value = True

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.post(f"/v1/triggers/{trigger_id}/disable")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is False

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_get_execution_history_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
        sample_execution_data,
    ):
        """Test successful execution history retrieval."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        trigger = CronTrigger(**sample_trigger_data)
        mock_trigger_service.get_trigger.return_value = trigger

        executions = [TriggerExecution(**sample_execution_data)]
        mock_trigger_service.get_execution_history_paginated.return_value = (executions, 1)

        # Make request
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.get(f"/v1/triggers/{trigger_id}/executions")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data["executions"]) == 1
        assert data["executions"][0]["status"] == "success"
        assert data["page"] == 1
        assert data["page_size"] == 50

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_get_execution_history_with_pagination(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test execution history retrieval with pagination."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        trigger = CronTrigger(**sample_trigger_data)
        mock_trigger_service.get_trigger.return_value = trigger
        mock_trigger_service.get_execution_history_paginated.return_value = ([], 25)

        # Make request with pagination
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.get(
            f"/v1/triggers/{trigger_id}/executions?page=2&page_size=25"
        )

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 25

        # Verify service was called with correct parameters
        mock_trigger_service.get_execution_history_paginated.assert_called_once()
        call_args = mock_trigger_service.get_execution_history_paginated.call_args
        assert call_args.kwargs["limit"] == 25
        assert call_args.kwargs["offset"] == 25

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth")
    async def test_get_trigger_status_success(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        """Test successful trigger status retrieval."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service

        trigger = CronTrigger(**sample_trigger_data)
        mock_trigger_service.get_trigger.return_value = trigger
        mock_trigger_service.get_cron_schedule_info.return_value = {
            "next_run_time": "2025-01-22T09:00:00Z",
            "is_paused": False,
        }

        # Make request
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.get(f"/v1/triggers/{trigger_id}/status")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["trigger_id"] == trigger_id
        assert data["is_active"] is True
        assert data["consecutive_failures"] == 0
        assert data["should_disable_due_to_failures"] is False
        assert data["schedule_info"] is not None

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    async def test_triggers_health_check_success(
        self, mock_get_service, async_client, mock_trigger_service, mock_health_checker
    ):
        """Test successful triggers health check."""
        # Setup mocks
        mock_get_service.return_value = mock_trigger_service
        mock_health_checker.check_all_components.return_value = {
            "overall_status": "healthy",
            "components": {},
        }

        # Make request
        response = await async_client.get("/v1/triggers/health")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "healthy"
        assert data["service"] == "triggers"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    async def test_triggers_health_check_failure(
        self, mock_get_service, async_client, mock_trigger_service, mock_health_checker
    ):
        """Test triggers health check when service fails."""
        # Setup mocks
        mock_get_service.return_value = mock_trigger_service
        mock_health_checker.check_all_components.side_effect = Exception("Database connection failed")

        # Make request
        response = await async_client.get("/v1/triggers/health")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "unhealthy"
        assert data["service"] == "triggers"
        assert "Database connection failed" in data["error"]

    async def test_invalid_trigger_type(self, async_client):
        """Test trigger creation with invalid trigger type."""
        request_data = {
            "name": "Test Trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "invalid_type",
        }

        response = await async_client.post("/v1/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422
        assert "Invalid trigger type" in str(response.json())

    async def test_invalid_webhook_type(self, async_client):
        """Test trigger creation with invalid webhook type."""
        request_data = {
            "name": "Test Trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "webhook",
            "webhook_id": "test_webhook",
            "webhook_type": "invalid_webhook_type",
        }

        response = await async_client.post("/v1/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422
        assert "Invalid webhook type" in str(response.json())

    async def test_missing_required_fields(self, async_client):
        """Test trigger creation with missing required fields."""
        request_data = {"description": "Missing required fields"}

        response = await async_client.post("/v1/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422

    @patch("agentarea_api.api.v1.triggers.TRIGGERS_AVAILABLE", False)
    async def test_triggers_not_available(self, async_client):
        """Test API behavior when triggers service is not available."""
        response = await async_client.get("/v1/triggers/health")

        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "unavailable"
        assert "not available" in data["message"]


if __name__ == "__main__":
    pytest.main([__file__])
