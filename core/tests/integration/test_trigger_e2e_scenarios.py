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
        CronTrigger,
        TriggerCreate,
        TriggerExecution,
        WebhookTrigger,
    )
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import WebhookManager

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

# Import API components
from agentarea_api.api.deps.services import get_trigger_service, get_webhook_manager
from agentarea_api.api.v1.triggers import router as triggers_router
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
        task_service.create_task_from_params.return_value = mock_task

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
    async def trigger_repositories(self, db_session):
        """Create real trigger repositories for testing."""
        trigger_repo = TriggerRepository(db_session)
        execution_repo = TriggerExecutionRepository(db_session)
        return trigger_repo, execution_repo

    @pytest.fixture
    async def trigger_service(
        self,
        trigger_repositories,
        mock_event_broker,
        mock_agent_repository,
        mock_task_service,
        mock_temporal_schedule_manager,
    ):
        """Create trigger service with real repositories and mocked dependencies."""
        trigger_repo, execution_repo = trigger_repositories

        return TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=mock_temporal_schedule_manager,
        )

    @pytest.fixture
    async def webhook_manager(self, trigger_service, mock_event_broker):
        """Create webhook manager for testing."""
        return WebhookManager(trigger_service=trigger_service, event_broker=mock_event_broker)

    @pytest.fixture
    def test_app(self, trigger_service, webhook_manager):
        """Create test FastAPI app with trigger endpoints."""
        app = FastAPI()

        # Override dependencies
        app.dependency_overrides[get_trigger_service] = lambda: trigger_service
        app.dependency_overrides[get_webhook_manager] = lambda: webhook_manager

        # Include trigger router
        app.include_router(triggers_router, prefix="/v1")

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
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created
        assert created_trigger.id is not None
        assert created_trigger.name == "Daily Report Trigger"
        assert created_trigger.trigger_type == TriggerType.CRON
        assert created_trigger.is_active is True

        # Verify schedule was created
        mock_temporal_schedule_manager.create_schedule.assert_called_once()

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
        assert execution_result.execution_time_ms > 0

        # Verify task was created with correct parameters
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["trigger_id"] == str(created_trigger.id)
        assert task_params["trigger_type"] == "cron"
        assert task_params["report_type"] == "daily"
        assert task_params["format"] == "pdf"

        # Step 3: Test trigger lifecycle management
        # Disable trigger
        disable_result = await trigger_service.disable_trigger(created_trigger.id)
        assert disable_result is True

        # Verify schedule was paused
        mock_temporal_schedule_manager.pause_schedule.assert_called_once()

        # Re-enable trigger
        enable_result = await trigger_service.enable_trigger(created_trigger.id)
        assert enable_result is True

        # Verify schedule was resumed
        mock_temporal_schedule_manager.resume_schedule.assert_called_once()

        # Step 4: Delete trigger
        delete_result = await trigger_service.delete_trigger(created_trigger.id)
        assert delete_result is True

        # Verify schedule was deleted
        mock_temporal_schedule_manager.delete_schedule.assert_called_once()

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
            webhook_type=WebhookType.GITHUB,
            allowed_methods=["POST"],
            task_parameters={"action": "deploy", "environment": "staging"},
            conditions={"branch": "main"},
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            created_by="test_user",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created
        assert created_trigger.id is not None
        assert created_trigger.webhook_id is not None
        assert created_trigger.webhook_type == WebhookType.GITHUB

        # Step 2: Simulate webhook request
        webhook_request_data = {
            "webhook_id": created_trigger.webhook_id,
            "method": "POST",
            "headers": {"X-GitHub-Event": "push", "Content-Type": "application/json"},
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
        assert "executions" in response["body"]
        assert len(response["body"]["executions"]) == 1

        execution_info = response["body"]["executions"][0]
        assert execution_info["status"] == "success"
        assert execution_info["task_id"] is not None

        # Verify task was created with webhook data
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["trigger_id"] == str(created_trigger.id)
        assert task_params["trigger_type"] == "webhook"
        assert task_params["action"] == "deploy"
        assert task_params["environment"] == "staging"

        # Verify webhook request data is included
        trigger_data = task_params["trigger_data"]
        assert trigger_data["request"]["body"]["ref"] == "refs/heads/main"
        assert trigger_data["request"]["headers"]["X-GitHub-Event"] == "push"

    async def test_multiple_triggers_same_event(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test multiple triggers responding to the same webhook event."""
        # Create multiple webhook triggers with same webhook_id
        webhook_id = f"multi_trigger_{uuid4().hex[:8]}"

        # Trigger 1: Deploy to staging
        trigger1_data = TriggerCreate(
            name="Deploy to Staging",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=webhook_id,
            task_parameters={"action": "deploy", "environment": "staging"},
            conditions={"branch": "main"},
            created_by="test_user",
        )

        # Trigger 2: Run tests
        trigger2_data = TriggerCreate(
            name="Run Tests",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=webhook_id,
            task_parameters={"action": "test", "suite": "integration"},
            conditions={"branch": "main"},
            created_by="test_user",
        )

        # Trigger 3: Notify team (different branch condition)
        trigger3_data = TriggerCreate(
            name="Notify Team",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=webhook_id,
            task_parameters={"action": "notify", "channel": "dev-team"},
            conditions={"branch": "develop"},  # Different condition
            created_by="test_user",
        )

        trigger1 = await trigger_service.create_trigger(trigger1_data)
        trigger2 = await trigger_service.create_trigger(trigger2_data)
        trigger3 = await trigger_service.create_trigger(trigger3_data)

        # Send webhook request for main branch
        webhook_request_data = {
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": {"ref": "refs/heads/main", "action": "push"},
            "query_params": {},
        }

        response = await webhook_manager.handle_webhook_request(
            webhook_id,
            webhook_request_data["method"],
            webhook_request_data["headers"],
            webhook_request_data["body"],
            webhook_request_data["query_params"],
        )

        # Verify response
        assert response["status_code"] == 200
        executions = response["body"]["executions"]

        # Should have 2 executions (trigger1 and trigger2 match main branch)
        assert len(executions) == 2

        # Verify both tasks were created
        assert mock_task_service.create_task_from_params.call_count == 2

        # Verify correct triggers were executed
        executed_actions = []
        for call in mock_task_service.create_task_from_params.call_args_list:
            task_params = call.kwargs["task_parameters"]
            executed_actions.append(task_params["action"])

        assert "deploy" in executed_actions
        assert "test" in executed_actions
        assert "notify" not in executed_actions  # Different branch condition

    # API Integration Tests

    async def test_trigger_api_crud_operations(self, test_client, sample_agent_id):
        """Test trigger CRUD operations through API endpoints."""
        # Mock authentication
        auth_headers = {"Authorization": "Bearer test-token"}

        with patch("agentarea_api.api.v1.triggers.require_a2a_execute_auth") as mock_auth:
            mock_auth.return_value = MagicMock(user_id="test_user")

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

            create_response = test_client.post(
                "/v1/triggers/", json=create_data, headers=auth_headers
            )

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
            get_deleted_response = test_client.get(
                f"/v1/triggers/{trigger_id}", headers=auth_headers
            )
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
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST", "PUT"],
            task_parameters={"http_test": True},
            created_by="test_user",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = created_trigger.webhook_id

        # Test POST request
        post_data = {"message": "Hello webhook", "timestamp": datetime.utcnow().isoformat()}
        post_response = test_client.post(
            f"/v1/webhooks/{webhook_id}",
            json=post_data,
            headers={"Content-Type": "application/json", "X-Test-Header": "test-value"},
        )

        assert post_response.status_code == 200
        post_result = post_response.json()
        assert post_result["status"] == "success"
        assert len(post_result["executions"]) == 1

        # Test PUT request
        put_data = {"action": "update", "data": {"key": "value"}}
        put_response = test_client.put(
            f"/v1/webhooks/{webhook_id}",
            json=put_data,
            headers={"Content-Type": "application/json"},
        )

        assert put_response.status_code == 200
        put_result = put_response.json()
        assert put_result["status"] == "success"

        # Test unsupported method (GET)
        get_response = test_client.get(f"/v1/webhooks/{webhook_id}")
        assert get_response.status_code == 405  # Method not allowed

        # Test non-existent webhook
        fake_webhook_id = f"fake_{uuid4().hex[:8]}"
        fake_response = test_client.post(f"/v1/webhooks/{fake_webhook_id}", json={"test": "data"})
        assert fake_response.status_code == 404

    # Error Handling and Edge Cases

    async def test_trigger_execution_with_task_service_failure(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger execution when task service fails."""
        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception(
            "Task service unavailable"
        )

        # Create trigger
        trigger_data = TriggerCreate(
            name="Failing Task Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="test_user",
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
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Execute all triggers concurrently
        execution_tasks = []
        for trigger in triggers:
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "trigger_index": trigger.task_parameters["trigger_index"],
            }
            task = trigger_service.execute_trigger(trigger.id, execution_data)
            execution_tasks.append(task)

        # Wait for all executions to complete
        execution_results = await asyncio.gather(*execution_tasks, return_exceptions=True)

        # Verify all executions succeeded
        for i, result in enumerate(execution_results):
            assert not isinstance(result, Exception), f"Trigger {i} failed: {result}"
            assert result.status == ExecutionStatus.SUCCESS
            assert result.task_id is not None

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == 5

    async def test_trigger_condition_evaluation_edge_cases(self, trigger_service, sample_agent_id):
        """Test trigger condition evaluation with various edge cases."""
        # Test with complex nested conditions
        complex_conditions = {
            "and": [
                {"field": "request.body.type", "operator": "eq", "value": "deployment"},
                {
                    "or": [
                        {"field": "request.body.branch", "operator": "eq", "value": "main"},
                        {"field": "request.body.branch", "operator": "eq", "value": "master"},
                    ]
                },
                {"field": "request.headers.X-GitHub-Event", "operator": "eq", "value": "push"},
            ]
        }

        trigger_data = TriggerCreate(
            name="Complex Conditions Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            conditions=complex_conditions,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)

        # Test matching conditions
        matching_data = {
            "request": {
                "body": {"type": "deployment", "branch": "main"},
                "headers": {"X-GitHub-Event": "push"},
            }
        }

        conditions_met = await trigger_service.evaluate_trigger_conditions(trigger, matching_data)
        assert conditions_met is True

        # Test non-matching conditions
        non_matching_data = {
            "request": {
                "body": {"type": "deployment", "branch": "develop"},  # Wrong branch
                "headers": {"X-GitHub-Event": "push"},
            }
        }

        conditions_not_met = await trigger_service.evaluate_trigger_conditions(
            trigger, non_matching_data
        )
        assert conditions_not_met is False

        # Test with missing data
        incomplete_data = {
            "request": {
                "body": {"type": "deployment"},
                # Missing headers
            }
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
        mock_task_service.create_task_from_params.side_effect = Exception("Temporary failure")

        for i in range(2):
            execution_data = {"execution_time": datetime.utcnow().isoformat(), "attempt": i + 3}
            result = await trigger_service.execute_trigger(trigger.id, execution_data)
            execution_results.append(result)
            assert result.status == ExecutionStatus.FAILED

        # Reset task service
        mock_task_service.create_task_from_params.side_effect = None
        mock_task_service.create_task_from_params.return_value = MagicMock(id=uuid4())

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
            assert execution.execution_time_ms > 0
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
            webhook_type=WebhookType.GITHUB,
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            created_by="test_user",
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
        assert len(github_response["body"]["executions"]) == 1

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

    async def test_trigger_system_health_monitoring(
        self, trigger_service, webhook_manager, mock_temporal_schedule_manager
    ):
        """Test trigger system health monitoring and status checks."""
        # Test trigger service health
        service_health = await trigger_service.check_health()
        assert service_health["status"] == "healthy"
        assert "database" in service_health["components"]
        assert "task_service" in service_health["components"]

        # Test webhook manager health
        webhook_health = await webhook_manager.check_health()
        assert webhook_health["status"] == "healthy"
        assert "trigger_service" in webhook_health["components"]

        # Test temporal schedule manager health
        mock_temporal_schedule_manager.check_health.return_value = {
            "status": "healthy",
            "active_schedules": 5,
            "connection": "ok",
        }

        temporal_health = await mock_temporal_schedule_manager.check_health()
        assert temporal_health["status"] == "healthy"
        assert temporal_health["active_schedules"] == 5
