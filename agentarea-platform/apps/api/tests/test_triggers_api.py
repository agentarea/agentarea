"""Integration tests for trigger management API endpoints.

This module tests the REST API endpoints for trigger CRUD operations,
lifecycle management, and execution history monitoring.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_trigger_health_check, get_trigger_service
from agentarea_api.api.v1.a2a_auth import require_a2a_execute_auth
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.config.database import get_db_session
from agentarea_common.testing import allow_all_permissions, install_graph_ownership_stub
from agentarea_common.testing.flows import MainFlow
from agentarea_streams.domain.models import TriggerBinding
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _graph_ownership(monkeypatch):
    """Creating a row records ownership; here the graph is scenery.

    ``libs/common/tests/test_graph_resource_ownership.py`` is where that write
    is the subject.
    """
    allow_all_permissions()
    return install_graph_ownership_stub(monkeypatch)


# Mock trigger system components when not available
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType
    from agentarea_triggers.domain.models import (
        CronTrigger,
        StreamTrigger,
        Trigger,
        TriggerCreate,
        TriggerExecution,
        TriggerUpdate,
    )
    from agentarea_triggers.trigger_service import (
        TriggerNotFoundError,
        TriggerService,
        TriggerValidationError,
    )
except ImportError:
    # Create mock classes for testing
    class TriggerType:
        CRON = "cron"
        STREAM = "stream"

    class ExecutionStatus:
        SUCCESS = "success"
        FAILED = "failed"
        TIMEOUT = "timeout"

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

    class StreamTrigger(Trigger):
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
    service.stream_service = AsyncMock()
    service.stream_service.trigger_bindings.return_value = {}
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


@pytest.fixture
def mock_db_session():
    """Session for the spend join: no rows, so every run reads as uncosted."""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    result.one.return_value = MagicMock(total=0, costed=0)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture(autouse=True)
def override_trigger_dependencies(
    mock_trigger_service, mock_auth_context, mock_health_checker, mock_db_session
):
    async def _override_trigger_service():
        return mock_trigger_service

    async def _override_auth():
        return mock_auth_context

    async def _override_health_checker():
        return mock_health_checker

    async def _override_db_session():
        return mock_db_session

    app.dependency_overrides[get_trigger_service] = _override_trigger_service
    app.dependency_overrides[require_a2a_execute_auth] = _override_auth
    app.dependency_overrides[get_trigger_health_check] = _override_health_checker
    app.dependency_overrides[get_db_session] = _override_db_session
    yield
    app.dependency_overrides.pop(get_trigger_service, None)
    app.dependency_overrides.pop(require_a2a_execute_auth, None)
    app.dependency_overrides.pop(get_trigger_health_check, None)
    app.dependency_overrides.pop(get_db_session, None)


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
def sample_stream_trigger_data():
    """Sample stream trigger data for testing."""
    return {
        "id": uuid4(),
        "name": "Test Stream Trigger",
        "description": "A test stream trigger",
        "agent_id": uuid4(),
        "trigger_type": TriggerType.STREAM,
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

    @pytest.mark.flow(MainFlow.TRIGGERS)
    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.post("/v1/workspaces/acme/triggers/", json=request_data)

        # Assertions
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Trigger"
        assert data["trigger_type"] == "cron"
        assert data["cron_expression"] == "0 9 * * *"
        assert data["is_active"] is True

        # Verify service was called
        mock_trigger_service.create_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_stream_trigger_success(
        self,
        async_client,
        mock_trigger_service,
        sample_stream_trigger_data,
    ):
        """A stream trigger is created on its stream and reports the binding."""
        trigger = StreamTrigger(**sample_stream_trigger_data)
        mock_trigger_service.create_trigger.return_value = trigger
        stream_id = uuid4()
        mock_trigger_service.stream_service.trigger_bindings.return_value = {
            trigger.id: TriggerBinding(stream_id=stream_id, event_filter={}, last_event_at=None)
        }

        response = await async_client.post(
            "/v1/workspaces/acme/triggers/",
            json={
                "name": "Test Stream Trigger",
                "description": "A test stream trigger",
                "agent_id": str(sample_stream_trigger_data["agent_id"]),
                "trigger_type": "stream",
                "stream_id": str(stream_id),
                "session": {"continue": True, "idle_timeout": "30m"},
            },
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["name"] == "Test Stream Trigger"
        assert data["trigger_type"] == "stream"
        assert data["stream_id"] == str(stream_id)
        created = mock_trigger_service.create_trigger.await_args.args[0]
        assert created.stream_id == stream_id
        assert created.session is not None and created.session.continue_ is True

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.post("/v1/workspaces/acme/triggers/", json=request_data)

        # Assertions
        assert response.status_code == 400
        assert "Invalid cron expression" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.get("/v1/workspaces/acme/triggers/")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Trigger"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
            f"/v1/workspaces/acme/triggers/?agent_id={agent_id}&trigger_type=cron&active_only=true&limit=50"
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
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.get(f"/v1/workspaces/acme/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Trigger"
        assert data["id"] == trigger_id

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.get(f"/v1/workspaces/acme/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        mock_trigger_service.update_trigger_from_payload.return_value = updated_trigger

        # Test data
        request_data = {
            "name": "Updated Trigger",
            "description": "Updated description",
            "is_active": False,
        }

        # Make request
        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.put(
            f"/v1/workspaces/acme/triggers/{trigger_id}", json=request_data
        )

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Trigger"
        assert data["description"] == "Updated description"

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
    async def test_update_trigger_not_found(
        self, mock_auth, mock_get_service, async_client, mock_trigger_service, mock_auth_context
    ):
        """Test trigger update when not found."""
        # Setup mocks
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.update_trigger_from_payload.side_effect = TriggerNotFoundError(
            "Trigger not found"
        )

        # Test data
        request_data = {"name": "Updated Trigger"}

        # Make request
        trigger_id = str(uuid4())
        response = await async_client.put(
            f"/v1/workspaces/acme/triggers/{trigger_id}", json=request_data
        )

        # Assertions
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.delete(f"/v1/workspaces/acme/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 204

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.delete(f"/v1/workspaces/acme/triggers/{trigger_id}")

        # Assertions
        assert response.status_code == 404

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/enable")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is True

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/disable")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["is_active"] is False

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.get(f"/v1/workspaces/acme/triggers/{trigger_id}/executions")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert len(data["executions"]) == 1
        assert data["executions"][0]["status"] == "success"
        assert data["page"] == 1
        assert data["page_size"] == 50

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
    async def test_get_execution_history_filters_by_status(
        self,
        mock_auth,
        mock_get_service,
        async_client,
        mock_trigger_service,
        mock_auth_context,
        sample_trigger_data,
    ):
        mock_auth.return_value = mock_auth_context
        mock_get_service.return_value = mock_trigger_service
        mock_trigger_service.get_trigger.return_value = CronTrigger(**sample_trigger_data)
        mock_trigger_service.get_execution_history_paginated.return_value = ([], 0)

        trigger_id = str(sample_trigger_data["id"])
        response = await async_client.get(
            f"/v1/workspaces/acme/triggers/{trigger_id}/executions?status=skipped"
        )

        assert response.status_code == 200
        kwargs = mock_trigger_service.get_execution_history_paginated.await_args.kwargs
        assert kwargs["status"] == ExecutionStatus.SKIPPED

    @patch("agentarea_api.api.deps.services.get_trigger_service")
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
            f"/v1/workspaces/acme/triggers/{trigger_id}/executions?page=2&page_size=25"
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
    @patch("agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth")
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
        response = await async_client.get(f"/v1/workspaces/acme/triggers/{trigger_id}/status")

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
        response = await async_client.get("/v1/workspaces/acme/triggers/health")

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
        mock_health_checker.check_all_components.side_effect = Exception(
            "Database connection failed"
        )

        # Make request
        response = await async_client.get("/v1/workspaces/acme/triggers/health")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "unhealthy"
        assert data["service"] == "triggers"
        # Internal error details must not leak to clients: the endpoint returns a
        # generic message and logs the real exception with exc_info instead.
        assert data["error"] == "health check failed"
        assert "Database connection failed" not in str(data)

    async def test_invalid_trigger_type(self, async_client):
        """Test trigger creation with invalid trigger type."""
        request_data = {
            "name": "Test Trigger",
            "agent_id": str(uuid4()),
            "trigger_type": "invalid_type",
        }

        response = await async_client.post("/v1/workspaces/acme/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422
        assert "Invalid trigger type" in str(response.json())

    async def test_webhook_is_not_a_trigger_type(self, async_client):
        """A webhook is a source of a stream now, not a trigger."""
        response = await async_client.post(
            "/v1/workspaces/acme/triggers/",
            json={"name": "Webhook", "agent_id": str(uuid4()), "trigger_type": "webhook"},
        )

        assert response.status_code == 422
        assert "Invalid trigger type" in str(response.json())

    async def test_missing_required_fields(self, async_client):
        """Test trigger creation with missing required fields."""
        request_data = {"description": "Missing required fields"}

        response = await async_client.post("/v1/workspaces/acme/triggers/", json=request_data)

        # Should fail validation
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__])


class TestExecuteTrigger:
    """POST /v1/workspaces/acme/triggers/{id}/execute -- the answer is the execution's outcome."""

    def test_an_execution_that_failed_is_not_reported_as_success(
        self, client, mock_trigger_service
    ):
        trigger_id = uuid4()
        mock_trigger_service.execute_trigger.return_value = MagicMock(
            id=uuid4(),
            task_id=None,
            status=ExecutionStatus.FAILED,
            error_message="Trigger has no task text",
        )

        response = client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/execute", json={})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "failed"
        assert body["reason"] == "Trigger has no task text"
        assert body["task_id"] is None

    def test_an_execution_that_started_a_task_is_success(self, client, mock_trigger_service):
        task_id = uuid4()
        mock_trigger_service.execute_trigger.return_value = MagicMock(
            id=uuid4(), task_id=task_id, status=ExecutionStatus.SUCCESS, error_message=None
        )

        response = client.post(f"/v1/workspaces/acme/triggers/{uuid4()}/execute", json={})

        body = response.json()
        assert body["status"] == "success"
        assert body["task_id"] == str(task_id)


