"""Tests for trigger domain models."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import (
    ExecutionStatus,
    TriggerType,
    WebhookType,
)
from agentarea_triggers.domain.models import (
    CronTrigger,
    Trigger,
    TriggerCreate,
    TriggerExecution,
    TriggerUpdate,
    WebhookTrigger,
)
from pydantic import ValidationError


class TestTrigger:
    """Test base Trigger model."""

    def test_trigger_creation_with_defaults(self):
        """Test creating a trigger with default values."""
        agent_id = uuid4()
        trigger = Trigger(
            name="Test Trigger",
            agent_id=agent_id,
            trigger_type=TriggerType.CRON,
            created_by="test_user",
        )

        assert trigger.name == "Test Trigger"
        assert trigger.description == ""
        assert trigger.agent_id == agent_id
        assert trigger.trigger_type == TriggerType.CRON
        assert trigger.is_active is True
        assert trigger.task_parameters == {}
        assert trigger.conditions == {}
        assert isinstance(trigger.created_at, datetime)
        assert isinstance(trigger.updated_at, datetime)
        assert trigger.created_by == "test_user"
        assert trigger.failure_threshold == 5
        assert trigger.consecutive_failures == 0
        assert trigger.last_execution_at is None

    def test_trigger_creation_with_custom_values(self):
        """Test creating a trigger with custom values."""
        agent_id = uuid4()
        trigger_id = uuid4()
        created_at = datetime.utcnow()
        updated_at = created_at + timedelta(minutes=5)
        last_execution = created_at + timedelta(minutes=10)

        trigger = Trigger(
            id=trigger_id,
            name="Custom Trigger",
            description="A custom trigger for testing",
            agent_id=agent_id,
            trigger_type=TriggerType.WEBHOOK,
            is_active=False,
            task_parameters={"param1": "value1"},
            conditions={"condition1": "value1"},
            created_at=created_at,
            updated_at=updated_at,
            created_by="custom_user",
            failure_threshold=10,
            consecutive_failures=3,
            last_execution_at=last_execution,
        )

        assert trigger.id == trigger_id
        assert trigger.name == "Custom Trigger"
        assert trigger.description == "A custom trigger for testing"
        assert trigger.is_active is False
        assert trigger.task_parameters == {"param1": "value1"}
        assert trigger.conditions == {"condition1": "value1"}
        assert trigger.created_at == created_at
        assert trigger.updated_at == updated_at
        assert trigger.failure_threshold == 10
        assert trigger.consecutive_failures == 3
        assert trigger.last_execution_at == last_execution

    def test_trigger_name_validation(self):
        """Test trigger name validation."""
        agent_id = uuid4()

        # Empty name should raise error
        with pytest.raises(ValidationError) as exc_info:
            Trigger(
                name="", agent_id=agent_id, trigger_type=TriggerType.CRON, created_by="test_user"
            )
        assert "String should have at least 1 character" in str(exc_info.value)

        # Whitespace-only name should raise error
        with pytest.raises(ValidationError) as exc_info:
            Trigger(
                name="   ", agent_id=agent_id, trigger_type=TriggerType.CRON, created_by="test_user"
            )
        assert "Trigger name cannot be empty" in str(exc_info.value)

        # Name with whitespace should be trimmed
        trigger = Trigger(
            name="  Test Trigger  ",
            agent_id=agent_id,
            trigger_type=TriggerType.CRON,
            created_by="test_user",
        )
        assert trigger.name == "Test Trigger"

    def test_trigger_datetime_validation(self):
        """Test datetime field validation."""
        agent_id = uuid4()
        created_at = datetime.utcnow()
        updated_at = created_at - timedelta(minutes=5)  # Invalid: before created_at

        with pytest.raises(ValidationError) as exc_info:
            Trigger(
                name="Test Trigger",
                agent_id=agent_id,
                trigger_type=TriggerType.CRON,
                created_by="test_user",
                created_at=created_at,
                updated_at=updated_at,
            )
        assert "updated_at cannot be before created_at" in str(exc_info.value)

    # Rate limiting has been moved to infrastructure layer (ingress/load balancer/API gateway)
    # No application-level rate limiting tests needed

    def test_trigger_failure_threshold(self):
        """Test failure threshold logic."""
        agent_id = uuid4()
        trigger = Trigger(
            name="Test Trigger",
            agent_id=agent_id,
            trigger_type=TriggerType.CRON,
            created_by="test_user",
            failure_threshold=3,
        )

        # No failures - should not disable
        assert not trigger.should_disable_due_to_failures()

        # Below threshold - should not disable
        trigger.consecutive_failures = 2
        assert not trigger.should_disable_due_to_failures()

        # At threshold - should disable
        trigger.consecutive_failures = 3
        assert trigger.should_disable_due_to_failures()

        # Above threshold - should disable
        trigger.consecutive_failures = 5
        assert trigger.should_disable_due_to_failures()

    def test_trigger_execution_recording(self):
        """Test execution success/failure recording."""
        agent_id = uuid4()
        trigger = Trigger(
            name="Test Trigger",
            agent_id=agent_id,
            trigger_type=TriggerType.CRON,
            created_by="test_user",
            consecutive_failures=3,
        )

        # Record success
        original_updated_at = trigger.updated_at
        trigger.record_execution_success()

        assert trigger.consecutive_failures == 0
        assert trigger.last_execution_at is not None
        assert trigger.updated_at > original_updated_at

        # Record failure
        original_updated_at = trigger.updated_at
        trigger.record_execution_failure()

        assert trigger.consecutive_failures == 1
        assert trigger.updated_at > original_updated_at


class TestCronTrigger:
    """Test CronTrigger model."""

    def test_cron_trigger_creation(self):
        """Test creating a cron trigger."""
        agent_id = uuid4()
        trigger = CronTrigger(
            name="Cron Test",
            agent_id=agent_id,
            created_by="test_user",
            cron_expression="0 9 * * *",
            timezone="America/New_York",
        )

        assert trigger.trigger_type == TriggerType.CRON
        assert trigger.cron_expression == "0 9 * * *"
        assert trigger.timezone == "America/New_York"
        assert trigger.next_run_time is None

    def test_cron_expression_validation(self):
        """Test cron expression validation."""
        agent_id = uuid4()

        # Empty expression should raise error
        with pytest.raises(ValidationError) as exc_info:
            CronTrigger(
                name="Cron Test", agent_id=agent_id, created_by="test_user", cron_expression=""
            )
        assert "String should have at least 1 character" in str(exc_info.value)

        # Invalid format (too few parts) should raise error
        with pytest.raises(ValidationError) as exc_info:
            CronTrigger(
                name="Cron Test", agent_id=agent_id, created_by="test_user", cron_expression="0 9 *"
            )
        assert "Cron expression must have 5 or 6 parts" in str(exc_info.value)

        # Valid 5-part expression
        trigger = CronTrigger(
            name="Cron Test", agent_id=agent_id, created_by="test_user", cron_expression="0 9 * * *"
        )
        assert trigger.cron_expression == "0 9 * * *"

        # Valid 6-part expression
        trigger = CronTrigger(
            name="Cron Test",
            agent_id=agent_id,
            created_by="test_user",
            cron_expression="0 0 9 * * *",
        )
        assert trigger.cron_expression == "0 0 9 * * *"

    def test_timezone_validation(self):
        """Test timezone validation."""
        agent_id = uuid4()

        # Empty timezone should raise error
        with pytest.raises(ValidationError) as exc_info:
            CronTrigger(
                name="Cron Test",
                agent_id=agent_id,
                created_by="test_user",
                cron_expression="0 9 * * *",
                timezone="",
            )
        assert "Timezone cannot be empty" in str(exc_info.value)

        # Whitespace timezone should be trimmed
        trigger = CronTrigger(
            name="Cron Test",
            agent_id=agent_id,
            created_by="test_user",
            cron_expression="0 9 * * *",
            timezone="  UTC  ",
        )
        assert trigger.timezone == "UTC"


class TestWebhookTrigger:
    """Test WebhookTrigger model."""

    def test_webhook_trigger_creation(self):
        """Test creating a webhook trigger."""
        agent_id = uuid4()
        trigger = WebhookTrigger(
            name="Webhook Test",
            agent_id=agent_id,
            created_by="test_user",
            webhook_id="webhook_123",
            allowed_methods=["POST", "PUT"],
            webhook_type=WebhookType.TELEGRAM,
        )

        assert trigger.trigger_type == TriggerType.WEBHOOK
        assert trigger.webhook_id == "webhook_123"
        assert trigger.allowed_methods == ["POST", "PUT"]
        assert trigger.webhook_type == WebhookType.TELEGRAM
        assert trigger.validation_rules == {}

    def test_webhook_id_validation(self):
        """Test webhook ID validation."""
        agent_id = uuid4()

        # Empty webhook_id should raise error
        with pytest.raises(ValidationError) as exc_info:
            WebhookTrigger(
                name="Webhook Test", agent_id=agent_id, created_by="test_user", webhook_id=""
            )
        assert "String should have at least 1 character" in str(exc_info.value)

        # Whitespace webhook_id should be trimmed
        trigger = WebhookTrigger(
            name="Webhook Test",
            agent_id=agent_id,
            created_by="test_user",
            webhook_id="  webhook_123  ",
        )
        assert trigger.webhook_id == "webhook_123"

    def test_allowed_methods_validation(self):
        """Test allowed methods validation."""
        agent_id = uuid4()

        # Empty methods list should raise error
        with pytest.raises(ValidationError) as exc_info:
            WebhookTrigger(
                name="Webhook Test",
                agent_id=agent_id,
                created_by="test_user",
                webhook_id="webhook_123",
                allowed_methods=[],
            )
        assert "At least one HTTP method must be allowed" in str(exc_info.value)

        # Invalid method should raise error
        with pytest.raises(ValidationError) as exc_info:
            WebhookTrigger(
                name="Webhook Test",
                agent_id=agent_id,
                created_by="test_user",
                webhook_id="webhook_123",
                allowed_methods=["INVALID"],
            )
        assert "Invalid HTTP method: INVALID" in str(exc_info.value)

        # Methods should be converted to uppercase
        trigger = WebhookTrigger(
            name="Webhook Test",
            agent_id=agent_id,
            created_by="test_user",
            webhook_id="webhook_123",
            allowed_methods=["post", "get"],
        )
        assert trigger.allowed_methods == ["POST", "GET"]


class TestTriggerExecution:
    """Test TriggerExecution model."""

    def test_trigger_execution_creation(self):
        """Test creating a trigger execution record."""
        trigger_id = uuid4()
        task_id = uuid4()
        execution = TriggerExecution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SUCCESS,
            task_id=task_id,
            execution_time_ms=1500,
            trigger_data={"key": "value"},
            workflow_id="workflow_123",
            run_id="run_456",
        )

        assert execution.trigger_id == trigger_id
        assert execution.status == ExecutionStatus.SUCCESS
        assert execution.task_id == task_id
        assert execution.execution_time_ms == 1500
        assert execution.error_message is None
        assert execution.trigger_data == {"key": "value"}
        assert execution.workflow_id == "workflow_123"
        assert execution.run_id == "run_456"
        assert isinstance(execution.executed_at, datetime)

    def test_execution_time_validation(self):
        """Test execution time validation."""
        trigger_id = uuid4()

        # Negative execution time should raise error
        with pytest.raises(ValidationError) as exc_info:
            TriggerExecution(
                trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=-100
            )
        assert "Input should be greater than or equal to 0" in str(exc_info.value)

        # Zero execution time should be valid
        execution = TriggerExecution(
            trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=0
        )
        assert execution.execution_time_ms == 0

    def test_execution_status_methods(self):
        """Test execution status helper methods."""
        trigger_id = uuid4()

        # Successful execution
        execution = TriggerExecution(
            trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=1000
        )
        assert execution.is_successful()
        assert not execution.has_error()

        # Failed execution
        execution = TriggerExecution(
            trigger_id=trigger_id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=500,
            error_message="Test error",
        )
        assert not execution.is_successful()
        assert execution.has_error()

        # Timeout execution
        execution = TriggerExecution(
            trigger_id=trigger_id, status=ExecutionStatus.TIMEOUT, execution_time_ms=30000
        )
        assert not execution.is_successful()
        assert execution.has_error()


class TestTriggerCreate:
    """Test TriggerCreate model."""

    def test_cron_trigger_create(self):
        """Test creating a cron trigger creation model."""
        agent_id = uuid4()
        create_model = TriggerCreate(
            name="Test Cron",
            agent_id=agent_id,
            trigger_type=TriggerType.CRON,
            created_by="test_user",
            cron_expression="0 9 * * *",
            timezone="UTC",
        )

        assert create_model.name == "Test Cron"
        assert create_model.trigger_type == TriggerType.CRON
        assert create_model.cron_expression == "0 9 * * *"
        assert create_model.timezone == "UTC"

    def test_webhook_trigger_create(self):
        """Test creating a webhook trigger creation model."""
        agent_id = uuid4()
        create_model = TriggerCreate(
            name="Test Webhook",
            agent_id=agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
            webhook_id="webhook_123",
            webhook_type=WebhookType.SLACK,
        )

        assert create_model.name == "Test Webhook"
        assert create_model.trigger_type == TriggerType.WEBHOOK
        assert create_model.webhook_id == "webhook_123"
        assert create_model.webhook_type == WebhookType.SLACK

    def test_trigger_create_validation(self):
        """Test trigger creation validation."""
        agent_id = uuid4()

        # Cron trigger without cron_expression should raise error
        with pytest.raises(ValidationError) as exc_info:
            TriggerCreate(
                name="Test Cron",
                agent_id=agent_id,
                trigger_type=TriggerType.CRON,
                created_by="test_user",
            )
        assert "cron_expression is required for CRON triggers" in str(exc_info.value)

        # Webhook trigger without webhook_id should raise error
        with pytest.raises(ValidationError) as exc_info:
            TriggerCreate(
                name="Test Webhook",
                agent_id=agent_id,
                trigger_type=TriggerType.WEBHOOK,
                created_by="test_user",
            )
        assert "webhook_id is required for WEBHOOK triggers" in str(exc_info.value)


class TestTriggerUpdate:
    """Test TriggerUpdate model."""

    def test_trigger_update_creation(self):
        """Test creating a trigger update model."""
        update_model = TriggerUpdate(
            name="Updated Name", description="Updated description", is_active=False
        )

        assert update_model.name == "Updated Name"
        assert update_model.description == "Updated description"
        assert update_model.is_active is False

    def test_trigger_update_optional_fields(self):
        """Test that all fields in TriggerUpdate are optional."""
        update_model = TriggerUpdate()

        assert update_model.name is None
        assert update_model.description is None
        assert update_model.is_active is None
        assert update_model.task_parameters is None
        assert update_model.conditions is None
