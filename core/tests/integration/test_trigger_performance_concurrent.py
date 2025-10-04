"""Performance and concurrency tests for trigger execution.

This module tests trigger system performance under load, concurrent execution
scenarios, and stress testing to ensure the system can handle high-throughput
webhook processing and multiple simultaneous trigger executions.
"""

import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

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
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import WebhookManager

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestTriggerPerformanceConcurrent:
    """Performance and concurrency tests for trigger system."""

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker for testing."""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service with realistic delays."""
        task_service = AsyncMock(spec=TaskService)

        async def create_task_with_delay(*args, **kwargs):
            # Simulate realistic task creation time
            await asyncio.sleep(0.01)  # 10ms delay
            mock_task = MagicMock()
            mock_task.id = uuid4()
            mock_task.title = "Performance Test Task"
            mock_task.status = "pending"
            return mock_task

        task_service.create_task_from_params.side_effect = create_task_with_delay
        return task_service

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository for testing."""
        agent_repo = AsyncMock()

        # Mock agent existence check
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Performance Test Agent"
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
            temporal_schedule_manager=None,
        )

    @pytest.fixture
    async def webhook_manager(self, trigger_service, mock_event_broker):
        """Create webhook manager for testing."""
        return WebhookManager(trigger_service=trigger_service, event_broker=mock_event_broker)

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # Concurrent Execution Tests

    async def test_concurrent_trigger_executions_same_trigger(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test concurrent executions of the same trigger."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Concurrent Same Trigger Test",
            description="Test concurrent executions of same trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            task_parameters={"concurrent_test": True},
            created_by="concurrent_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Define concurrent execution function
        async def execute_trigger(execution_id: int):
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "execution_id": execution_id,
                "source": "concurrent_test",
            }
            start_time = time.time()
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            end_time = time.time()

            return {
                "execution_id": execution_id,
                "result": result,
                "duration": end_time - start_time,
            }

        # Execute trigger concurrently
        concurrent_count = 10
        start_time = time.time()

        tasks = [execute_trigger(i) for i in range(concurrent_count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_duration = end_time - start_time

        # Verify all executions completed successfully
        successful_results = []
        for result in results:
            assert not isinstance(result, Exception), f"Execution failed: {result}"
            assert result["result"].status == ExecutionStatus.SUCCESS
            successful_results.append(result)

        # Verify performance metrics
        assert len(successful_results) == concurrent_count
        assert total_duration < 5.0  # Should complete within 5 seconds

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == concurrent_count

        # Verify execution history
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) == concurrent_count

        # Check average execution time
        avg_duration = sum(r["duration"] for r in successful_results) / len(successful_results)
        assert avg_duration < 1.0  # Each execution should be under 1 second

    async def test_concurrent_different_triggers_execution(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test concurrent execution of different triggers."""
        # Create multiple triggers
        trigger_count = 5
        triggers = []

        for i in range(trigger_count):
            trigger_data = TriggerCreate(
                name=f"Concurrent Different Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                task_parameters={"trigger_index": i},
                created_by="different_concurrent_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Execute all triggers concurrently
        async def execute_specific_trigger(trigger, execution_id):
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "execution_id": execution_id,
                "trigger_index": trigger.task_parameters["trigger_index"],
            }
            start_time = time.time()
            result = await trigger_service.execute_trigger(trigger.id, execution_data)
            end_time = time.time()

            return {
                "trigger_id": trigger.id,
                "trigger_index": trigger.task_parameters["trigger_index"],
                "result": result,
                "duration": end_time - start_time,
            }

        start_time = time.time()

        # Execute each trigger multiple times concurrently
        tasks = []
        for i, trigger in enumerate(triggers):
            for j in range(3):  # 3 executions per trigger
                tasks.append(execute_specific_trigger(trigger, j))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_duration = end_time - start_time

        # Verify all executions completed successfully
        successful_results = []
        for result in results:
            assert not isinstance(result, Exception), f"Execution failed: {result}"
            assert result["result"].status == ExecutionStatus.SUCCESS
            successful_results.append(result)

        # Verify performance
        expected_executions = trigger_count * 3
        assert len(successful_results) == expected_executions
        assert total_duration < 10.0  # Should complete within 10 seconds

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == expected_executions

        # Verify each trigger has correct execution history
        for trigger in triggers:
            history = await trigger_service.get_execution_history(trigger.id)
            assert len(history) == 3  # 3 executions per trigger

    async def test_webhook_concurrent_request_processing(
        self, webhook_manager, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test concurrent webhook request processing."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Concurrent Webhook Test",
            description="Test concurrent webhook processing",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST"],
            task_parameters={"webhook_concurrent_test": True},
            created_by="webhook_concurrent_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Define concurrent webhook request function
        async def send_webhook_request(request_id: int):
            request_data = {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "X-Request-ID": f"req-{request_id}",
                },
                "body": {
                    "request_id": request_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": f"concurrent_request_{request_id}",
                },
                "query_params": {"source": "concurrent_test"},
            }

            start_time = time.time()
            response = await webhook_manager.handle_webhook_request(
                webhook_id,
                request_data["method"],
                request_data["headers"],
                request_data["body"],
                request_data["query_params"],
            )
            end_time = time.time()

            return {
                "request_id": request_id,
                "response": response,
                "duration": end_time - start_time,
            }

        # Send concurrent webhook requests
        concurrent_requests = 20
        start_time = time.time()

        tasks = [send_webhook_request(i) for i in range(concurrent_requests)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_duration = end_time - start_time

        # Verify all requests were processed successfully
        successful_results = []
        for result in results:
            assert not isinstance(result, Exception), f"Request failed: {result}"
            assert result["response"]["status_code"] == 200
            assert result["response"]["body"]["status"] == "success"
            successful_results.append(result)

        # Verify performance metrics
        assert len(successful_results) == concurrent_requests
        assert total_duration < 15.0  # Should complete within 15 seconds

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == concurrent_requests

        # Check average response time
        avg_duration = sum(r["duration"] for r in successful_results) / len(successful_results)
        assert avg_duration < 2.0  # Each request should be under 2 seconds

    # High-Throughput Tests

    async def test_high_throughput_webhook_processing(
        self, webhook_manager, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test high-throughput webhook processing."""
        # Create multiple webhook triggers
        webhook_count = 5
        triggers = []

        for i in range(webhook_count):
            trigger_data = TriggerCreate(
                name=f"High Throughput Webhook {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.WEBHOOK,
                webhook_type=WebhookType.GENERIC,
                task_parameters={"webhook_index": i},
                created_by="throughput_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Generate high volume of requests
        requests_per_webhook = 10
        total_requests = webhook_count * requests_per_webhook

        async def process_batch_requests():
            tasks = []

            for trigger in triggers:
                webhook_id = trigger.webhook_id
                for j in range(requests_per_webhook):
                    request_data = {
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                        "body": {
                            "webhook_index": trigger.task_parameters["webhook_index"],
                            "request_index": j,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        "query_params": {},
                    }

                    task = webhook_manager.handle_webhook_request(
                        webhook_id,
                        request_data["method"],
                        request_data["headers"],
                        request_data["body"],
                        request_data["query_params"],
                    )
                    tasks.append(task)

            return await asyncio.gather(*tasks, return_exceptions=True)

        # Process requests and measure performance
        start_time = time.time()
        results = await process_batch_requests()
        end_time = time.time()

        total_duration = end_time - start_time
        throughput = total_requests / total_duration

        # Verify all requests were processed
        successful_count = 0
        for result in results:
            if not isinstance(result, Exception) and result["status_code"] == 200:
                successful_count += 1

        # Performance assertions
        assert successful_count == total_requests
        assert throughput > 5.0  # At least 5 requests per second
        assert total_duration < 30.0  # Complete within 30 seconds

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == total_requests

    async def test_mixed_trigger_types_concurrent_execution(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test concurrent execution of mixed trigger types (cron and webhook)."""
        # Create cron triggers
        cron_triggers = []
        for i in range(3):
            trigger_data = TriggerCreate(
                name=f"Mixed Cron Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                task_parameters={"type": "cron", "index": i},
                created_by="mixed_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            cron_triggers.append(trigger)

        # Create webhook triggers
        webhook_triggers = []
        for i in range(3):
            trigger_data = TriggerCreate(
                name=f"Mixed Webhook Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.WEBHOOK,
                webhook_type=WebhookType.GENERIC,
                task_parameters={"type": "webhook", "index": i},
                created_by="mixed_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            webhook_triggers.append(trigger)

        # Execute cron triggers and process webhook requests concurrently
        async def execute_cron_trigger(trigger):
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "source": "cron",
                "trigger_index": trigger.task_parameters["index"],
            }
            return await trigger_service.execute_trigger(trigger.id, execution_data)

        async def process_webhook_request(trigger):
            webhook_id = trigger.webhook_id
            request_data = {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {"source": "webhook", "trigger_index": trigger.task_parameters["index"]},
                "query_params": {},
            }
            return await webhook_manager.handle_webhook_request(
                webhook_id,
                request_data["method"],
                request_data["headers"],
                request_data["body"],
                request_data["query_params"],
            )

        # Execute all triggers concurrently
        start_time = time.time()

        cron_tasks = [execute_cron_trigger(trigger) for trigger in cron_triggers]
        webhook_tasks = [process_webhook_request(trigger) for trigger in webhook_triggers]

        all_tasks = cron_tasks + webhook_tasks
        results = await asyncio.gather(*all_tasks, return_exceptions=True)

        end_time = time.time()
        total_duration = end_time - start_time

        # Verify all executions completed successfully
        cron_results = results[: len(cron_triggers)]
        webhook_results = results[len(cron_triggers) :]

        # Verify cron trigger results
        for result in cron_results:
            assert not isinstance(result, Exception)
            assert result.status == ExecutionStatus.SUCCESS

        # Verify webhook trigger results
        for result in webhook_results:
            assert not isinstance(result, Exception)
            assert result["status_code"] == 200

        # Performance verification
        total_executions = len(cron_triggers) + len(webhook_triggers)
        assert total_duration < 10.0  # Should complete within 10 seconds
        assert mock_task_service.create_task_from_params.call_count == total_executions

    # Stress Tests

    async def test_trigger_system_under_stress(
        self, trigger_service, webhook_manager, mock_task_service, sample_agent_id
    ):
        """Test trigger system under stress conditions."""
        # Create multiple triggers of different types
        triggers = []

        # Create 10 cron triggers
        for i in range(10):
            trigger_data = TriggerCreate(
                name=f"Stress Cron Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {i % 24} * * *",
                task_parameters={"stress_test": True, "index": i},
                created_by="stress_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(("cron", trigger))

        # Create 10 webhook triggers
        for i in range(10):
            trigger_data = TriggerCreate(
                name=f"Stress Webhook Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.WEBHOOK,
                webhook_type=WebhookType.GENERIC,
                task_parameters={"stress_test": True, "index": i + 10},
                created_by="stress_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(("webhook", trigger))

        # Generate stress load
        async def stress_execution_batch():
            tasks = []

            for trigger_type, trigger in triggers:
                if trigger_type == "cron":
                    # Execute cron trigger multiple times
                    for j in range(5):
                        execution_data = {
                            "execution_time": datetime.utcnow().isoformat(),
                            "batch_index": j,
                            "stress_test": True,
                        }
                        task = trigger_service.execute_trigger(trigger.id, execution_data)
                        tasks.append(task)

                elif trigger_type == "webhook":
                    # Process webhook requests multiple times
                    for j in range(5):
                        request_data = {
                            "method": "POST",
                            "headers": {"Content-Type": "application/json"},
                            "body": {
                                "batch_index": j,
                                "stress_test": True,
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                            "query_params": {},
                        }
                        task = webhook_manager.handle_webhook_request(
                            trigger.webhook_id,
                            request_data["method"],
                            request_data["headers"],
                            request_data["body"],
                            request_data["query_params"],
                        )
                        tasks.append(task)

            return await asyncio.gather(*tasks, return_exceptions=True)

        # Execute stress test
        start_time = time.time()
        results = await stress_execution_batch()
        end_time = time.time()

        total_duration = end_time - start_time
        total_operations = len(triggers) * 5  # 5 operations per trigger

        # Verify system handled stress load
        successful_operations = 0
        for result in results:
            if not isinstance(result, Exception):
                if hasattr(result, "status") and result.status == ExecutionStatus.SUCCESS:
                    successful_operations += 1
                elif isinstance(result, dict) and result.get("status_code") == 200:
                    successful_operations += 1

        # Performance and reliability assertions
        success_rate = successful_operations / total_operations
        assert success_rate > 0.95  # At least 95% success rate
        assert total_duration < 60.0  # Complete within 60 seconds

        # Verify system remained responsive
        throughput = total_operations / total_duration
        assert throughput > 2.0  # At least 2 operations per second

    # Memory and Resource Tests

    async def test_memory_usage_under_load(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test memory usage under sustained load."""
        import gc

        # Create trigger
        trigger_data = TriggerCreate(
            name="Memory Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            task_parameters={"memory_test": True},
            created_by="memory_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Measure initial memory usage
        gc.collect()
        initial_objects = len(gc.get_objects())

        # Execute trigger many times
        execution_count = 100
        for i in range(execution_count):
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "iteration": i,
                "memory_test": True,
            }
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            assert result.status == ExecutionStatus.SUCCESS

            # Periodic garbage collection
            if i % 20 == 0:
                gc.collect()

        # Measure final memory usage
        gc.collect()
        final_objects = len(gc.get_objects())

        # Verify memory usage is reasonable
        object_growth = final_objects - initial_objects
        # Allow some growth but not excessive
        assert object_growth < execution_count * 10  # Less than 10 objects per execution

        # Verify execution history is properly managed
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) == execution_count

    async def test_database_connection_handling_under_load(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test database connection handling under concurrent load."""
        # Create multiple triggers
        trigger_count = 5
        triggers = []

        for i in range(trigger_count):
            trigger_data = TriggerCreate(
                name=f"DB Load Test Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                task_parameters={"db_test": True, "index": i},
                created_by="db_load_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Execute triggers concurrently to stress database connections
        async def concurrent_db_operations():
            tasks = []

            # Mix of read and write operations
            for trigger in triggers:
                # Execute trigger (write operation)
                execution_data = {
                    "execution_time": datetime.utcnow().isoformat(),
                    "db_stress_test": True,
                }
                tasks.append(trigger_service.execute_trigger(trigger.id, execution_data))

                # Get trigger (read operation)
                tasks.append(trigger_service.get_trigger(trigger.id))

                # Get execution history (read operation)
                tasks.append(trigger_service.get_execution_history(trigger.id))

            return await asyncio.gather(*tasks, return_exceptions=True)

        # Run multiple batches of concurrent operations
        batch_count = 3
        for batch in range(batch_count):
            start_time = time.time()
            results = await concurrent_db_operations()
            end_time = time.time()

            batch_duration = end_time - start_time

            # Verify all operations completed successfully
            for result in results:
                assert not isinstance(result, Exception), f"DB operation failed: {result}"

            # Verify reasonable performance
            assert batch_duration < 10.0  # Each batch should complete within 10 seconds

            # Small delay between batches
            await asyncio.sleep(0.1)

    # Error Handling Under Load

    async def test_error_handling_under_concurrent_load(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test error handling under concurrent load."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Error Handling Load Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=10,  # High threshold to avoid auto-disable
            created_by="error_load_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Make task service fail intermittently
        call_count = 0

        def intermittent_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:  # Fail every 3rd call
                raise Exception(f"Intermittent failure #{call_count}")
            else:
                mock_task = MagicMock()
                mock_task.id = uuid4()
                return mock_task

        mock_task_service.create_task_from_params.side_effect = intermittent_failure

        # Execute trigger concurrently with intermittent failures
        concurrent_executions = 30

        async def execute_with_potential_failure(execution_id):
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "execution_id": execution_id,
                "error_test": True,
            }
            return await trigger_service.execute_trigger(trigger_id, execution_data)

        start_time = time.time()
        tasks = [execute_with_potential_failure(i) for i in range(concurrent_executions)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()

        total_duration = end_time - start_time

        # Analyze results
        successful_executions = 0
        failed_executions = 0

        for result in results:
            assert not isinstance(result, Exception), f"Unexpected exception: {result}"
            if result.status == ExecutionStatus.SUCCESS:
                successful_executions += 1
            elif result.status == ExecutionStatus.FAILED:
                failed_executions += 1

        # Verify error handling worked correctly
        assert successful_executions + failed_executions == concurrent_executions
        assert successful_executions > 0  # Some should succeed
        assert failed_executions > 0  # Some should fail (due to intermittent failures)

        # Verify performance under error conditions
        assert total_duration < 20.0  # Should complete within 20 seconds

        # Verify trigger state is consistent
        final_trigger = await trigger_service.get_trigger(trigger_id)
        assert final_trigger is not None
        assert final_trigger.is_active is True  # Should not be auto-disabled
        assert final_trigger.consecutive_failures < 10  # Below threshold
