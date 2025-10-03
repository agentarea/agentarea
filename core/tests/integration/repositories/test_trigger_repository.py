"""Integration tests for trigger repositories."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
from agentarea_triggers.domain.models import (
    CronTrigger,
    TriggerCreate,
    TriggerExecution,
    TriggerUpdate,
    WebhookTrigger,
)
from agentarea_triggers.infrastructure.repository import (
    TriggerExecutionRepository,
    TriggerRepository,
)


@pytest.mark.asyncio
class TestTriggerRepository:
    """Test cases for TriggerRepository."""

    @pytest_asyncio.fixture
    def trigger_repository(self, db_session):
        """Provide a TriggerRepository instance."""
        return TriggerRepository(db_session)

    @pytest_asyncio.fixture
    def sample_cron_trigger(self):
        """Create a sample cron trigger."""
        return CronTrigger(
            id=uuid4(),
            name="Daily Report",
            description="Generate daily report",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            is_active=True,
            task_parameters={"report_type": "daily"},
            conditions={"time_condition": "business_hours"},
            created_by="test-user",
            cron_expression="0 9 * * *",
            timezone="UTC",
            max_executions_per_hour=1,
            failure_threshold=3,
        )

    @pytest_asyncio.fixture
    def sample_webhook_trigger(self):
        """Create a sample webhook trigger."""
        return WebhookTrigger(
            id=uuid4(),
            name="GitHub Webhook",
            description="Handle GitHub push events",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            is_active=True,
            task_parameters={"action": "process_push"},
            conditions={"branch": "main"},
            created_by="test-user",
            webhook_id="github-webhook-123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.GITHUB,
            validation_rules={"require_signature": True},
            github_config={"secret": "webhook-secret"},
        )

    async def test_create_cron_trigger(self, trigger_repository, sample_cron_trigger):
        """Test creating a cron trigger."""
        # Act
        created_trigger = await trigger_repository.create(sample_cron_trigger)

        # Assert
        assert created_trigger.id == sample_cron_trigger.id
        assert created_trigger.name == "Daily Report"
        assert created_trigger.trigger_type == TriggerType.CRON
        assert isinstance(created_trigger, CronTrigger)
        assert created_trigger.cron_expression == "0 9 * * *"
        assert created_trigger.timezone == "UTC"

    async def test_create_webhook_trigger(self, trigger_repository, sample_webhook_trigger):
        """Test creating a webhook trigger."""
        # Act
        created_trigger = await trigger_repository.create(sample_webhook_trigger)

        # Assert
        assert created_trigger.id == sample_webhook_trigger.id
        assert created_trigger.name == "GitHub Webhook"
        assert created_trigger.trigger_type == TriggerType.WEBHOOK
        assert isinstance(created_trigger, WebhookTrigger)
        assert created_trigger.webhook_id == "github-webhook-123"
        assert created_trigger.webhook_type == WebhookType.GITHUB
        assert created_trigger.allowed_methods == ["POST"]

    async def test_get_trigger_by_id(self, trigger_repository, sample_cron_trigger):
        """Test retrieving a trigger by ID."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)

        # Act
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)

        # Assert
        assert retrieved_trigger is not None
        assert retrieved_trigger.id == sample_cron_trigger.id
        assert retrieved_trigger.name == "Daily Report"
        assert isinstance(retrieved_trigger, CronTrigger)

    async def test_get_nonexistent_trigger(self, trigger_repository):
        """Test retrieving a non-existent trigger."""
        # Act
        result = await trigger_repository.get(uuid4())

        # Assert
        assert result is None

    async def test_list_triggers(
        self, trigger_repository, sample_cron_trigger, sample_webhook_trigger
    ):
        """Test listing all triggers."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)
        await trigger_repository.create(sample_webhook_trigger)

        # Act
        triggers = await trigger_repository.list()

        # Assert
        assert len(triggers) == 2
        trigger_names = [t.name for t in triggers]
        assert "Daily Report" in trigger_names
        assert "GitHub Webhook" in trigger_names

    async def test_update_trigger(self, trigger_repository, sample_cron_trigger):
        """Test updating a trigger."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)
        sample_cron_trigger.name = "Updated Daily Report"
        sample_cron_trigger.description = "Updated description"

        # Act
        updated_trigger = await trigger_repository.update(sample_cron_trigger)

        # Assert
        assert updated_trigger.name == "Updated Daily Report"
        assert updated_trigger.description == "Updated description"

        # Verify in database
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)
        assert retrieved_trigger.name == "Updated Daily Report"

    async def test_delete_trigger(self, trigger_repository, sample_cron_trigger):
        """Test deleting a trigger."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)

        # Act
        deleted = await trigger_repository.delete(sample_cron_trigger.id)

        # Assert
        assert deleted is True

        # Verify deletion
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)
        assert retrieved_trigger is None

    async def test_delete_nonexistent_trigger(self, trigger_repository):
        """Test deleting a non-existent trigger."""
        # Act
        deleted = await trigger_repository.delete(uuid4())

        # Assert
        assert deleted is False

    async def test_create_from_data(self, trigger_repository):
        """Test creating trigger from TriggerCreate data."""
        # Arrange
        trigger_data = TriggerCreate(
            name="Test Cron Trigger",
            description="Test description",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            created_by="test-user",
            cron_expression="0 10 * * *",
            timezone="America/New_York",
            task_parameters={"test": "value"},
            conditions={"env": "test"},
        )

        # Act
        created_trigger = await trigger_repository.create_from_data(trigger_data)

        # Assert
        assert created_trigger.name == "Test Cron Trigger"
        assert created_trigger.trigger_type == TriggerType.CRON
        assert isinstance(created_trigger, CronTrigger)
        assert created_trigger.cron_expression == "0 10 * * *"
        assert created_trigger.timezone == "America/New_York"

    async def test_update_by_id(self, trigger_repository, sample_cron_trigger):
        """Test updating trigger by ID with TriggerUpdate data."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)
        update_data = TriggerUpdate(
            name="Updated Name",
            description="Updated description",
            is_active=False,
        )

        # Act
        updated_trigger = await trigger_repository.update_by_id(sample_cron_trigger.id, update_data)

        # Assert
        assert updated_trigger is not None
        assert updated_trigger.name == "Updated Name"
        assert updated_trigger.description == "Updated description"
        assert updated_trigger.is_active is False

    async def test_list_by_agent(
        self, trigger_repository, sample_cron_trigger, sample_webhook_trigger
    ):
        """Test listing triggers by agent ID."""
        # Arrange
        agent_id = uuid4()
        sample_cron_trigger.agent_id = agent_id
        sample_webhook_trigger.agent_id = agent_id
        other_trigger = CronTrigger(
            id=uuid4(),
            name="Other Trigger",
            description="Different agent",
            agent_id=uuid4(),  # Different agent
            trigger_type=TriggerType.CRON,
            created_by="test-user",
            cron_expression="0 8 * * *",
        )

        await trigger_repository.create(sample_cron_trigger)
        await trigger_repository.create(sample_webhook_trigger)
        await trigger_repository.create(other_trigger)

        # Act
        agent_triggers = await trigger_repository.list_by_agent(agent_id)

        # Assert
        assert len(agent_triggers) == 2
        for trigger in agent_triggers:
            assert trigger.agent_id == agent_id

    async def test_list_by_type(
        self, trigger_repository, sample_cron_trigger, sample_webhook_trigger
    ):
        """Test listing triggers by type."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)
        await trigger_repository.create(sample_webhook_trigger)

        # Act
        cron_triggers = await trigger_repository.list_by_type(TriggerType.CRON)
        webhook_triggers = await trigger_repository.list_by_type(TriggerType.WEBHOOK)

        # Assert
        assert len(cron_triggers) == 1
        assert len(webhook_triggers) == 1
        assert cron_triggers[0].trigger_type == TriggerType.CRON
        assert webhook_triggers[0].trigger_type == TriggerType.WEBHOOK

    async def test_list_active_triggers(
        self, trigger_repository, sample_cron_trigger, sample_webhook_trigger
    ):
        """Test listing active triggers."""
        # Arrange
        sample_webhook_trigger.is_active = False  # Make one inactive
        await trigger_repository.create(sample_cron_trigger)
        await trigger_repository.create(sample_webhook_trigger)

        # Act
        active_triggers = await trigger_repository.list_active_triggers()

        # Assert
        assert len(active_triggers) == 1
        assert active_triggers[0].is_active is True
        assert active_triggers[0].name == "Daily Report"

    async def test_get_by_webhook_id(self, trigger_repository, sample_webhook_trigger):
        """Test getting trigger by webhook ID."""
        # Arrange
        await trigger_repository.create(sample_webhook_trigger)

        # Act
        retrieved_trigger = await trigger_repository.get_by_webhook_id("github-webhook-123")

        # Assert
        assert retrieved_trigger is not None
        assert retrieved_trigger.webhook_id == "github-webhook-123"
        assert isinstance(retrieved_trigger, WebhookTrigger)

    async def test_list_cron_triggers_due(self, trigger_repository):
        """Test listing cron triggers that are due for execution."""
        # Arrange
        past_time = datetime.utcnow() - timedelta(minutes=5)
        future_time = datetime.utcnow() + timedelta(minutes=5)

        due_trigger = CronTrigger(
            id=uuid4(),
            name="Due Trigger",
            description="Should be due",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            created_by="test-user",
            cron_expression="* * * * *",
            next_run_time=past_time,
        )

        not_due_trigger = CronTrigger(
            id=uuid4(),
            name="Not Due Trigger",
            description="Should not be due",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            created_by="test-user",
            cron_expression="* * * * *",
            next_run_time=future_time,
        )

        await trigger_repository.create(due_trigger)
        await trigger_repository.create(not_due_trigger)

        # Act
        due_triggers = await trigger_repository.list_cron_triggers_due(datetime.utcnow())

        # Assert
        assert len(due_triggers) == 1
        assert due_triggers[0].name == "Due Trigger"

    async def test_update_execution_tracking(self, trigger_repository, sample_cron_trigger):
        """Test updating trigger execution tracking fields."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)
        execution_time = datetime.utcnow()

        # Act
        updated = await trigger_repository.update_execution_tracking(
            sample_cron_trigger.id, execution_time, consecutive_failures=2
        )

        # Assert
        assert updated is True

        # Verify update
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)
        assert retrieved_trigger.last_execution_at == execution_time
        assert retrieved_trigger.consecutive_failures == 2

    async def test_disable_enable_trigger(self, trigger_repository, sample_cron_trigger):
        """Test disabling and enabling a trigger."""
        # Arrange
        await trigger_repository.create(sample_cron_trigger)

        # Act - Disable
        disabled = await trigger_repository.disable_trigger(sample_cron_trigger.id)
        assert disabled is True

        # Verify disabled
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)
        assert retrieved_trigger.is_active is False

        # Act - Enable
        enabled = await trigger_repository.enable_trigger(sample_cron_trigger.id)
        assert enabled is True

        # Verify enabled
        retrieved_trigger = await trigger_repository.get(sample_cron_trigger.id)
        assert retrieved_trigger.is_active is True


