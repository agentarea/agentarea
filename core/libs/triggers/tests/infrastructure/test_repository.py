"""Tests for trigger repository implementations."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import (
    ExecutionStatus,
    TriggerType,
    WebhookType,
)
from agentarea_triggers.domain.models import (
    CronTrigger,
    TriggerExecution,
    WebhookTrigger,
)
from agentarea_triggers.infrastructure.orm import TriggerExecutionORM, TriggerORM
from agentarea_triggers.infrastructure.repository import (
    TriggerExecutionRepository,
    TriggerRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession


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


class TestTriggerExecutionRepositoryEnhancements:
    """Test enhanced TriggerExecutionRepository methods for monitoring."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock AsyncSession."""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def repository(self, mock_session):
        """Create a TriggerExecutionRepository instance with mock session."""
        return TriggerExecutionRepository(mock_session)

    @pytest.fixture
    def sample_executions_orm(self):
        """Create sample TriggerExecutionORM instances for testing."""
        trigger_id = uuid4()
        base_time = datetime.utcnow()

        return [
            TriggerExecutionORM(
                id=uuid4(),
                trigger_id=trigger_id,
                executed_at=base_time - timedelta(minutes=30),
                status=ExecutionStatus.SUCCESS.value,
                task_id=uuid4(),
                execution_time_ms=1200,
                error_message=None,
                trigger_data={"key": "value1"},
                workflow_id="workflow_1",
                run_id="run_1",
            ),
            TriggerExecutionORM(
                id=uuid4(),
                trigger_id=trigger_id,
                executed_at=base_time - timedelta(minutes=20),
                status=ExecutionStatus.FAILED.value,
                task_id=None,
                execution_time_ms=800,
                error_message="Test error",
                trigger_data={"key": "value2"},
                workflow_id="workflow_2",
                run_id="run_2",
            ),
            TriggerExecutionORM(
                id=uuid4(),
                trigger_id=trigger_id,
                executed_at=base_time - timedelta(minutes=10),
                status=ExecutionStatus.SUCCESS.value,
                task_id=uuid4(),
                execution_time_ms=1500,
                error_message=None,
                trigger_data={"key": "value3"},
                workflow_id="workflow_3",
                run_id="run_3",
            ),
        ]

    @pytest.mark.asyncio
    async def test_list_executions_paginated(self, repository, mock_session, sample_executions_orm):
        """Test paginated execution listing with filtering."""
        # Setup
        trigger_id = sample_executions_orm[0].trigger_id
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sample_executions_orm[:2]
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.list_executions_paginated(
            trigger_id=trigger_id, status=None, limit=2, offset=0
        )

        # Verify
        assert len(result) == 2
        assert all(isinstance(exec, TriggerExecution) for exec in result)
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_executions_paginated_with_status_filter(
        self, repository, mock_session, sample_executions_orm
    ):
        """Test paginated execution listing with status filtering."""
        # Setup - only return successful executions
        successful_executions = [
            exec for exec in sample_executions_orm if exec.status == ExecutionStatus.SUCCESS.value
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = successful_executions
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.list_executions_paginated(
            trigger_id=sample_executions_orm[0].trigger_id,
            status=ExecutionStatus.SUCCESS,
            limit=10,
            offset=0,
        )

        # Verify
        assert len(result) == 2  # Only successful executions
        assert all(exec.status == ExecutionStatus.SUCCESS for exec in result)
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_executions_filtered(self, repository, mock_session):
        """Test counting executions with filtering."""
        # Setup
        trigger_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.count_executions_filtered(
            trigger_id=trigger_id, status=ExecutionStatus.SUCCESS
        )

        # Verify
        assert result == 3
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_execution_metrics(self, repository, mock_session):
        """Test getting execution metrics."""
        # Setup mock result for metrics query
        mock_row = MagicMock()
        mock_row.total_executions = 10
        mock_row.successful_executions = 8
        mock_row.failed_executions = 1
        mock_row.timeout_executions = 1
        mock_row.avg_execution_time_ms = 1250.5
        mock_row.min_execution_time_ms = 800
        mock_row.max_execution_time_ms = 2000

        mock_result = MagicMock()
        mock_result.first.return_value = mock_row
        mock_session.execute.return_value = mock_result

        # Execute
        trigger_id = uuid4()
        result = await repository.get_execution_metrics(trigger_id, hours=24)

        # Verify
        assert result["total_executions"] == 10
        assert result["successful_executions"] == 8
        assert result["failed_executions"] == 1
        assert result["timeout_executions"] == 1
        assert result["success_rate"] == 80.0
        assert result["failure_rate"] == 20.0
        assert result["avg_execution_time_ms"] == 1250.5
        assert result["min_execution_time_ms"] == 800
        assert result["max_execution_time_ms"] == 2000
        assert result["period_hours"] == 24
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_execution_metrics_no_data(self, repository, mock_session):
        """Test getting execution metrics when no data exists."""
        # Setup mock result for no data
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.execute.return_value = mock_result

        # Execute
        trigger_id = uuid4()
        result = await repository.get_execution_metrics(trigger_id, hours=24)

        # Verify default values
        assert result["total_executions"] == 0
        assert result["successful_executions"] == 0
        assert result["failed_executions"] == 0
        assert result["timeout_executions"] == 0
        assert result["success_rate"] == 0.0
        assert result["failure_rate"] == 0.0
        assert result["avg_execution_time_ms"] == 0.0
        assert result["min_execution_time_ms"] == 0
        assert result["max_execution_time_ms"] == 0
        assert result["period_hours"] == 24
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_executions_with_task_correlation(
        self, repository, mock_session, sample_executions_orm
    ):
        """Test getting executions with task correlation information."""
        # Setup
        trigger_id = sample_executions_orm[0].trigger_id
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sample_executions_orm
        mock_session.execute.return_value = mock_result

        # Execute
        result = await repository.get_executions_with_task_correlation(
            trigger_id, limit=10, offset=0
        )

        # Verify
        assert len(result) == 3
        assert all("has_task_correlation" in exec for exec in result)
        assert all("has_workflow_correlation" in exec for exec in result)

        # Check correlation flags
        assert result[0]["has_task_correlation"] is True  # Has task_id
        assert result[1]["has_task_correlation"] is False  # No task_id (failed execution)
        assert result[2]["has_task_correlation"] is True  # Has task_id

        assert all(
            exec["has_workflow_correlation"] is True for exec in result
        )  # All have workflow_id

    @pytest.mark.asyncio
    async def test_get_execution_timeline(self, repository, mock_session):
        """Test getting execution timeline with bucketed data."""
        # Setup mock timeline data
        mock_rows = [
            MagicMock(
                time_bucket=datetime.utcnow() - timedelta(hours=2),
                total_count=5,
                success_count=4,
                failed_count=1,
                timeout_count=0,
            ),
            MagicMock(
                time_bucket=datetime.utcnow() - timedelta(hours=1),
                total_count=3,
                success_count=2,
                failed_count=0,
                timeout_count=1,
            ),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        # Execute
        trigger_id = uuid4()
        result = await repository.get_execution_timeline(
            trigger_id, hours=24, bucket_size_minutes=60
        )

        # Verify
        assert len(result) == 2
        assert result[0]["total_count"] == 5
        assert result[0]["success_count"] == 4
        assert result[0]["failed_count"] == 1
        assert result[0]["timeout_count"] == 0
        assert result[0]["success_rate"] == 80.0

        assert result[1]["total_count"] == 3
        assert result[1]["success_count"] == 2
        assert result[1]["failed_count"] == 0
        assert result[1]["timeout_count"] == 1
        assert abs(result[1]["success_rate"] - 66.67) < 0.01  # Approximately 66.67%

        mock_session.execute.assert_called_once()