class TestRunTriggerNow:
    """POST /v1/workspaces/acme/triggers/{id}/run -- firing a trigger once by hand."""

    def test_it_reports_the_task_to_watch(self, client, mock_trigger_service):
        trigger_id = uuid4()
        task_id = uuid4()
        mock_trigger_service.execute_trigger.return_value = MagicMock(
            id=uuid4(), task_id=task_id, error_message=None
        )

        response = client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/run")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "started"
        assert body["task_id"] == str(task_id)

    def test_it_records_the_caller_as_having_asked_for_the_run(self, client, mock_trigger_service):
        """Without this the run is indistinguishable from the schedule firing."""
        trigger_id = uuid4()
        mock_trigger_service.execute_trigger.return_value = MagicMock(
            id=uuid4(), task_id=uuid4(), error_message=None
        )

        client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/run")

        assert mock_trigger_service.execute_trigger.call_args.kwargs["fired_by"] == "test_user"

    def test_a_run_the_conditions_rejected_is_skipped_not_failed(
        self, client, mock_trigger_service
    ):
        """The trigger answering "not now" is a result, not an error."""
        trigger_id = uuid4()
        mock_trigger_service.execute_trigger.return_value = MagicMock(
            id=uuid4(), task_id=None, error_message="Trigger conditions not met"
        )

        response = client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/run")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "skipped"
        assert body["task_id"] is None
        assert body["reason"] == "Trigger conditions not met"

    def test_a_trigger_this_workspace_cannot_see_is_404(self, client, mock_trigger_service):
        trigger_id = uuid4()
        mock_trigger_service.execute_trigger.side_effect = TriggerNotFoundError("nope")

        response = client.post(f"/v1/workspaces/acme/triggers/{trigger_id}/run")

        assert response.status_code == 404


