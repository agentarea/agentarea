"""Unit tests for trigger execution activities."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_execution.activities.trigger_execution_activities import make_trigger_activities
from agentarea_execution.interfaces import ActivityDependencies
from agentarea_execution.models import (
    CreateTaskFromTriggerRequest,
    EvaluateTriggerConditionsRequest,
    ExecuteTriggerRequest,
    RecordTriggerExecutionRequest,
)
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import CronTrigger, TriggerExecution

pytestmark = pytest.mark.asyncio


class TestTriggerExecutionActivities:
    """Test cases for trigger execution activities."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock activity dependencies."""
        return ActivityDependencies(event_broker=AsyncMock())

    @pytest.fixture
    def trigger_activities(self, mock_dependencies):
        """Create trigger activities with mocked dependencies."""
        return make_trigger_activities(mock_dependencies)

    @pytest.fixture
    def sample_trigger(self):
        """Create a sample trigger for testing."""
        return CronTrigger(
            id=uuid4(),
            name="Test Trigger",
            description="Test trigger for activities",
            agent_id=uuid4(),
            cron_expression="0 9 * * 1-5",
            timezone="UTC",
            task_parameters={"test_param": "test_value"},
            created_by="test_user",
            is_active=True,
        )

    @pytest.fixture
    def mock_database_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_execute_trigger_activity_success(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test successful trigger execution activity."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        # Mock repositories and services
        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TaskRepository"
            ) as mock_task_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TaskService"
            ) as mock_task_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_task_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo
            mock_task_repo_class.return_value = mock_task_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_task_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_task_service_class.return_value = mock_task_service

            # Setup trigger service methods
            mock_trigger_service.get_trigger.return_value = sample_trigger
            mock_trigger_service.evaluate_trigger_conditions.return_value = True
            mock_trigger_service._build_task_parameters.return_value = {
                "trigger_id": str(sample_trigger.id),
                "test_param": "test_value",
            }

            # Setup task service methods
            mock_task = MagicMock()
            mock_task.id = uuid4()
            mock_task_service.create_task_from_params.return_value = mock_task
            mock_task_service.submit_task.return_value = None

            # Setup execution recording
            mock_execution = TriggerExecution(
                trigger_id=sample_trigger.id,
                status=ExecutionStatus.SUCCESS,
                execution_time_ms=100,
                task_id=mock_task.id,
            )
            mock_trigger_service.record_execution.return_value = mock_execution

            # Get the activity function
            execute_trigger_activity = trigger_activities[0]  # First activity is execute_trigger

            # Execute the activity
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            request = ExecuteTriggerRequest(
                trigger_id=sample_trigger.id, execution_data=execution_data
            )
            result = await execute_trigger_activity(request)

            # Verify results
            assert result.status == "success"
            assert result.trigger_id == sample_trigger.id
            assert result.task_id == mock_task.id
            assert result.execution_time_ms > 0

            # Verify service calls
            mock_trigger_service.get_trigger.assert_called_once_with(sample_trigger.id)
            mock_trigger_service.evaluate_trigger_conditions.assert_called_once()
            mock_task_service.create_task_from_params.assert_called_once()
            mock_task_service.submit_task.assert_called_once()
            mock_trigger_service.record_execution.assert_called_once()

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_execute_trigger_activity_trigger_not_found(
        self, mock_get_database, trigger_activities, mock_database_session
    ):
        """Test trigger execution activity when trigger is not found."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_trigger_service.get_trigger.return_value = None

            # Get the activity function
            execute_trigger_activity = trigger_activities[0]

            # Execute the activity - should raise TriggerNotFoundError
            trigger_id = uuid4()
            execution_data = {"execution_time": datetime.utcnow().isoformat()}

            with pytest.raises(Exception):  # TriggerNotFoundError
                request = ExecuteTriggerRequest(
                    trigger_id=trigger_id, execution_data=execution_data
                )
                await execute_trigger_activity(request)

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_execute_trigger_activity_inactive_trigger(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test trigger execution activity with inactive trigger."""
        # Make trigger inactive
        sample_trigger.is_active = False

        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_trigger_service.get_trigger.return_value = sample_trigger

            # Get the activity function
            execute_trigger_activity = trigger_activities[0]

            # Execute the activity
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            request = ExecuteTriggerRequest(
                trigger_id=sample_trigger.id, execution_data=execution_data
            )
            result = await execute_trigger_activity(request)

            # Verify results
            assert result.status == "skipped"
            assert result.reason == "trigger_inactive"
            assert result.trigger_id == sample_trigger.id

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_execute_trigger_activity_conditions_not_met(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test trigger execution activity when conditions are not met."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_trigger_service.get_trigger.return_value = sample_trigger
            mock_trigger_service.evaluate_trigger_conditions.return_value = False

            # Get the activity function
            execute_trigger_activity = trigger_activities[0]

            # Execute the activity
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            request = ExecuteTriggerRequest(
                trigger_id=sample_trigger.id, execution_data=execution_data
            )
            result = await execute_trigger_activity(request)

            # Verify results
            assert result.status == "skipped"
            assert result.reason == "conditions_not_met"
            assert result.trigger_id == sample_trigger.id

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_record_trigger_execution_activity(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test record trigger execution activity."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service

            # Setup execution recording
            mock_execution = TriggerExecution(
                trigger_id=sample_trigger.id,
                status=ExecutionStatus.SUCCESS,
                execution_time_ms=150,
                task_id=uuid4(),
            )
            mock_trigger_service.record_execution.return_value = mock_execution

            # Get the activity function
            record_execution_activity = trigger_activities[1]  # Second activity is record_execution

            # Execute the activity
            execution_data = {
                "status": "success",
                "execution_time_ms": 150,
                "task_id": str(mock_execution.task_id),
                "trigger_data": {"test": "data"},
            }
            request = RecordTriggerExecutionRequest(
                trigger_id=sample_trigger.id, execution_data=execution_data
            )
            result = await record_execution_activity(request)

            # Verify results
            assert result.execution_id == mock_execution.id
            assert result.trigger_id == sample_trigger.id
            assert result.status == "success"

            # Verify service call
            mock_trigger_service.record_execution.assert_called_once()

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_evaluate_trigger_conditions_activity(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test evaluate trigger conditions activity."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_trigger_service.get_trigger.return_value = sample_trigger
            mock_trigger_service.evaluate_trigger_conditions.return_value = True

            # Get the activity function
            evaluate_conditions_activity = trigger_activities[
                2
            ]  # Third activity is evaluate_conditions

            # Execute the activity
            event_data = {"request": {"body": {"type": "test"}}}
            request = EvaluateTriggerConditionsRequest(
                trigger_id=sample_trigger.id, event_data=event_data
            )
            result = await evaluate_conditions_activity(request)

            # Verify results
            assert result.conditions_met is True

            # Verify service calls
            mock_trigger_service.get_trigger.assert_called_once_with(sample_trigger.id)
            mock_trigger_service.evaluate_trigger_conditions.assert_called_once_with(
                sample_trigger, event_data
            )

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_create_task_from_trigger_activity(
        self, mock_get_database, trigger_activities, sample_trigger, mock_database_session
    ):
        """Test create task from trigger activity."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TaskRepository"
            ) as mock_task_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TaskService"
            ) as mock_task_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_task_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo
            mock_task_repo_class.return_value = mock_task_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_task_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_task_service_class.return_value = mock_task_service

            # Setup trigger service methods
            mock_trigger_service.get_trigger.return_value = sample_trigger
            mock_trigger_service._build_task_parameters.return_value = {
                "trigger_id": str(sample_trigger.id),
                "test_param": "test_value",
            }

            # Setup task service methods
            mock_task = MagicMock()
            mock_task.id = uuid4()
            mock_task_service.create_task_from_params.return_value = mock_task

            # Get the activity function
            create_task_activity = trigger_activities[
                3
            ]  # Fourth activity is create_task_from_trigger

            # Execute the activity
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            request = CreateTaskFromTriggerRequest(
                trigger_id=sample_trigger.id, execution_data=execution_data
            )
            result = await create_task_activity(request)

            # Verify results
            assert result.status == "created"
            assert result.task_id == mock_task.id
            assert result.trigger_id == sample_trigger.id

            # Verify service calls
            mock_trigger_service.get_trigger.assert_called_once_with(sample_trigger.id)
            mock_trigger_service._build_task_parameters.assert_called_once()
            mock_task_service.create_task_from_params.assert_called_once()

    @patch("agentarea_execution.activities.trigger_execution_activities.get_database")
    async def test_create_task_from_trigger_activity_trigger_not_found(
        self, mock_get_database, trigger_activities, mock_database_session
    ):
        """Test create task from trigger activity when trigger is not found."""
        # Setup mocks
        mock_database = MagicMock()
        mock_database.async_session_factory.return_value = mock_database_session
        mock_get_database.return_value = mock_database

        with (
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerRepository"
            ) as mock_trigger_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerExecutionRepository"
            ) as mock_execution_repo_class,
            patch(
                "agentarea_execution.activities.trigger_execution_activities.TriggerService"
            ) as mock_trigger_service_class,
        ):
            # Setup repository mocks
            mock_trigger_repo = AsyncMock()
            mock_execution_repo = AsyncMock()
            mock_trigger_repo_class.return_value = mock_trigger_repo
            mock_execution_repo_class.return_value = mock_execution_repo

            # Setup service mocks
            mock_trigger_service = AsyncMock()
            mock_trigger_service_class.return_value = mock_trigger_service
            mock_trigger_service.get_trigger.return_value = None

            # Get the activity function
            create_task_activity = trigger_activities[3]

            # Execute the activity
            trigger_id = uuid4()
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            request = CreateTaskFromTriggerRequest(
                trigger_id=trigger_id, execution_data=execution_data
            )
            result = await create_task_activity(request)

            # Verify results
            assert result.status == "failed"
            assert result.task_id is None
            assert result.trigger_id == trigger_id
            assert result.error and "not found" in result.error
