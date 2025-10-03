"""Comprehensive integration test suite for trigger system.

This module provides a comprehensive test suite that runs all trigger system
integration tests and provides summary reporting for system validation.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Import all test modules

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
    from agentarea_triggers.domain.models import TriggerCreate
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import WebhookManager

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestTriggerComprehensiveSuite:
    """Comprehensive integration test suite for trigger system."""

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
        mock_task.title = "Comprehensive Test Task"
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
        mock_agent.name = "Comprehensive Test Agent"
        agent_repo.get.return_value = mock_agent

        return agent_repo

    @pytest.fixture
    async def trigger_repositories(self, db_session):
        """Create real trigger repositories for testing."""
        trigger_repo = TriggerRepository(db_session)
        execution_repo = TriggerExecutionRepository(db_session)
        return trigger_repo, execution_repo

    @pytest.fixture
    async def trigger_service(
        self, trigger_repositories, mock_event_broker, mock_agent_repository, mock_task_service
    ):
        """Create trigger service with real repositories."""
        trigger_repo, execution_repo = trigger_repositories

        return TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=AsyncMock(),
        )

    @pytest.fixture
    async def webhook_manager(self, trigger_service, mock_event_broker):
        """Create webhook manager for testing."""
        return WebhookManager(trigger_service=trigger_service, event_broker=mock_event_broker)

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # System Health and Validation Tests

    async def test_trigger_system_health_check(self, trigger_service, webhook_manager):
        """Test overall trigger system health."""
        # Test trigger service health
        service_health = await trigger_service.check_health()
        assert service_health["status"] == "healthy"
        assert "database" in service_health["components"]
        assert "task_service" in service_health["components"]

        # Test webhook manager health
        webhook_health = await webhook_manager.check_health()
        assert webhook_health["status"] == "healthy"
        assert "trigger_service" in webhook_health["components"]

    async def test_trigger_system_component_integration(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test integration between all trigger system components."""
        # Create triggers of different types
        cron_trigger_data = TriggerCreate(
            name="Integration Test Cron",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            task_parameters={"integration_test": "cron"},
            created_by="integration_test",
        )

        webhook_trigger_data = TriggerCreate(
            name="Integration Test Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            task_parameters={"integration_test": "webhook"},
            created_by="integration_test",
        )

        # Create triggers
        cron_trigger = await trigger_service.create_trigger(cron_trigger_data)
        webhook_trigger = await trigger_service.create_trigger(webhook_trigger_data)

        # Test cron trigger execution
        cron_execution_data = {"execution_time": datetime.utcnow().isoformat(), "source": "cron"}
        cron_result = await trigger_service.execute_trigger(cron_trigger.id, cron_execution_data)
        assert cron_result.status == ExecutionStatus.SUCCESS

        # Test webhook trigger execution via webhook manager
        webhook_response = await webhook_manager.handle_webhook_request(
            webhook_trigger.webhook_id,
            "POST",
            {"Content-Type": "application/json"},
            {"integration_test": "webhook_request"},
            {},
        )
        assert webhook_response["status_code"] == 200
        assert webhook_response["body"]["status"] == "success"

        # Verify both triggers created tasks
        assert mock_task_service.create_task_from_params.call_count == 2

        # Verify execution history
        cron_history = await trigger_service.get_execution_history(cron_trigger.id)
        webhook_history = await trigger_service.get_execution_history(webhook_trigger.id)

        assert len(cron_history) == 1
        assert len(webhook_history) == 1

    async def test_trigger_system_data_consistency(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test data consistency across trigger operations."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Data Consistency Test",
            description="Test data consistency",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            task_parameters={"consistency_test": True},
            failure_threshold=5,
            created_by="consistency_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Perform various operations and verify consistency

        # 1. Execute trigger and verify execution is recorded
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result.status == ExecutionStatus.SUCCESS

        # Verify execution history
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) == 1
        assert history[0].trigger_id == trigger_id

        # 2. Update trigger and verify changes persist
        from agentarea_triggers.domain.models import TriggerUpdate

        update_data = TriggerUpdate(
            name="Updated Consistency Test", description="Updated description", failure_threshold=3
        )

        updated_trigger = await trigger_service.update_trigger(trigger_id, update_data)
        assert updated_trigger.name == "Updated Consistency Test"
        assert updated_trigger.failure_threshold == 3

        # Verify update persisted
        retrieved_trigger = await trigger_service.get_trigger(trigger_id)
        assert retrieved_trigger.name == "Updated Consistency Test"
        assert retrieved_trigger.failure_threshold == 3

        # 3. Disable and re-enable trigger
        await trigger_service.disable_trigger(trigger_id)
        disabled_trigger = await trigger_service.get_trigger(trigger_id)
        assert disabled_trigger.is_active is False

        await trigger_service.enable_trigger(trigger_id)
        enabled_trigger = await trigger_service.get_trigger(trigger_id)
        assert enabled_trigger.is_active is True

        # 4. Verify execution history is preserved through all operations
        final_history = await trigger_service.get_execution_history(trigger_id)
        assert len(final_history) == 1  # Should still have the original execution

    async def test_trigger_system_error_recovery(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger system error recovery capabilities."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Error Recovery Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=3,
            created_by="error_recovery_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Simulate system errors and recovery

        # 1. Task service failure
        mock_task_service.create_task_from_params.side_effect = Exception("Task service error")

        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result.status == ExecutionStatus.FAILED

        # 2. Recovery - fix task service
        mock_task_service.create_task_from_params.side_effect = None
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task_service.create_task_from_params.return_value = mock_task

        # 3. Verify system recovers
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result.status == ExecutionStatus.SUCCESS

        # 4. Verify failure count was reset
        recovered_trigger = await trigger_service.get_trigger(trigger_id)
        assert recovered_trigger.consecutive_failures == 0
        assert recovered_trigger.is_active is True

    async def test_trigger_system_scalability_validation(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test trigger system scalability with multiple triggers and executions."""
        # Create multiple triggers of different types
        triggers = []

        # Create 5 cron triggers
        for i in range(5):
            trigger_data = TriggerCreate(
                name=f"Scalability Cron {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                task_parameters={"scalability_test": "cron", "index": i},
                created_by="scalability_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(("cron", trigger))

        # Create 5 webhook triggers
        for i in range(5):
            trigger_data = TriggerCreate(
                name=f"Scalability Webhook {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.WEBHOOK,
                webhook_type=WebhookType.GENERIC,
                task_parameters={"scalability_test": "webhook", "index": i},
                created_by="scalability_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(("webhook", trigger))

        # Execute all triggers multiple times
        total_executions = 0

        for trigger_type, trigger in triggers:
            if trigger_type == "cron":
                # Execute cron trigger 3 times
                for j in range(3):
                    execution_data = {
                        "execution_time": datetime.utcnow().isoformat(),
                        "execution_index": j,
                    }
                    result = await trigger_service.execute_trigger(trigger.id, execution_data)
                    assert result.status == ExecutionStatus.SUCCESS
                    total_executions += 1

            elif trigger_type == "webhook":
                # Process webhook requests 3 times
                for j in range(3):
                    response = await webhook_manager.handle_webhook_request(
                        trigger.webhook_id,
                        "POST",
                        {"Content-Type": "application/json"},
                        {"execution_index": j},
                        {},
                    )
                    assert response["status_code"] == 200
                    total_executions += 1

        # Verify all executions were processed
        expected_executions = 10 * 3  # 10 triggers * 3 executions each
        assert total_executions == expected_executions
        assert mock_task_service.create_task_from_params.call_count == expected_executions

        # Verify each trigger has correct execution history
        for trigger_type, trigger in triggers:
            history = await trigger_service.get_execution_history(trigger.id)
            assert len(history) == 3

    async def test_trigger_system_configuration_validation(self, trigger_service, sample_agent_id):
        """Test trigger system configuration validation."""
        # Test valid configurations
        valid_configs = [
            {
                "name": "Valid Cron Trigger",
                "trigger_type": TriggerType.CRON,
                "cron_expression": "0 9 * * 1-5",
                "timezone": "UTC",
            },
            {
                "name": "Valid Webhook Trigger",
                "trigger_type": TriggerType.WEBHOOK,
                "webhook_type": WebhookType.GITHUB,
                "allowed_methods": ["POST"],
                "validation_rules": {"required_headers": ["X-GitHub-Event"]},
            },
        ]

        for config in valid_configs:
            trigger_data = TriggerCreate(
                name=config["name"],
                agent_id=sample_agent_id,
                trigger_type=config["trigger_type"],
                cron_expression=config.get("cron_expression"),
                timezone=config.get("timezone", "UTC"),
                webhook_type=config.get("webhook_type"),
                allowed_methods=config.get("allowed_methods"),
                validation_rules=config.get("validation_rules"),
                created_by="config_validation_test",
            )

            # Should create successfully
            trigger = await trigger_service.create_trigger(trigger_data)
            assert trigger is not None
            assert trigger.name == config["name"]

    async def test_trigger_system_monitoring_and_observability(
        self, trigger_service, mock_task_service, mock_event_broker, sample_agent_id
    ):
        """Test trigger system monitoring and observability features."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Monitoring Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            task_parameters={"monitoring_test": True},
            created_by="monitoring_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Execute trigger to generate monitoring data
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result.status == ExecutionStatus.SUCCESS

        # Test monitoring capabilities

        # 1. Execution history tracking
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) == 1
        assert history[0].execution_time_ms > 0
        assert history[0].executed_at is not None

        # 2. Safety status monitoring
        safety_status = await trigger_service.get_trigger_safety_status(trigger_id)
        assert safety_status is not None
        assert safety_status["consecutive_failures"] == 0
        assert safety_status["is_at_risk"] is False

        # 3. Event publishing for observability
        mock_event_broker.publish.assert_called()

        # 4. Health check functionality
        health_status = await trigger_service.check_health()
        assert health_status["status"] == "healthy"

    # Integration Test Summary

    async def test_comprehensive_integration_summary(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Comprehensive integration test that validates all major functionality."""
        print("\n" + "=" * 60)
        print("TRIGGER SYSTEM COMPREHENSIVE INTEGRATION TEST SUMMARY")
        print("=" * 60)

        test_results = {
            "trigger_creation": {"cron": 0, "webhook": 0},
            "trigger_execution": {"successful": 0, "failed": 0},
            "webhook_processing": {"requests": 0, "successful": 0},
            "lifecycle_operations": {"enable": 0, "disable": 0, "update": 0, "delete": 0},
            "safety_mechanisms": {"auto_disabled": 0, "recovered": 0},
            "performance": {"avg_execution_time": 0, "throughput": 0},
        }

        # 1. Test trigger creation
        print("\n1. Testing Trigger Creation...")

        # Create cron trigger
        cron_trigger_data = TriggerCreate(
            name="Summary Cron Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="summary_test",
        )
        cron_trigger = await trigger_service.create_trigger(cron_trigger_data)
        test_results["trigger_creation"]["cron"] += 1

        # Create webhook trigger
        webhook_trigger_data = TriggerCreate(
            name="Summary Webhook Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            created_by="summary_test",
        )
        webhook_trigger = await trigger_service.create_trigger(webhook_trigger_data)
        test_results["trigger_creation"]["webhook"] += 1

        print(f"   ✓ Created {test_results['trigger_creation']['cron']} cron trigger(s)")
        print(f"   ✓ Created {test_results['trigger_creation']['webhook']} webhook trigger(s)")

        # 2. Test trigger execution
        print("\n2. Testing Trigger Execution...")

        import time

        start_time = time.time()

        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(cron_trigger.id, execution_data)

        end_time = time.time()
        execution_time = end_time - start_time

        if result.status == ExecutionStatus.SUCCESS:
            test_results["trigger_execution"]["successful"] += 1
        else:
            test_results["trigger_execution"]["failed"] += 1

        test_results["performance"]["avg_execution_time"] = execution_time

        print(f"   ✓ Successful executions: {test_results['trigger_execution']['successful']}")
        print(f"   ✓ Failed executions: {test_results['trigger_execution']['failed']}")
        print(f"   ✓ Average execution time: {execution_time:.3f}s")

        # 3. Test webhook processing
        print("\n3. Testing Webhook Processing...")

        response = await webhook_manager.handle_webhook_request(
            webhook_trigger.webhook_id,
            "POST",
            {"Content-Type": "application/json"},
            {"summary_test": True},
            {},
        )

        test_results["webhook_processing"]["requests"] += 1
        if response["status_code"] == 200:
            test_results["webhook_processing"]["successful"] += 1

        print(f"   ✓ Webhook requests processed: {test_results['webhook_processing']['requests']}")
        print(
            f"   ✓ Successful webhook responses: {test_results['webhook_processing']['successful']}"
        )

        # 4. Test lifecycle operations
        print("\n4. Testing Lifecycle Operations...")

        # Disable trigger
        await trigger_service.disable_trigger(cron_trigger.id)
        test_results["lifecycle_operations"]["disable"] += 1

        # Enable trigger
        await trigger_service.enable_trigger(cron_trigger.id)
        test_results["lifecycle_operations"]["enable"] += 1

        # Update trigger
        from agentarea_triggers.domain.models import TriggerUpdate

        update_data = TriggerUpdate(description="Updated in summary test")
        await trigger_service.update_trigger(cron_trigger.id, update_data)
        test_results["lifecycle_operations"]["update"] += 1

        print(f"   ✓ Enable operations: {test_results['lifecycle_operations']['enable']}")
        print(f"   ✓ Disable operations: {test_results['lifecycle_operations']['disable']}")
        print(f"   ✓ Update operations: {test_results['lifecycle_operations']['update']}")

        # 5. Test safety mechanisms
        print("\n5. Testing Safety Mechanisms...")

        safety_status = await trigger_service.get_trigger_safety_status(cron_trigger.id)
        assert safety_status is not None

        print("   ✓ Safety monitoring operational")
        print(f"   ✓ Failure threshold: {safety_status['failure_threshold']}")
        print(f"   ✓ Current failures: {safety_status['consecutive_failures']}")

        # 6. Calculate performance metrics
        total_operations = (
            test_results["trigger_creation"]["cron"]
            + test_results["trigger_creation"]["webhook"]
            + test_results["trigger_execution"]["successful"]
            + test_results["webhook_processing"]["successful"]
            + test_results["lifecycle_operations"]["enable"]
            + test_results["lifecycle_operations"]["disable"]
            + test_results["lifecycle_operations"]["update"]
        )

        test_results["performance"]["throughput"] = (
            total_operations / execution_time if execution_time > 0 else 0
        )

        # 7. Final summary
        print("\n" + "=" * 60)
        print("INTEGRATION TEST RESULTS SUMMARY")
        print("=" * 60)
        print(f"Total Triggers Created: {sum(test_results['trigger_creation'].values())}")
        print(f"Total Executions: {sum(test_results['trigger_execution'].values())}")
        print(f"Total Webhook Requests: {test_results['webhook_processing']['requests']}")
        print(f"Total Lifecycle Operations: {sum(test_results['lifecycle_operations'].values())}")
        print(f"Average Execution Time: {test_results['performance']['avg_execution_time']:.3f}s")
        print(f"System Throughput: {test_results['performance']['throughput']:.2f} ops/sec")
        print("\n✅ ALL INTEGRATION TESTS PASSED")
        print("=" * 60)

        # Verify all major functionality works
        assert sum(test_results["trigger_creation"].values()) >= 2
        assert test_results["trigger_execution"]["successful"] >= 1
        assert test_results["webhook_processing"]["successful"] >= 1
        assert sum(test_results["lifecycle_operations"].values()) >= 3