class _StreamReaders:
    """Allows everything except reading the streams in ``unreadable``; records each check."""

    def __init__(self, *unreadable: str) -> None:
        self.unreadable = set(unreadable)
        self.checks: list[tuple[str, str, str, str]] = []

    async def check(self, user_id: str, permission: str, resource_type: str, resource_id: str):
        self.checks.append((user_id, permission, resource_type, resource_id))
        return not (
            permission == "read" and resource_type == "stream" and resource_id in self.unreadable
        )


def _stream_trigger_body(stream_id: str) -> dict:
    return {
        "name": "On push",
        "agent_id": str(uuid4()),
        "trigger_type": "stream",
        "stream_id": stream_id,
        "task_parameters": {"text": "Summarise the push"},
    }


async def test_a_stream_trigger_on_a_stream_its_creator_may_not_read_is_refused(
    async_client, mock_trigger_service
):
    from agentarea_common.auth.permission import PermissionService
    from agentarea_common.di.container import register_singleton

    stream_id = str(uuid4())
    register_singleton(PermissionService, _StreamReaders(stream_id))

    response = await async_client.post(
        "/v1/workspaces/acme/triggers/", json=_stream_trigger_body(stream_id)
    )

    assert response.status_code == 403, response.text
    mock_trigger_service.create_trigger.assert_not_called()


async def test_a_stream_trigger_checks_its_creator_may_read_the_stream(
    async_client, mock_trigger_service
):
    from agentarea_common.auth.permission import PermissionService
    from agentarea_common.di.container import register_singleton
    from agentarea_triggers.domain.enums import TriggerType as DomainTriggerType
    from agentarea_triggers.domain.models import Trigger as DomainTrigger

    stream_id = str(uuid4())
    pdp = _StreamReaders()
    register_singleton(PermissionService, pdp)
    mock_trigger_service.create_trigger.return_value = DomainTrigger(
        name="On push",
        agent_id=uuid4(),
        trigger_type=DomainTriggerType.STREAM,
        created_by="test_user",
        workspace_id="w",
    )

    response = await async_client.post(
        "/v1/workspaces/acme/triggers/", json=_stream_trigger_body(stream_id)
    )

    assert response.status_code == 201, response.text
    assert ("test_user", "read", "stream", stream_id) in pdp.checks
