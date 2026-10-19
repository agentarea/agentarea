"""Performance and concurrency tests for trigger execution.

This module tests trigger system performance under load, concurrent execution
scenarios, and stress testing to ensure the system can handle
multiple simultaneous trigger executions.
"""

import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType
    from agentarea_triggers.domain.models import (
        TriggerCreate,
    )
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.trigger_service import TriggerService

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

    async def test_trigger_system_under_stress(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger system under stress conditions."""
        # Create multiple triggers of different types
        triggers = []

        # Create 20 cron triggers
        for i in range(20):
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

        # Generate stress load
        async def stress_execution_batch():
            tasks = []

            for _trigger_type, trigger in triggers:
                for j in range(5):
                    execution_data = {
                        "execution_time": datetime.utcnow().isoformat(),
                        "batch_index": j,
                        "stress_test": True,
                    }
                    tasks.append(trigger_service.execute_trigger(trigger.id, execution_data))

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
