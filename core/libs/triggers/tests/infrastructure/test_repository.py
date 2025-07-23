"""Tests for trigger repository implementations."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_triggers.domain.models import (
    Trigger,
    CronTrigger,
    WebhookTrigger,
    TriggerExecution,
    TriggerCreate,
    TriggerUpdate,
)
from agentarea_triggers.domain.enums import (
    TriggerType,
    ExecutionStatus,
    WebhookType,
)
from agentarea_triggers.infrastructure.repository import (
    TriggerRepository,
    TriggerExecutionRepository,
)
from agentarea_triggers.infrastructure.orm import TriggerORM, TriggerExecutionORM


class TestTriggerRepository:
    """Test TriggerRepository implementation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock AsyncSession."""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def repository(self, mock_session):
        """Create a TriggerRepository instance with mock session."""
        return TriggerRepository(mock_session)

    @pytest.fixture
    def sample_trigger_orm(self):
        """Create a sample TriggerORM for testing."""
        return TriggerORM(
            id=uuid4(),
            name="Test Trigger",
            description="Test description",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON.value,
            is_active=True,
            task_parameters={"param1": "value1"},
            conditions={"condition1": "value1"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            max_executions_per_hour=60,
            failure_threshold=5,
            consecutive_failures=0,
            last_execution_at=None,
            cron_expression="0 9 * * *",
            timezone="UTC",
            next_run_time=None,
        )

    @pytest.fixture
    def sample_trigger(self):
        """Create a sample CronTrigger domain model."""
        return CronTrigger(
            id=uuid4(),
            name="Test Trigger",
            description="Test description",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            is_active=True,
            task_parameters={"param1": "value1"},
            conditions={"condition1": "value1"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            max_executions_per_hour=60,
            failure_threshold=5,
            consecutive_failures=0,
            last_execution_at=None,
            cron_expression="0 9 * * *",
            timezone="UTC",
            next_run_time=None,
        )

    @pytest.mark.asyncio
    async def test_get_existing_trigger(self, repository, mock_session, sample_trigger_orm):
        """Test getting an existing trigger by ID."""
        # Setup mock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_trigger_orm
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.get(sample_trigger_orm.id)

        # Verify
        assert result is not None
        assert result.id == sample_trigger_orm.id
        assert result.name == sample_trigger_orm.name
        assert result.trigger_type == TriggerType.CRON
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_nonexistent_trigger(self, repository, mock_session):
        """Test getting a non-existent trigger returns None."""
        # Setup mock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.get(uuid4())

        # Verify
        assert result is None
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_trigger(self, repository, mock_session, sample_trigger):
        """Test creating a new trigger."""
        # Setup mock
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Execute
        result = await repository.create(sample_trigger)

        # Verify
        assert result.id == sample_trigger.id
        assert result.name == sample_trigger.name
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_agent(self, repository, mock_session, sample_trigger_orm):
        """Test listing triggers by agent ID."""
        # Setup
        agent_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_trigger_orm]
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.list_by_agent(agent_id, limit=50)

        # Verify
        assert len(result) == 1
        assert result[0].id == sample_trigger_orm.id
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_type(self, repository, mock_session, sample_trigger_orm):
        """Test listing triggers by type."""
        # Setup
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_trigger_orm]
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.list_by_type(TriggerType.CRON, limit=50)

        # Verify
        assert len(result) == 1
        assert result[0].trigger_type == TriggerType.CRON
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_webhook_id(self, repository, mock_session):
        """Test getting trigger by webhook ID."""
        # Setup webhook trigger ORM
        webhook_orm = TriggerORM(
            id=uuid4(),
            name="Webhook Test",
            description="Webhook description",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={"param1": "value1"},
            conditions={"condition1": "value1"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            max_executions_per_hour=60,
            failure_threshold=5,
            consecutive_failures=0,
            last_execution_at=None,
            webhook_id="webhook_123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.TELEGRAM.value,
            validation_rules={"rule1": "value1"},
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = webhook_orm
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.get_by_webhook_id("webhook_123")

        # Verify
        assert result is not None
        assert isinstance(result, WebhookTrigger)
        assert result.webhook_id == "webhook_123"
        mock_session.execute.assert_called_once()

    def test_orm_to_domain_cron_trigger(self, repository, sample_trigger_orm):
        """Test converting CronTrigger ORM to domain model."""
        # Execute
        result = repository._orm_to_domain(sample_trigger_orm)

        # Verify
        assert isinstance(result, CronTrigger)
        assert result.id == sample_trigger_orm.id
        assert result.name == sample_trigger_orm.name
        assert result.trigger_type == TriggerType.CRON
        assert result.cron_expression == sample_trigger_orm.cron_expression
        assert result.timezone == sample_trigger_orm.timezone


class TestTriggerExecutionRepository:
    """Test TriggerExecutionRepository implementation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock AsyncSession."""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def repository(self, mock_session):
        """Create a TriggerExecutionRepository instance with mock session."""
        return TriggerExecutionRepository(mock_session)

    @pytest.fixture
    def sample_execution_orm(self):
        """Create a sample TriggerExecutionORM for testing."""
        return TriggerExecutionORM(
            id=uuid4(),
            trigger_id=uuid4(),
            executed_at=datetime.utcnow(),
            status=ExecutionStatus.SUCCESS.value,
            task_id=uuid4(),
            execution_time_ms=1500,
            error_message=None,
            trigger_data={"key": "value"},
            workflow_id="workflow_123",
            run_id="run_456",
        )

    @pytest.fixture
    def sample_execution(self):
        """Create a sample TriggerExecution domain model."""
        return TriggerExecution(
            id=uuid4(),
            trigger_id=uuid4(),
            executed_at=datetime.utcnow(),
            status=ExecutionStatus.SUCCESS,
            task_id=uuid4(),
            execution_time_ms=1500,
            error_message=None,
            trigger_data={"key": "value"},
            workflow_id="workflow_123",
            run_id="run_456",
        )

    @pytest.mark.asyncio
    async def test_get_existing_execution(self, repository, mock_session, sample_execution_orm):
        """Test getting an existing execution by ID."""
        # Setup mock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_execution_orm
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.get(sample_execution_orm.id)

        # Verify
        assert result is not None
        assert result.id == sample_execution_orm.id
        assert result.status == ExecutionStatus.SUCCESS
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_execution(self, repository, mock_session, sample_execution):
        """Test creating a new execution."""
        # Setup mock
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Execute
        result = await repository.create(sample_execution)

        # Verify
        assert result.id == sample_execution.id
        assert result.status == sample_execution.status
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_trigger(self, repository, mock_session, sample_execution_orm):
        """Test listing executions by trigger ID."""
        # Setup
        trigger_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_execution_orm]
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.list_by_trigger(trigger_id, limit=50, offset=10)

        # Verify
        assert len(result) == 1
        assert result[0].id == sample_execution_orm.id
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_executions_in_period(self, repository, mock_session):
        """Test counting executions in a specific time period."""
        # Setup
        trigger_id = uuid4()
        start_time = datetime.utcnow() - timedelta(hours=1)
        end_time = datetime.utcnow()
        
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.count_executions_in_period(trigger_id, start_time, end_time)

        # Verify
        assert result == 5
        mock_session.execute.assert_called_once()

    def test_orm_to_domain_execution(self, repository, sample_execution_orm):
        """Test converting TriggerExecutionORM to domain model."""
        # Execute
        result = repository._orm_to_domain(sample_execution_orm)

        # Verify
        assert isinstance(result, TriggerExecution)
        assert result.id == sample_execution_orm.id
        assert result.trigger_id == sample_execution_orm.trigger_id
        assert result.status == ExecutionStatus.SUCCESS
        assert result.execution_time_ms == sample_execution_orm.execution_time_ms