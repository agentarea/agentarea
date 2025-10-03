"""Unit tests for TriggerService."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
from agentarea_triggers.domain.models import (
    CronTrigger,
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


class TestTriggerService:
    """Test cases for TriggerService."""

    @pytest.fixture
    def mock_trigger_repository(self):
        """Mock trigger repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_trigger_execution_repository(self):
        """Mock trigger execution repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker."""
        return AsyncMock()

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service."""
        return AsyncMock()

    @pytest.fixture
    def mock_llm_service(self):
        """Mock LLM service."""
        return AsyncMock()

    @pytest.fixture
    def mock_temporal_client(self):
        """Mock Temporal client."""
        return AsyncMock()

    @pytest.fixture
    def trigger_service(
        self,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_event_broker,
        mock_agent_repository,
        mock_task_service,
        mock_llm_service,
        mock_temporal_client,
    ):
        """Create TriggerService instance with mocked dependencies."""
        # Create a mock temporal schedule manager
        mock_temporal_schedule_manager = AsyncMock()

        # Create service
        service = TriggerService(
            trigger_repository=mock_trigger_repository,
            trigger_execution_repository=mock_trigger_execution_repository,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=mock_llm_service,
            temporal_schedule_manager=mock_temporal_schedule_manager,
        )

        # Make schedule manager accessible for tests
        service._mock_temporal_schedule_manager = mock_temporal_schedule_manager

        return service

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID."""
        return uuid4()

    @pytest.fixture
    def sample_cron_trigger_data(self, sample_agent_id):
        """Sample cron trigger creation data."""
        return TriggerCreate(
            name="Daily Report",
            description="Generate daily report",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            task_parameters={"report_type": "daily"},
        )

    @pytest.fixture
    def sample_webhook_trigger_data(self, sample_agent_id):
        """Sample webhook trigger creation data."""
        return TriggerCreate(
            name="Webhook Handler",
            description="Handle incoming webhooks",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="webhook_123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.GENERIC,
            created_by="test_user",
            task_parameters={"handler": "generic"},
        )

    @pytest.fixture
    def sample_cron_trigger(self, sample_agent_id):
        """Sample cron trigger."""
        return CronTrigger(
            id=uuid4(),
            name="Daily Report",
            description="Generate daily report",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            task_parameters={"report_type": "daily"},
        )

    @pytest.fixture
    def sample_webhook_trigger(self, sample_agent_id):
        """Sample webhook trigger."""
        return WebhookTrigger(
            id=uuid4(),
            name="Webhook Handler",
            description="Handle incoming webhooks",
            agent_id=sample_agent_id,
            webhook_id="webhook_123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.GENERIC,
            created_by="test_user",
            task_parameters={"handler": "generic"},
        )

    # Test CRUD Operations

    @pytest.mark.asyncio
    async def test_create_trigger_success(
        self,
        trigger_service,
        mock_agent_repository,
        mock_trigger_repository,
        sample_cron_trigger_data,
        sample_cron_trigger,
    ):
        """Test successful trigger creation."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists
        mock_trigger_repository.create_from_data.return_value = sample_cron_trigger

        # Execute
        result = await trigger_service.create_trigger(sample_cron_trigger_data)

        # Verify
        assert result == sample_cron_trigger
        mock_agent_repository.get.assert_called_once_with(sample_cron_trigger_data.agent_id)
        mock_trigger_repository.create_from_data.assert_called_once_with(sample_cron_trigger_data)

    @pytest.mark.asyncio
    async def test_create_trigger_agent_not_found(
        self, trigger_service, mock_agent_repository, sample_cron_trigger_data
    ):
        """Test trigger creation fails when agent doesn't exist."""
        # Setup mocks
        mock_agent_repository.get.return_value = None  # Agent doesn't exist

        # Execute and verify
        with pytest.raises(TriggerValidationError, match="Agent with ID .* does not exist"):
            await trigger_service.create_trigger(sample_cron_trigger_data)

    @pytest.mark.asyncio
    async def test_create_trigger_invalid_cron_expression(
        self, trigger_service, mock_agent_repository, sample_agent_id
    ):
        """Test trigger creation fails with invalid cron expression."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists

        # Create invalid cron trigger data
        invalid_trigger_data = TriggerCreate(
            name="Invalid Cron",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="invalid",  # Invalid cron expression
            created_by="test_user",
        )

        # Execute and verify
        with pytest.raises(TriggerValidationError, match="Cron expression must have 5 or 6 parts"):
            await trigger_service.create_trigger(invalid_trigger_data)

    @pytest.mark.asyncio
    async def test_create_trigger_missing_webhook_id(
        self, trigger_service, mock_agent_repository, sample_agent_id
    ):
        """Test trigger creation fails when webhook ID is missing."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists

        # Execute and verify - Pydantic validation should catch this
        with pytest.raises(ValueError, match="webhook_id is required for WEBHOOK triggers"):
            TriggerCreate(
                name="Invalid Webhook",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.WEBHOOK,
                created_by="test_user",
            )

    @pytest.mark.asyncio
    async def test_get_trigger_success(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test successful trigger retrieval."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger

        # Execute
        result = await trigger_service.get_trigger(sample_cron_trigger.id)

        # Verify
        assert result == sample_cron_trigger
        mock_trigger_repository.get.assert_called_once_with(sample_cron_trigger.id)

    @pytest.mark.asyncio
    async def test_get_trigger_not_found(self, trigger_service, mock_trigger_repository):
        """Test trigger retrieval when trigger doesn't exist."""
        # Setup mocks
        mock_trigger_repository.get.return_value = None
        trigger_id = uuid4()

        # Execute
        result = await trigger_service.get_trigger(trigger_id)

        # Verify
        assert result is None
        mock_trigger_repository.get.assert_called_once_with(trigger_id)

    @pytest.mark.asyncio
    async def test_update_trigger_success(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test successful trigger update."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        updated_trigger = CronTrigger(**sample_cron_trigger.model_dump())
        updated_trigger.name = "Updated Name"
        mock_trigger_repository.update_by_id.return_value = updated_trigger

        # Create update data
        trigger_update = TriggerUpdate(name="Updated Name")

        # Execute
        result = await trigger_service.update_trigger(sample_cron_trigger.id, trigger_update)

        # Verify
        assert result.name == "Updated Name"
        mock_trigger_repository.get.assert_called_once_with(sample_cron_trigger.id)
        mock_trigger_repository.update_by_id.assert_called_once_with(
            sample_cron_trigger.id, trigger_update
        )

    @pytest.mark.asyncio
    async def test_update_trigger_not_found(self, trigger_service, mock_trigger_repository):
        """Test trigger update when trigger doesn't exist."""
        # Setup mocks
        mock_trigger_repository.get.return_value = None
        trigger_id = uuid4()
        trigger_update = TriggerUpdate(name="Updated Name")

        # Execute and verify
        with pytest.raises(TriggerNotFoundError, match=f"Trigger {trigger_id} not found"):
            await trigger_service.update_trigger(trigger_id, trigger_update)

    @pytest.mark.asyncio
    async def test_delete_trigger_success(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test successful trigger deletion."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_trigger_repository.delete.return_value = True

        # Execute
        result = await trigger_service.delete_trigger(sample_cron_trigger.id)

        # Verify
        assert result is True
        mock_trigger_repository.get.assert_called_once_with(sample_cron_trigger.id)
        mock_trigger_repository.delete.assert_called_once_with(sample_cron_trigger.id)

    @pytest.mark.asyncio
    async def test_delete_trigger_not_found(self, trigger_service, mock_trigger_repository):
        """Test trigger deletion when trigger doesn't exist."""
        # Setup mocks
        mock_trigger_repository.get.return_value = None
        trigger_id = uuid4()

        # Execute
        result = await trigger_service.delete_trigger(trigger_id)

        # Verify
        assert result is False
        mock_trigger_repository.get.assert_called_once_with(trigger_id)
        mock_trigger_repository.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_triggers_all(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger, sample_webhook_trigger
    ):
        """Test listing all triggers."""
        # Setup mocks
        triggers = [sample_cron_trigger, sample_webhook_trigger]
        mock_trigger_repository.list.return_value = triggers

        # Execute
        result = await trigger_service.list_triggers()

        # Verify
        assert result == triggers
        mock_trigger_repository.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_triggers_by_agent(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger, sample_agent_id
    ):
        """Test listing triggers by agent ID."""
        # Setup mocks
        triggers = [sample_cron_trigger]
        mock_trigger_repository.list_by_agent.return_value = triggers

        # Execute
        result = await trigger_service.list_triggers(agent_id=sample_agent_id)

        # Verify
        assert result == triggers
        mock_trigger_repository.list_by_agent.assert_called_once_with(sample_agent_id, 100)

    @pytest.mark.asyncio
    async def test_list_triggers_by_type(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test listing triggers by type."""
        # Setup mocks
        triggers = [sample_cron_trigger]
        mock_trigger_repository.list_by_type.return_value = triggers

        # Execute
        result = await trigger_service.list_triggers(trigger_type=TriggerType.CRON)

        # Verify
        assert result == triggers
        mock_trigger_repository.list_by_type.assert_called_once_with(TriggerType.CRON, 100)

    @pytest.mark.asyncio
    async def test_list_triggers_active_only(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test listing only active triggers."""
        # Setup mocks
        triggers = [sample_cron_trigger]
        mock_trigger_repository.list_active_triggers.return_value = triggers

        # Execute
        result = await trigger_service.list_triggers(active_only=True)

        # Verify
        assert result == triggers
        mock_trigger_repository.list_active_triggers.assert_called_once_with(100)

    # Test Lifecycle Management

    @pytest.mark.asyncio
    async def test_enable_trigger_success(self, trigger_service, mock_trigger_repository):
        """Test successful trigger enabling."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.enable_trigger.return_value = True

        # Execute
        result = await trigger_service.enable_trigger(trigger_id)

        # Verify
        assert result is True
        mock_trigger_repository.enable_trigger.assert_called_once_with(trigger_id)

    @pytest.mark.asyncio
    async def test_enable_trigger_not_found(self, trigger_service, mock_trigger_repository):
        """Test trigger enabling when trigger doesn't exist."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.enable_trigger.return_value = False

        # Execute
        result = await trigger_service.enable_trigger(trigger_id)

        # Verify
        assert result is False
        mock_trigger_repository.enable_trigger.assert_called_once_with(trigger_id)

    @pytest.mark.asyncio
    async def test_disable_trigger_success(self, trigger_service, mock_trigger_repository):
        """Test successful trigger disabling."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.disable_trigger.return_value = True

        # Execute
        result = await trigger_service.disable_trigger(trigger_id)

        # Verify
        assert result is True
        mock_trigger_repository.disable_trigger.assert_called_once_with(trigger_id)

    @pytest.mark.asyncio
    async def test_disable_trigger_not_found(self, trigger_service, mock_trigger_repository):
        """Test trigger disabling when trigger doesn't exist."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.disable_trigger.return_value = False

        # Execute
        result = await trigger_service.disable_trigger(trigger_id)

        # Verify
        assert result is False
        mock_trigger_repository.disable_trigger.assert_called_once_with(trigger_id)

    # Test Execution History

    @pytest.mark.asyncio
    async def test_get_execution_history(self, trigger_service, mock_trigger_execution_repository):
        """Test getting execution history."""
        # Setup mocks
        trigger_id = uuid4()
        executions = [
            TriggerExecution(
                trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=100
            )
        ]
        mock_trigger_execution_repository.list_by_trigger.return_value = executions

        # Execute
        result = await trigger_service.get_execution_history(trigger_id)

        # Verify
        assert result == executions
        mock_trigger_execution_repository.list_by_trigger.assert_called_once_with(
            trigger_id, 100, 0
        )

    @pytest.mark.asyncio
    async def test_record_execution_success(
        self, trigger_service, mock_trigger_execution_repository, mock_trigger_repository
    ):
        """Test recording successful execution."""
        # Setup mocks
        trigger_id = uuid4()
        task_id = uuid4()
        execution = TriggerExecution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
            task_id=task_id,
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.update_execution_tracking.return_value = True

        # Execute
        result = await trigger_service.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
            task_id=task_id,
        )

        # Verify
        assert result.status == ExecutionStatus.SUCCESS
        assert result.task_id == task_id
        mock_trigger_execution_repository.create.assert_called_once()
        mock_trigger_repository.update_execution_tracking.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_execution_failure_auto_disable(
        self,
        trigger_service,
        mock_trigger_execution_repository,
        mock_trigger_repository,
        sample_cron_trigger,
    ):
        """Test recording failed execution that triggers auto-disable."""
        # Setup mocks - trigger at failure threshold
        sample_cron_trigger.consecutive_failures = 4  # One less than threshold (5)
        sample_cron_trigger.failure_threshold = 5

        trigger_id = sample_cron_trigger.id
        execution = TriggerExecution(
            trigger_id=trigger_id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Test error",
        )

        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_trigger_repository.update_execution_tracking.return_value = True
        mock_trigger_repository.disable_trigger.return_value = True

        # Execute
        result = await trigger_service.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Test error",
        )

        # Verify
        assert result.status == ExecutionStatus.FAILED
        mock_trigger_execution_repository.create.assert_called_once()
        mock_trigger_repository.update_execution_tracking.assert_called_once()
        mock_trigger_repository.disable_trigger.assert_called_once_with(trigger_id)

    # Test Utility Methods

    @pytest.mark.asyncio
    async def test_get_trigger_by_webhook_id(
        self, trigger_service, mock_trigger_repository, sample_webhook_trigger
    ):
        """Test getting trigger by webhook ID."""
        # Setup mocks
        mock_trigger_repository.get_by_webhook_id.return_value = sample_webhook_trigger

        # Execute
        result = await trigger_service.get_trigger_by_webhook_id("webhook_123")

        # Verify
        assert result == sample_webhook_trigger
        mock_trigger_repository.get_by_webhook_id.assert_called_once_with("webhook_123")

    @pytest.mark.asyncio
    async def test_get_trigger_by_webhook_id_not_webhook_trigger(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test getting trigger by webhook ID when trigger is not a webhook trigger."""
        # Setup mocks - return cron trigger instead of webhook trigger
        mock_trigger_repository.get_by_webhook_id.return_value = sample_cron_trigger

        # Execute
        result = await trigger_service.get_trigger_by_webhook_id("webhook_123")

        # Verify
        assert result is None
        mock_trigger_repository.get_by_webhook_id.assert_called_once_with("webhook_123")

    @pytest.mark.asyncio
    async def test_list_cron_triggers_due(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test listing cron triggers due for execution."""
        # Setup mocks
        current_time = datetime.utcnow()
        triggers = [sample_cron_trigger]
        mock_trigger_repository.list_cron_triggers_due.return_value = triggers

        # Execute
        result = await trigger_service.list_cron_triggers_due(current_time)

        # Verify
        assert result == triggers
        mock_trigger_repository.list_cron_triggers_due.assert_called_once_with(current_time)

    @pytest.mark.asyncio
    async def test_get_recent_executions(self, trigger_service, mock_trigger_execution_repository):
        """Test getting recent executions."""
        # Setup mocks
        trigger_id = uuid4()
        executions = [
            TriggerExecution(
                trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=100
            )
        ]
        mock_trigger_execution_repository.get_recent_executions.return_value = executions

        # Execute
        result = await trigger_service.get_recent_executions(trigger_id, hours=12, limit=50)

        # Verify
        assert result == executions
        mock_trigger_execution_repository.get_recent_executions.assert_called_once_with(
            trigger_id, 12, 50
        )

    @pytest.mark.asyncio
    async def test_count_executions_in_period(
        self, trigger_service, mock_trigger_execution_repository
    ):
        """Test counting executions in a time period."""
        # Setup mocks
        trigger_id = uuid4()
        start_time = datetime.utcnow() - timedelta(hours=24)
        end_time = datetime.utcnow()
        mock_trigger_execution_repository.count_executions_in_period.return_value = 5

        # Execute
        result = await trigger_service.count_executions_in_period(trigger_id, start_time, end_time)

        # Verify
        assert result == 5
        mock_trigger_execution_repository.count_executions_in_period.assert_called_once_with(
            trigger_id, start_time, end_time
        )

    # Test Validation Edge Cases

    @pytest.mark.asyncio
    async def test_create_trigger_empty_name(
        self, trigger_service, mock_agent_repository, sample_agent_id
    ):
        """Test trigger creation fails with empty name."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists

        # Execute and verify - Pydantic validation should catch this
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            TriggerCreate(
                name="",  # Empty name
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression="0 9 * * *",
                created_by="test_user",
            )

    @pytest.mark.asyncio
    async def test_create_trigger_empty_created_by(
        self, trigger_service, mock_agent_repository, sample_agent_id
    ):
        """Test trigger creation fails with empty created_by."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists

        # Create trigger data with empty created_by
        invalid_trigger_data = TriggerCreate(
            name="Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="",  # Empty created_by
        )

        # Execute and verify
        with pytest.raises(TriggerValidationError, match="Trigger created_by is required"):
            await trigger_service.create_trigger(invalid_trigger_data)

    @pytest.mark.asyncio
    async def test_create_trigger_invalid_http_method(
        self, trigger_service, mock_agent_repository, sample_agent_id
    ):
        """Test trigger creation fails with invalid HTTP method."""
        # Setup mocks
        mock_agent_repository.get.return_value = MagicMock()  # Agent exists

        # Create webhook trigger data with invalid HTTP method
        invalid_trigger_data = TriggerCreate(
            name="Webhook Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="webhook_123",
            allowed_methods=["INVALID"],  # Invalid HTTP method
            created_by="test_user",
        )

        # Execute and verify
        with pytest.raises(TriggerValidationError, match="Invalid HTTP method: INVALID"):
            await trigger_service.create_trigger(invalid_trigger_data)

    @pytest.mark.asyncio
    async def test_update_trigger_empty_name(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test trigger update fails with empty name."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger

        # Execute and verify - Pydantic validation should catch this
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            TriggerUpdate(name="")

    @pytest.mark.asyncio
    async def test_update_trigger_invalid_cron_expression(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test trigger update fails with invalid cron expression."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger

        # Create update data with invalid cron expression
        trigger_update = TriggerUpdate(cron_expression="invalid")

        # Execute and verify
        with pytest.raises(TriggerValidationError, match="Cron expression must have 5 or 6 parts"):
            await trigger_service.update_trigger(sample_cron_trigger.id, trigger_update)

    @pytest.mark.asyncio
    async def test_agent_repository_not_available(
        self,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_event_broker,
        sample_cron_trigger_data,
    ):
        """Test trigger creation when agent repository is not available."""
        # Create service without agent repository
        trigger_service = TriggerService(
            trigger_repository=mock_trigger_repository,
            trigger_execution_repository=mock_trigger_execution_repository,
            event_broker=mock_event_broker,
            agent_repository=None,  # No agent repository
        )

        # Setup mocks
        sample_trigger = CronTrigger(**sample_cron_trigger_data.model_dump())
        mock_trigger_repository.create_from_data.return_value = sample_trigger

        # Execute - should succeed with warning logged
        result = await trigger_service.create_trigger(sample_cron_trigger_data)

        # Verify
        assert result == sample_trigger
        mock_trigger_repository.create_from_data.assert_called_once_with(sample_cron_trigger_data)

    @pytest.mark.asyncio
    async def test_create_cron_trigger_schedules(
        self,
        trigger_service,
        mock_trigger_repository,
        sample_cron_trigger_data,
        sample_cron_trigger,
    ):
        """Test that creating a cron trigger schedules it."""
        # Setup mocks
        mock_trigger_repository.create_from_data.return_value = sample_cron_trigger

        # Execute
        await trigger_service.create_trigger(sample_cron_trigger_data)

        # Verify schedule was created
        trigger_service._mock_temporal_schedule_manager.create_cron_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_cron_trigger_updates_schedule(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test that updating a cron trigger updates its schedule."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_trigger_repository.update_by_id.return_value = sample_cron_trigger

        # Create update with new cron expression
        trigger_update = TriggerUpdate(cron_expression="0 10 * * *")

        # Execute
        await trigger_service.update_trigger(sample_cron_trigger.id, trigger_update)

        # Verify schedule was updated
        trigger_service._mock_temporal_schedule_manager.update_cron_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_cron_trigger_deletes_schedule(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test that deleting a cron trigger deletes its schedule."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_trigger_repository.delete.return_value = True

        # Execute
        result = await trigger_service.delete_trigger(sample_cron_trigger.id)

        # Verify
        assert result is True
        trigger_service._mock_temporal_schedule_manager.delete_cron_schedule.assert_called_once_with(
            sample_cron_trigger.id
        )

    @pytest.mark.asyncio
    async def test_enable_cron_trigger_unpauses_schedule(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test that enabling a cron trigger unpauses its schedule."""
        # Setup mocks
        mock_trigger_repository.enable_trigger.return_value = True
        mock_trigger_repository.get.return_value = sample_cron_trigger

        # Execute
        result = await trigger_service.enable_trigger(sample_cron_trigger.id)

        # Verify
        assert result is True
        trigger_service._mock_temporal_schedule_manager.unpause_cron_schedule.assert_called_once_with(
            sample_cron_trigger.id
        )

    @pytest.mark.asyncio
    async def test_disable_cron_trigger_pauses_schedule(
        self, trigger_service, mock_trigger_repository, sample_cron_trigger
    ):
        """Test that disabling a cron trigger pauses its schedule."""
        # Setup mocks
        mock_trigger_repository.disable_trigger.return_value = True
        mock_trigger_repository.get.return_value = sample_cron_trigger

        # Execute
        result = await trigger_service.disable_trigger(sample_cron_trigger.id)

        # Verify
        assert result is True
        trigger_service._mock_temporal_schedule_manager.pause_cron_schedule.assert_called_once_with(
            sample_cron_trigger.id
        )

    @pytest.mark.asyncio
    async def test_execute_trigger_success(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_task_service,
        sample_cron_trigger,
    ):
        """Test successful trigger execution."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_task_service.create_task_from_params.return_value = MagicMock(id=uuid4())
        mock_trigger_execution_repository.create.return_value = MagicMock(
            id=uuid4(), trigger_id=sample_cron_trigger.id, status=ExecutionStatus.SUCCESS
        )

        # Execute
        trigger_data = {"source": "test"}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, trigger_data)

        # Verify
        assert result.status == ExecutionStatus.SUCCESS
        mock_task_service.create_task_from_params.assert_called_once()
        mock_trigger_execution_repository.create.assert_called_once()
        mock_trigger_repository.update.assert_called_once()  # For execution tracking

    @pytest.mark.asyncio
    async def test_execute_trigger_inactive(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        sample_cron_trigger,
    ):
        """Test executing an inactive trigger."""
        # Setup mocks - inactive trigger
        inactive_trigger = CronTrigger(**sample_cron_trigger.model_dump())
        inactive_trigger.is_active = False
        mock_trigger_repository.get.return_value = inactive_trigger
        mock_trigger_execution_repository.create.return_value = MagicMock(
            id=uuid4(),
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.FAILED,
            error_message="Trigger is inactive",
        )

        # Execute
        trigger_data = {"source": "test"}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, trigger_data)

        # Verify
        assert result.status == ExecutionStatus.FAILED
        assert "inactive" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_execute_trigger_task_creation_error(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_task_service,
        sample_cron_trigger,
    ):
        """Test trigger execution with task creation error."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_cron_trigger
        mock_task_service.create_task_from_params.side_effect = Exception("Task creation failed")
        mock_trigger_execution_repository.create.return_value = MagicMock(
            id=uuid4(),
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.FAILED,
            error_message="Task creation failed",
        )

        # Execute
        trigger_data = {"source": "test"}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, trigger_data)

        # Verify
        assert result.status == ExecutionStatus.FAILED
        assert "failed" in result.error_message.lower()
        mock_trigger_repository.update.assert_called_once()  # For execution tracking


class TestTriggerServiceMonitoring:
    """Test cases for TriggerService monitoring and execution history enhancements."""

    @pytest.fixture
    def mock_trigger_repository(self):
        """Mock trigger repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_trigger_execution_repository(self):
        """Mock trigger execution repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker."""
        return AsyncMock()

    @pytest.fixture
    def trigger_service(
        self, mock_trigger_repository, mock_trigger_execution_repository, mock_event_broker
    ):
        """Create TriggerService instance with mocked dependencies."""
        return TriggerService(
            trigger_repository=mock_trigger_repository,
            trigger_execution_repository=mock_trigger_execution_repository,
            event_broker=mock_event_broker,
        )

    @pytest.fixture
    def sample_trigger_id(self):
        """Sample trigger ID."""
        return uuid4()

    @pytest.fixture
    def sample_executions(self, sample_trigger_id):
        """Sample trigger executions."""
        return [
            TriggerExecution(
                id=uuid4(),
                trigger_id=sample_trigger_id,
                executed_at=datetime.utcnow() - timedelta(minutes=30),
                status=ExecutionStatus.SUCCESS,
                task_id=uuid4(),
                execution_time_ms=1200,
                trigger_data={"key": "value1"},
            ),
            TriggerExecution(
                id=uuid4(),
                trigger_id=sample_trigger_id,
                executed_at=datetime.utcnow() - timedelta(minutes=20),
                status=ExecutionStatus.FAILED,
                task_id=None,
                execution_time_ms=800,
                error_message="Test error",
                trigger_data={"key": "value2"},
            ),
            TriggerExecution(
                id=uuid4(),
                trigger_id=sample_trigger_id,
                executed_at=datetime.utcnow() - timedelta(minutes=10),
                status=ExecutionStatus.SUCCESS,
                task_id=uuid4(),
                execution_time_ms=1500,
                trigger_data={"key": "value3"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_execution_history_paginated(
        self,
        trigger_service,
        mock_trigger_execution_repository,
        sample_trigger_id,
        sample_executions,
    ):
        """Test getting paginated execution history."""
        # Setup mocks
        mock_trigger_execution_repository.list_executions_paginated.return_value = (
            sample_executions[:2]
        )
        mock_trigger_execution_repository.count_executions_filtered.return_value = 10

        # Execute
        executions, total = await trigger_service.get_execution_history_paginated(
            trigger_id=sample_trigger_id, limit=2, offset=0
        )

        # Verify
        assert len(executions) == 2
        assert total == 10
        mock_trigger_execution_repository.list_executions_paginated.assert_called_once_with(
            trigger_id=sample_trigger_id,
            status=None,
            start_time=None,
            end_time=None,
            limit=2,
            offset=0,
        )
        mock_trigger_execution_repository.count_executions_filtered.assert_called_once_with(
            trigger_id=sample_trigger_id, status=None, start_time=None, end_time=None
        )

    @pytest.mark.asyncio
    async def test_get_execution_history_paginated_with_filters(
        self,
        trigger_service,
        mock_trigger_execution_repository,
        sample_trigger_id,
        sample_executions,
    ):
        """Test getting paginated execution history with status filter."""
        # Setup mocks - only successful executions
        successful_executions = [
            exec for exec in sample_executions if exec.status == ExecutionStatus.SUCCESS
        ]
        mock_trigger_execution_repository.list_executions_paginated.return_value = (
            successful_executions
        )
        mock_trigger_execution_repository.count_executions_filtered.return_value = 2

        # Execute
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow()
        executions, total = await trigger_service.get_execution_history_paginated(
            trigger_id=sample_trigger_id,
            status=ExecutionStatus.SUCCESS,
            start_time=start_time,
            end_time=end_time,
            limit=10,
            offset=0,
        )

        # Verify
        assert len(executions) == 2
        assert total == 2
        assert all(exec.status == ExecutionStatus.SUCCESS for exec in executions)
        mock_trigger_execution_repository.list_executions_paginated.assert_called_once_with(
            trigger_id=sample_trigger_id,
            status=ExecutionStatus.SUCCESS,
            start_time=start_time,
            end_time=end_time,
            limit=10,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_get_execution_metrics(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution metrics."""
        # Setup mock metrics data
        metrics_data = {
            "total_executions": 10,
            "successful_executions": 8,
            "failed_executions": 1,
            "timeout_executions": 1,
            "success_rate": 80.0,
            "failure_rate": 20.0,
            "avg_execution_time_ms": 1250.5,
            "min_execution_time_ms": 800,
            "max_execution_time_ms": 2000,
            "period_hours": 24,
        }
        mock_trigger_execution_repository.get_execution_metrics.return_value = metrics_data

        # Execute
        result = await trigger_service.get_execution_metrics(sample_trigger_id, hours=24)

        # Verify
        assert result == metrics_data
        mock_trigger_execution_repository.get_execution_metrics.assert_called_once_with(
            sample_trigger_id, 24
        )

    @pytest.mark.asyncio
    async def test_get_execution_timeline(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution timeline."""
        # Setup mock timeline data
        timeline_data = [
            {
                "time_bucket": datetime.utcnow() - timedelta(hours=2),
                "total_count": 5,
                "success_count": 4,
                "failed_count": 1,
                "timeout_count": 0,
                "success_rate": 80.0,
            },
            {
                "time_bucket": datetime.utcnow() - timedelta(hours=1),
                "total_count": 3,
                "success_count": 2,
                "failed_count": 0,
                "timeout_count": 1,
                "success_rate": 66.67,
            },
        ]
        mock_trigger_execution_repository.get_execution_timeline.return_value = timeline_data

        # Execute
        result = await trigger_service.get_execution_timeline(
            sample_trigger_id, hours=24, bucket_size_minutes=60
        )

        # Verify
        assert result == timeline_data
        assert len(result) == 2
        assert result[0]["total_count"] == 5
        assert result[0]["success_rate"] == 80.0
        mock_trigger_execution_repository.get_execution_timeline.assert_called_once_with(
            sample_trigger_id, 24, 60
        )

    @pytest.mark.asyncio
    async def test_get_execution_correlations(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution correlations."""
        # Setup mock correlation data
        correlation_data = [
            {
                "id": uuid4(),
                "trigger_id": sample_trigger_id,
                "executed_at": datetime.utcnow() - timedelta(minutes=30),
                "status": "success",
                "task_id": uuid4(),
                "execution_time_ms": 1200,
                "error_message": None,
                "trigger_data": {"key": "value1"},
                "workflow_id": "workflow_1",
                "run_id": "run_1",
                "has_task_correlation": True,
                "has_workflow_correlation": True,
            },
            {
                "id": uuid4(),
                "trigger_id": sample_trigger_id,
                "executed_at": datetime.utcnow() - timedelta(minutes=20),
                "status": "failed",
                "task_id": None,
                "execution_time_ms": 800,
                "error_message": "Test error",
                "trigger_data": {"key": "value2"},
                "workflow_id": "workflow_2",
                "run_id": "run_2",
                "has_task_correlation": False,
                "has_workflow_correlation": True,
            },
        ]
        mock_trigger_execution_repository.get_executions_with_task_correlation.return_value = (
            correlation_data
        )
        mock_trigger_execution_repository.count_executions_filtered.return_value = 5

        # Execute
        correlations, total = await trigger_service.get_execution_correlations(
            sample_trigger_id, limit=10, offset=0
        )

        # Verify
        assert correlations == correlation_data
        assert total == 5
        assert len(correlations) == 2
        assert correlations[0]["has_task_correlation"] is True
        assert correlations[1]["has_task_correlation"] is False
        assert all(corr["has_workflow_correlation"] is True for corr in correlations)

        mock_trigger_execution_repository.get_executions_with_task_correlation.assert_called_once_with(
            sample_trigger_id, 10, 0
        )
        mock_trigger_execution_repository.count_executions_filtered.assert_called_once_with(
            trigger_id=sample_trigger_id
        )

    @pytest.mark.asyncio
    async def test_get_execution_metrics_no_data(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution metrics when no data exists."""
        # Setup mock for no data
        empty_metrics = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "timeout_executions": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "avg_execution_time_ms": 0.0,
            "min_execution_time_ms": 0,
            "max_execution_time_ms": 0,
            "period_hours": 24,
        }
        mock_trigger_execution_repository.get_execution_metrics.return_value = empty_metrics

        # Execute
        result = await trigger_service.get_execution_metrics(sample_trigger_id, hours=24)

        # Verify
        assert result == empty_metrics
        assert result["total_executions"] == 0
        assert result["success_rate"] == 0.0
        mock_trigger_execution_repository.get_execution_metrics.assert_called_once_with(
            sample_trigger_id, 24
        )

    @pytest.mark.asyncio
    async def test_get_execution_timeline_empty(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution timeline when no data exists."""
        # Setup mock for empty timeline
        mock_trigger_execution_repository.get_execution_timeline.return_value = []

        # Execute
        result = await trigger_service.get_execution_timeline(
            sample_trigger_id, hours=24, bucket_size_minutes=60
        )

        # Verify
        assert result == []
        mock_trigger_execution_repository.get_execution_timeline.assert_called_once_with(
            sample_trigger_id, 24, 60
        )

    @pytest.mark.asyncio
    async def test_get_execution_correlations_empty(
        self, trigger_service, mock_trigger_execution_repository, sample_trigger_id
    ):
        """Test getting execution correlations when no data exists."""
        # Setup mock for empty correlations
        mock_trigger_execution_repository.get_executions_with_task_correlation.return_value = []
        mock_trigger_execution_repository.count_executions_filtered.return_value = 0

        # Execute
        correlations, total = await trigger_service.get_execution_correlations(
            sample_trigger_id, limit=10, offset=0
        )

        # Verify
        assert correlations == []
        assert total == 0
        mock_trigger_execution_repository.get_executions_with_task_correlation.assert_called_once_with(
            sample_trigger_id, 10, 0
        )
        mock_trigger_execution_repository.count_executions_filtered.assert_called_once_with(
            trigger_id=sample_trigger_id
        )
