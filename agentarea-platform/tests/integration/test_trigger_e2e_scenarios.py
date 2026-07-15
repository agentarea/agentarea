"""End-to-end integration tests for trigger system.

This module tests complete trigger workflows from creation through execution
and task creation, including real HTTP requests for webhook triggers and
full lifecycle management scenarios.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
    from agentarea_triggers.domain.models import (
        TriggerCreate,
    )
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import DefaultWebhookManager

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

# Import API components
from agentarea_api.api.deps.services import (
    TriggerServiceWebhookCallback,
    get_public_webhook_manager,
    get_secret_manager,
    get_trigger_service,
    get_webhook_manager,
)
from agentarea_api.api.v1.triggers import router as triggers_router
from agentarea_api.api.v1.webhooks import router as webhooks_router
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestTriggerE2EScenarios:
    """End-to-end integration tests for trigger system."""

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker for testing."""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service for testing."""
        task_service = AsyncMock(spec=TaskService)

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task.title = "Test Task"
        mock_task.status = "pending"
        task_service.route_or_submit_task.return_value = mock_task

        return task_service

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository for testing."""
        agent_repo = AsyncMock()

        # Mock agent existence check
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Test Agent"
        agent_repo.get.return_value = mock_agent

        return agent_repo

    @pytest.fixture
    def mock_temporal_schedule_manager(self):
        """Mock temporal schedule manager for testing."""
        return AsyncMock(spec=TemporalScheduleManager)

    @pytest.fixture
    def user_context(self):
        """Create a test user context for the repository factory."""
        return create_test_user_context(user_id="e2e-test-user", workspace_id="e2e-test-workspace")

    @pytest.fixture
    def repository_factory(self, db_session, user_context):
        """Create a repository factory backed by the test db session."""
        return RepositoryFactory(db_session, user_context)

    @pytest.fixture
    async def trigger_service(
        self,
        repository_factory,
        mock_event_broker,
        mock_agent_repository,
        mock_task_service,
        mock_temporal_schedule_manager,
    ):
        """Create trigger service with real repositories and mocked dependencies."""
        service = TriggerService(
            repository_factory=repository_factory,
            event_broker=mock_event_broker,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=mock_temporal_schedule_manager,
        )
        # Swap in the mock agent repository so agent-existence validation
        # doesn't require a real Agent row in the test database.
        service.agent_repository = mock_agent_repository
        return service

    @pytest.fixture
    async def webhook_manager(self, trigger_service, mock_event_broker):
        """Create webhook manager for testing."""
        execution_callback = TriggerServiceWebhookCallback(trigger_service)
        return DefaultWebhookManager(
            execution_callback=execution_callback,
            event_broker=mock_event_broker,
            trigger_service=trigger_service,
        )

    @pytest.fixture
    def test_app(self, trigger_service, webhook_manager):
        """Create test FastAPI app with trigger endpoints."""
        app = FastAPI()

        # Override dependencies
        app.dependency_overrides[get_trigger_service] = lambda: trigger_service
        app.dependency_overrides[get_webhook_manager] = lambda: webhook_manager
        app.dependency_overrides[get_public_webhook_manager] = lambda: webhook_manager
        app.dependency_overrides[get_user_context] = lambda: UserContext(
            user_id="test_user", workspace_id="e2e-test-workspace"
        )
        mock_secret_manager = AsyncMock()
        mock_secret_manager.get_secret.return_value = None
        app.dependency_overrides[get_secret_manager] = lambda: mock_secret_manager

        # Include trigger router
        app.include_router(triggers_router, prefix="/v1")

        # Webhook receiver is mounted outside /v1 in the real app (bypasses
        # auth middleware) -- see apps/api/agentarea_api/main.py.
        app.include_router(webhooks_router)

        return app

    @pytest.fixture
    def test_client(self, test_app):
        """Create test client for API testing."""
        return TestClient(test_app)

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # End-to-End Trigger Creation and Execution Tests

    async def test_complete_cron_trigger_lifecycle(
        self, trigger_service, mock_temporal_schedule_manager, mock_task_service, sample_agent_id
    ):
        """Test complete lifecycle of a cron trigger from creation to execution."""
        # Step 1: Create cron trigger
        trigger_data = TriggerCreate(
            name="Daily Report Trigger",
            description="Generate daily reports at 9 AM",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * 1-5",  # 9 AM weekdays
            timezone="UTC",
            task_parameters={"report_type": "daily", "format": "pdf"},
            conditions={"business_hours": True},
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created
        assert created_trigger.id is not None
        assert created_trigger.name == "Daily Report Trigger"
        assert created_trigger.trigger_type == TriggerType.CRON
        assert created_trigger.is_active is True

        # Verify schedule was created
        mock_temporal_schedule_manager.create_cron_schedule.assert_called_once()

        # Step 2: Simulate trigger execution
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "source": "cron",
            "schedule_info": {"next_run": "2024-01-02T09:00:00Z"},
        }

        execution_result = await trigger_service.execute_trigger(created_trigger.id, execution_data)

        # Verify execution was successful
        assert execution_result.status == ExecutionStatus.SUCCESS
        assert execution_result.task_id is not None
        assert execution_result.execution_time_ms >= 0

        # Verify task was created with correct parameters
        mock_task_service.route_or_submit_task.assert_called_once()
        call_args = mock_task_service.route_or_submit_task.call_args

        task_params = call_args.args[0].task_parameters
        assert task_params["trigger_id"] == str(created_trigger.id)
        assert task_params["trigger_type"] == "cron"
        assert task_params["report_type"] == "daily"
        assert task_params["format"] == "pdf"

        # Step 3: Test trigger lifecycle management
        # Disable trigger
        disable_result = await trigger_service.disable_trigger(created_trigger.id)
        assert disable_result is True

        # Verify schedule was paused
        mock_temporal_schedule_manager.pause_cron_schedule.assert_called_once()

        # Re-enable trigger
        enable_result = await trigger_service.enable_trigger(created_trigger.id)
        assert enable_result is True

        # Verify schedule was resumed
        mock_temporal_schedule_manager.unpause_cron_schedule.assert_called_once()

        # Step 4: Delete trigger
        delete_result = await trigger_service.delete_trigger(created_trigger.id)
        assert delete_result is True

        # Verify schedule was deleted
        mock_temporal_schedule_manager.delete_cron_schedule.assert_called_once()

    async def test_complete_webhook_trigger_lifecycle(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test complete lifecycle of a webhook trigger from creation to HTTP request handling."""
        # Step 1: Create webhook trigger
        trigger_data = TriggerCreate(
            name="GitHub Push Webhook",
            description="Handle GitHub push events",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GITHUB,
            allowed_methods=["POST"],
            task_parameters={"action": "deploy", "environment": "staging"},
            conditions={"branch": "main"},
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created
        assert created_trigger.id is not None
        assert created_trigger.webhook_id is not None
        assert created_trigger.webhook_type == WebhookType.GITHUB

        # Step 2: Simulate webhook request. Header keys are lowercase here to
        # match what Starlette/FastAPI hands the app for real HTTP requests
        # (dict(request.headers) is already lowercased) -- webhook_manager's
        # GitHub parser reads request_data.headers.get("x-github-event").
        webhook_request_data = {
            "webhook_id": created_trigger.webhook_id,
            "method": "POST",
            "headers": {"x-github-event": "push", "content-type": "application/json"},
            "body": {
                "ref": "refs/heads/main",
                "repository": {"name": "test-repo"},
                "commits": [{"message": "Fix bug"}],
            },
            "query_params": {},
            "received_at": datetime.utcnow(),
        }

        # Process webhook request
        response = await webhook_manager.handle_webhook_request(
            webhook_request_data["webhook_id"],
            webhook_request_data["method"],
            webhook_request_data["headers"],
            webhook_request_data["body"],
            webhook_request_data["query_params"],
        )

        # Verify webhook was processed successfully
        assert response["status_code"] == 200
        assert response["body"]["status"] == "success"

        # Verify task was created with webhook data
        mock_task_service.route_or_submit_task.assert_called_once()
        call_args = mock_task_service.route_or_submit_task.call_args

        task_params = call_args.args[0].task_parameters
        assert task_params["trigger_id"] == str(created_trigger.id)
        assert task_params["trigger_type"] == "webhook"
        assert task_params["action"] == "deploy"
        assert task_params["environment"] == "staging"

        # Verify webhook request data is included
        trigger_data = task_params["trigger_data"]
        assert trigger_data["ref"] == "refs/heads/main"
        assert trigger_data["headers"]["x-github-event"] == "push"

    # NOTE: test_multiple_triggers_same_event was removed -- it exercised
    # multiple triggers sharing one webhook_id with the webhook manager
    # fanning out to all matching triggers and returning a `body.executions`
    # list. That fan-out no longer exists: TriggerRepository.get_by_webhook_id
    # uses scalar_one_or_none() (raises on duplicate webhook_id -- routing is
    # strictly 1:1), and DefaultWebhookManager.get_webhook_response only
    # returns a single {"status", "message"} body, not a per-trigger
    # executions array. This was aspirational coverage for a feature that
    # isn't in the current codebase, not a renamed API.

    # API Integration Tests

    async def test_trigger_api_crud_operations(self, test_client, sample_agent_id):
        """Test trigger CRUD operations through API endpoints.

        Auth is handled by the get_user_context dependency (overridden on
        test_app), not a per-route require_a2a_execute_auth callable -- that
        name doesn't exist in the current triggers router.
        """
        auth_headers = {"Authorization": "Bearer test-token"}

        # Step 1: Create trigger via API
        create_data = {
            "name": "API Test Trigger",
            "description": "Test trigger created via API",
            "agent_id": str(sample_agent_id),
            "trigger_type": "cron",
            "cron_expression": "0 10 * * *",
            "timezone": "UTC",
            "task_parameters": {"api_test": True},
            "conditions": {"test_mode": True},
        }

        create_response = test_client.post("/v1/triggers/", json=create_data, headers=auth_headers)

        assert create_response.status_code == 201
        created_trigger = create_response.json()
        trigger_id = created_trigger["id"]

        # Step 2: Get trigger via API
        get_response = test_client.get(f"/v1/triggers/{trigger_id}", headers=auth_headers)

        assert get_response.status_code == 200
        retrieved_trigger = get_response.json()
        assert retrieved_trigger["name"] == "API Test Trigger"
        assert retrieved_trigger["cron_expression"] == "0 10 * * *"

        # Step 3: Update trigger via API
        update_data = {
            "name": "Updated API Test Trigger",
            "description": "Updated description",
            "cron_expression": "0 11 * * *",
        }

        update_response = test_client.put(
            f"/v1/triggers/{trigger_id}", json=update_data, headers=auth_headers
        )

        assert update_response.status_code == 200
        updated_trigger = update_response.json()
        assert updated_trigger["name"] == "Updated API Test Trigger"
        assert updated_trigger["cron_expression"] == "0 11 * * *"

        # Step 4: List triggers via API
        list_response = test_client.get("/v1/triggers/", headers=auth_headers)

        assert list_response.status_code == 200
        triggers_list = list_response.json()
        assert len(triggers_list) >= 1
        assert any(t["id"] == trigger_id for t in triggers_list)

        # Step 5: Disable trigger via API
        disable_response = test_client.post(
            f"/v1/triggers/{trigger_id}/disable", headers=auth_headers
        )

        assert disable_response.status_code == 200
        disable_result = disable_response.json()
        assert disable_result["is_active"] is False

        # Step 6: Enable trigger via API
        enable_response = test_client.post(
            f"/v1/triggers/{trigger_id}/enable", headers=auth_headers
        )

        assert enable_response.status_code == 200
        enable_result = enable_response.json()
        assert enable_result["is_active"] is True

        # Step 7: Delete trigger via API
        delete_response = test_client.delete(f"/v1/triggers/{trigger_id}", headers=auth_headers)

        assert delete_response.status_code == 204

        # Verify trigger is deleted
        get_deleted_response = test_client.get(f"/v1/triggers/{trigger_id}", headers=auth_headers)
        assert get_deleted_response.status_code == 404

    async def test_webhook_http_request_processing(
        self, test_client, trigger_service, sample_agent_id
    ):
        """Test processing real HTTP requests to webhook endpoints."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="HTTP Test Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST", "PUT"],
            task_parameters={"http_test": True},
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = created_trigger.webhook_id

        # Test POST request
        post_data = {"message": "Hello webhook", "timestamp": datetime.utcnow().isoformat()}
        post_response = test_client.post(
            f"/webhooks/{webhook_id}",
            json=post_data,
            headers={"Content-Type": "application/json", "X-Test-Header": "test-value"},
        )

        assert post_response.status_code == 200
        post_result = post_response.json()
        assert post_result["status"] == "success"

        # Test PUT request
        put_data = {"action": "update", "data": {"key": "value"}}
        put_response = test_client.put(
            f"/webhooks/{webhook_id}",
            json=put_data,
            headers={"Content-Type": "application/json"},
        )

        assert put_response.status_code == 200
        put_result = put_response.json()
        assert put_result["status"] == "success"

        # Test unsupported method (GET). All webhook failures currently
        # collapse to a generic 400 (no distinct 405), so check the message.
        get_response = test_client.get(f"/webhooks/{webhook_id}")
        assert get_response.status_code == 400
        assert "not allowed" in get_response.json()["message"].lower()

        # Test non-existent webhook. All webhook failures currently collapse
        # to a generic 400 (no distinct 404), so check the message.
        fake_webhook_id = f"fake_{uuid4().hex[:8]}"
        fake_response = test_client.post(f"/webhooks/{fake_webhook_id}", json={"test": "data"})
        assert fake_response.status_code == 400
        assert "not found" in fake_response.json()["message"].lower()

    # Error Handling and Edge Cases

    async def test_trigger_execution_with_task_service_failure(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger execution when task service fails."""
        # Make task service fail
        mock_task_service.route_or_submit_task.side_effect = Exception(
            "Task service unavailable"
        )

        # Create trigger
        trigger_data = TriggerCreate(
            name="Failing Task Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Execute trigger
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        execution_result = await trigger_service.execute_trigger(created_trigger.id, execution_data)

        # Verify execution failed gracefully
        assert execution_result.status == ExecutionStatus.FAILED
        assert "Task service unavailable" in execution_result.error_message
        assert execution_result.task_id is None

        # Verify failure was recorded and consecutive failures incremented
        updated_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert updated_trigger.consecutive_failures == 1

    async def test_concurrent_trigger_executions(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test concurrent execution of multiple triggers."""
        # Create multiple triggers
        triggers = []
        for i in range(5):
            trigger_data = TriggerCreate(
                name=f"Concurrent Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                task_parameters={"trigger_index": i},
                created_by="test_user",
                workspace_id="e2e-test-workspace",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Execute all triggers concurrently. The test db_session fixture is a
        # single shared AsyncSession (not safe for true concurrent use), so
        # serialize the actual DB access with a lock while still exercising
        # execute_trigger via overlapping asyncio tasks/scheduling.
        db_lock = asyncio.Lock()

        async def execute_locked(trigger_id, execution_data):
            async with db_lock:
                return await trigger_service.execute_trigger(trigger_id, execution_data)

        execution_tasks = []
        for trigger in triggers:
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "trigger_index": trigger.task_parameters["trigger_index"],
            }
            task = execute_locked(trigger.id, execution_data)
            execution_tasks.append(task)

        # Wait for all executions to complete
        execution_results = await asyncio.gather(*execution_tasks, return_exceptions=True)

        # Verify all executions succeeded
        for i, result in enumerate(execution_results):
            assert not isinstance(result, Exception), f"Trigger {i} failed: {result}"
            assert result.status == ExecutionStatus.SUCCESS
            assert result.task_id is not None

        # Verify all tasks were created
        assert mock_task_service.route_or_submit_task.call_count == 5

    async def test_trigger_condition_evaluation_edge_cases(self, trigger_service, sample_agent_id):
        """Test trigger condition evaluation with various edge cases.

        Note: without an llm_condition_evaluator configured, condition
        evaluation falls back to `_evaluate_simple_conditions`, which only
        understands a flat `field_matches` mapping of dot-path -> expected
        value (no `and`/`or`/`operator` boolean-tree support). Event data is
        also flat (no top-level "request" wrapper) -- see
        WebhookManager._parse_webhook_data.
        """
        conditions = {
            "field_matches": {
                "body.type": "deployment",
                "body.branch": "main",
                "headers.X-GitHub-Event": "push",
            }
        }

        trigger_data = TriggerCreate(
            name="Complex Conditions Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            conditions=conditions,
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)

        # Test matching conditions
        matching_data = {
            "body": {"type": "deployment", "branch": "main"},
            "headers": {"X-GitHub-Event": "push"},
        }

        conditions_met = await trigger_service.evaluate_trigger_conditions(trigger, matching_data)
        assert conditions_met is True

        # Test non-matching conditions
        non_matching_data = {
            "body": {"type": "deployment", "branch": "develop"},  # Wrong branch
            "headers": {"X-GitHub-Event": "push"},
        }

        conditions_not_met = await trigger_service.evaluate_trigger_conditions(
            trigger, non_matching_data
        )
        assert conditions_not_met is False

        # Test with missing data
        incomplete_data = {
            "body": {"type": "deployment"},
            # Missing headers
        }

        conditions_incomplete = await trigger_service.evaluate_trigger_conditions(
            trigger, incomplete_data
        )
        assert conditions_incomplete is False

    async def test_execution_history_and_metrics(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test execution history tracking and metrics calculation."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="History Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)

        # Execute trigger multiple times with different outcomes
        execution_results = []

        # 3 successful executions
        for i in range(3):
            execution_data = {"execution_time": datetime.utcnow().isoformat(), "attempt": i}
            result = await trigger_service.execute_trigger(trigger.id, execution_data)
            execution_results.append(result)
            assert result.status == ExecutionStatus.SUCCESS

        # 2 failed executions
        mock_task_service.route_or_submit_task.side_effect = Exception("Temporary failure")

        for i in range(2):
            execution_data = {"execution_time": datetime.utcnow().isoformat(), "attempt": i + 3}
            result = await trigger_service.execute_trigger(trigger.id, execution_data)
            execution_results.append(result)
            assert result.status == ExecutionStatus.FAILED

        # Reset task service
        mock_task_service.route_or_submit_task.side_effect = None
        mock_task_service.route_or_submit_task.return_value = MagicMock(id=uuid4())

        # Get execution history
        history = await trigger_service.get_execution_history(trigger.id)

        # Verify history
        assert len(history) == 5
        successful_executions = [e for e in history if e.status == ExecutionStatus.SUCCESS]
        failed_executions = [e for e in history if e.status == ExecutionStatus.FAILED]

        assert len(successful_executions) == 3
        assert len(failed_executions) == 2

        # Verify execution times are recorded
        for execution in history:
            assert execution.execution_time_ms >= 0
            assert execution.executed_at is not None

        # Verify trigger failure count
        updated_trigger = await trigger_service.get_trigger(trigger.id)
        assert updated_trigger.consecutive_failures == 2  # Last 2 were failures

    async def test_webhook_validation_and_parsing(
        self, webhook_manager, trigger_service, sample_agent_id
    ):
        """Test webhook request validation and parsing for different webhook types."""
        # Test GitHub webhook
        github_trigger_data = TriggerCreate(
            name="GitHub Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GITHUB,
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            created_by="test_user",
            workspace_id="e2e-test-workspace",
        )

        github_trigger = await trigger_service.create_trigger(github_trigger_data)

        # Valid GitHub request
        github_request = {
            "method": "POST",
            "headers": {
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "12345",
                "Content-Type": "application/json",
            },
            "body": {
                "ref": "refs/heads/main",
                "repository": {"name": "test-repo"},
                "pusher": {"name": "testuser"},
            },
            "query_params": {},
        }

        github_response = await webhook_manager.handle_webhook_request(
            github_trigger.webhook_id,
            github_request["method"],
            github_request["headers"],
            github_request["body"],
            github_request["query_params"],
        )

        assert github_response["status_code"] == 200
        assert github_response["body"]["status"] == "success"

        # Invalid GitHub request (missing required header)
        invalid_github_request = {
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": {"ref": "refs/heads/main"},
            "query_params": {},
        }

        invalid_response = await webhook_manager.handle_webhook_request(
            github_trigger.webhook_id,
            invalid_github_request["method"],
            invalid_github_request["headers"],
            invalid_github_request["body"],
            invalid_github_request["query_params"],
        )

        assert invalid_response["status_code"] == 400
        assert "validation failed" in invalid_response["body"]["message"].lower()

    # NOTE: test_trigger_system_health_monitoring was removed -- it exercised a
    # `check_health()` API on TriggerService/WebhookManager that doesn't exist
    # in the current codebase (WebhookManager only exposes `is_healthy() -> bool`,
    # and TriggerService has no health-check method at all). This was aspirational
    # test coverage for a feature that was never built, not a renamed API.