@pytest.mark.asyncio
class TestTriggerExecutionRepository:
    """Test cases for TriggerExecutionRepository."""

    @pytest_asyncio.fixture
    def execution_repository(self, db_session):
        """Provide a TriggerExecutionRepository instance."""
        return TriggerExecutionRepository(db_session)

    @pytest_asyncio.fixture
    def trigger_repository(self, db_session):
        """Provide a TriggerRepository instance."""
        return TriggerRepository(db_session)

    @pytest_asyncio.fixture
    async def sample_trigger(self, trigger_repository):
        """Create and persist a sample trigger."""
        trigger = CronTrigger(
            id=uuid4(),
            name="Test Trigger",
            description="Test trigger for executions",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            created_by="test-user",
            cron_expression="0 9 * * *",
        )
        return await trigger_repository.create(trigger)

    @pytest_asyncio.fixture
    def sample_execution(self, sample_trigger):
        """Create a sample trigger execution."""
        return TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            executed_at=datetime.utcnow(),
            status=ExecutionStatus.SUCCESS,
            task_id=uuid4(),
            execution_time_ms=1500,
            trigger_data={"source": "cron", "timestamp": "2025-01-21T14:00:00Z"},
            workflow_id="workflow-123",
            run_id="run-456",
        )

    async def test_create_execution(self, execution_repository, sample_execution):
        """Test creating a trigger execution."""
        # Act
        created_execution = await execution_repository.create(sample_execution)

        # Assert
        assert created_execution.id == sample_execution.id
        assert created_execution.trigger_id == sample_execution.trigger_id
        assert created_execution.status == ExecutionStatus.SUCCESS
        assert created_execution.execution_time_ms == 1500
        assert created_execution.workflow_id == "workflow-123"

    async def test_get_execution_by_id(self, execution_repository, sample_execution):
        """Test retrieving an execution by ID."""
        # Arrange
        await execution_repository.create(sample_execution)

        # Act
        retrieved_execution = await execution_repository.get(sample_execution.id)

        # Assert
        assert retrieved_execution is not None
        assert retrieved_execution.id == sample_execution.id
        assert retrieved_execution.status == ExecutionStatus.SUCCESS

    async def test_list_executions(self, execution_repository, sample_trigger):
        """Test listing all executions."""
        # Arrange
        execution1 = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )
        execution2 = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=500,
            error_message="Test error",
        )

        await execution_repository.create(execution1)
        await execution_repository.create(execution2)

        # Act
        executions = await execution_repository.list()

        # Assert
        assert len(executions) == 2
        statuses = [e.status for e in executions]
        assert ExecutionStatus.SUCCESS in statuses
        assert ExecutionStatus.FAILED in statuses

    async def test_list_by_trigger(self, execution_repository, sample_trigger):
        """Test listing executions by trigger ID."""
        # Arrange
        other_trigger_id = uuid4()

        execution1 = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )
        execution2 = TriggerExecution(
            id=uuid4(),
            trigger_id=other_trigger_id,  # Different trigger
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )

        await execution_repository.create(execution1)
        await execution_repository.create(execution2)

        # Act
        trigger_executions = await execution_repository.list_by_trigger(sample_trigger.id)

        # Assert
        assert len(trigger_executions) == 1
        assert trigger_executions[0].trigger_id == sample_trigger.id

    async def test_list_by_status(self, execution_repository, sample_trigger):
        """Test listing executions by status."""
        # Arrange
        success_execution = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )
        failed_execution = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=500,
            error_message="Test error",
        )

        await execution_repository.create(success_execution)
        await execution_repository.create(failed_execution)

        # Act
        failed_executions = await execution_repository.list_by_status(ExecutionStatus.FAILED)

        # Assert
        assert len(failed_executions) == 1
        assert failed_executions[0].status == ExecutionStatus.FAILED
        assert failed_executions[0].error_message == "Test error"

    async def test_get_recent_executions(self, execution_repository, sample_trigger):
        """Test getting recent executions within specified hours."""
        # Arrange
        recent_time = datetime.utcnow() - timedelta(hours=1)
        old_time = datetime.utcnow() - timedelta(hours=25)  # Older than 24 hours

        recent_execution = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            executed_at=recent_time,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )
        old_execution = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            executed_at=old_time,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )

        await execution_repository.create(recent_execution)
        await execution_repository.create(old_execution)

        # Act
        recent_executions = await execution_repository.get_recent_executions(
            sample_trigger.id, hours=24
        )

        # Assert
        assert len(recent_executions) == 1
        assert recent_executions[0].id == recent_execution.id

    async def test_count_executions_in_period(self, execution_repository, sample_trigger):
        """Test counting executions in a specific time period."""
        # Arrange
        start_time = datetime.utcnow() - timedelta(hours=2)
        end_time = datetime.utcnow()

        # Create executions at different times
        execution1 = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            executed_at=start_time + timedelta(minutes=30),  # Within period
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )
        execution2 = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_trigger.id,
            executed_at=start_time - timedelta(minutes=30),  # Before period
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1000,
        )

        await execution_repository.create(execution1)
        await execution_repository.create(execution2)

        # Act
        count = await execution_repository.count_executions_in_period(
            sample_trigger.id, start_time, end_time
        )

        # Assert
        assert count == 1

    async def test_update_execution(self, execution_repository, sample_execution):
        """Test updating an execution."""
        # Arrange
        await execution_repository.create(sample_execution)
        sample_execution.status = ExecutionStatus.FAILED
        sample_execution.error_message = "Updated error message"

        # Act
        updated_execution = await execution_repository.update(sample_execution)

        # Assert
        assert updated_execution.status == ExecutionStatus.FAILED
        assert updated_execution.error_message == "Updated error message"

        # Verify in database
        retrieved_execution = await execution_repository.get(sample_execution.id)
        assert retrieved_execution.status == ExecutionStatus.FAILED

    async def test_delete_execution(self, execution_repository, sample_execution):
        """Test deleting an execution."""
        # Arrange
        await execution_repository.create(sample_execution)

        # Act
        deleted = await execution_repository.delete(sample_execution.id)

        # Assert
        assert deleted is True

        # Verify deletion
        retrieved_execution = await execution_repository.get(sample_execution.id)
        assert retrieved_execution is None
