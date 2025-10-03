"""Integration tests for trigger service with LLM condition evaluation."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import CronTrigger, TriggerCreate, WebhookTrigger
from agentarea_triggers.trigger_service import TriggerService


@pytest.fixture
def mock_trigger_repository():
    """Mock trigger repository."""
    return AsyncMock()


@pytest.fixture
def mock_trigger_execution_repository():
    """Mock trigger execution repository."""
    return AsyncMock()


@pytest.fixture
def mock_event_broker():
    """Mock event broker."""
    return AsyncMock()


@pytest.fixture
def mock_agent_repository():
    """Mock agent repository."""
    repo = AsyncMock()
    # Mock agent exists
    mock_agent = MagicMock()
    mock_agent.id = uuid4()
    repo.get.return_value = mock_agent
    return repo


@pytest.fixture
def mock_task_service():
    """Mock task service."""
    service = AsyncMock()
    mock_task = MagicMock()
    mock_task.id = uuid4()
    service.create_task_from_params.return_value = mock_task
    return service


@pytest.fixture
def mock_llm_condition_evaluator():
    """Mock LLM condition evaluator."""
    evaluator = AsyncMock()
    evaluator.evaluate_condition.return_value = True
    evaluator.validate_condition_syntax.return_value = []
    evaluator.extract_task_parameters.return_value = {"extracted": "parameters"}
    return evaluator


@pytest.fixture
def trigger_service(
    mock_trigger_repository,
    mock_trigger_execution_repository,
    mock_event_broker,
    mock_agent_repository,
    mock_task_service,
    mock_llm_condition_evaluator,
):
    """Create trigger service with mocked dependencies."""
    return TriggerService(
        trigger_repository=mock_trigger_repository,
        trigger_execution_repository=mock_trigger_execution_repository,
        event_broker=mock_event_broker,
        agent_repository=mock_agent_repository,
        task_service=mock_task_service,
        llm_condition_evaluator=mock_llm_condition_evaluator,
    )


class TestTriggerServiceLLMIntegration:
    """Test cases for trigger service LLM integration."""

    @pytest.mark.asyncio
    async def test_create_trigger_with_llm_condition(
        self, trigger_service, mock_trigger_repository
    ):
        """Test creating a trigger with LLM-based condition."""
        agent_id = uuid4()

        trigger_data = TriggerCreate(
            name="File Upload Trigger",
            description="Trigger when user uploads a file",
            agent_id=agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="webhook_123",
            conditions={
                "type": "llm",
                "description": "when user sends a file attachment or document",
                "context_fields": ["request.body", "request.headers"],
            },
            task_parameters={
                "llm_parameter_extraction": "analyze the uploaded file and respond with insights"
            },
            created_by="test_user",
        )

        # Mock repository response
        created_trigger = WebhookTrigger(
            id=uuid4(),
            name=trigger_data.name,
            description=trigger_data.description,
            agent_id=agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="webhook_123",
            conditions=trigger_data.conditions,
            task_parameters=trigger_data.task_parameters,
            created_by="test_user",
        )
        mock_trigger_repository.create_from_data.return_value = created_trigger

        result = await trigger_service.create_trigger(trigger_data)

        assert result.id == created_trigger.id
        assert result.conditions["type"] == "llm"
        assert "llm_parameter_extraction" in result.task_parameters

        # Verify repository was called
        mock_trigger_repository.create_from_data.assert_called_once_with(trigger_data)

    @pytest.mark.asyncio
    async def test_evaluate_trigger_conditions_with_llm(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test trigger condition evaluation using LLM."""
        trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            conditions={
                "type": "llm",
                "description": "when user sends a file attachment",
                "context_fields": ["request.body"],
            },
            created_by="test_user",
        )

        event_data = {
            "request": {
                "body": {"document": {"file_name": "report.pdf"}, "message": "Here's the report"}
            }
        }

        # Mock LLM evaluator to return True
        mock_llm_condition_evaluator.evaluate_condition.return_value = True

        result = await trigger_service.evaluate_trigger_conditions(trigger, event_data)

        assert result is True

        # Verify LLM evaluator was called with correct parameters
        mock_llm_condition_evaluator.evaluate_condition.assert_called_once()
        call_args = mock_llm_condition_evaluator.evaluate_condition.call_args
        assert call_args[1]["condition"] == trigger.conditions
        assert call_args[1]["event_data"] == event_data
        assert "trigger_id" in call_args[1]["trigger_context"]

    @pytest.mark.asyncio
    async def test_evaluate_trigger_conditions_llm_failure_fallback(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test fallback to simple evaluation when LLM fails."""
        trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            conditions={"field_matches": {"request.method": "POST"}},
            created_by="test_user",
        )

        event_data = {"request": {"method": "POST", "body": {"message": "test"}}}

        # Mock LLM evaluator to raise an exception
        from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluationError

        mock_llm_condition_evaluator.evaluate_condition.side_effect = LLMConditionEvaluationError(
            "LLM failed"
        )

        result = await trigger_service.evaluate_trigger_conditions(trigger, event_data)

        # Should fallback to simple evaluation and return True (field matches)
        assert result is True

    @pytest.mark.asyncio
    async def test_build_task_parameters_with_llm_extraction(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test task parameter building with LLM extraction."""
        trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            task_parameters={
                "base_param": "base_value",
                "llm_parameter_extraction": "extract user information and file details",
            },
            created_by="test_user",
        )

        trigger_data = {
            "request": {
                "body": {
                    "user": {"id": "123", "name": "John"},
                    "document": {"file_name": "report.pdf"},
                }
            }
        }

        # Mock LLM parameter extraction
        mock_llm_condition_evaluator.extract_task_parameters.return_value = {
            "user_id": "123",
            "user_name": "John",
            "file_name": "report.pdf",
            "action": "process_document",
        }

        result = await trigger_service._build_task_parameters(trigger, trigger_data)

        # Should include base parameters, trigger metadata, and LLM-extracted parameters
        assert result["base_param"] == "base_value"
        assert result["trigger_id"] == str(trigger.id)
        assert result["trigger_type"] == "webhook"
        assert result["user_id"] == "123"
        assert result["user_name"] == "John"
        assert result["file_name"] == "report.pdf"
        assert result["action"] == "process_document"

        # Verify LLM extraction was called
        trigger_service.llm_condition_evaluator.extract_task_parameters.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_trigger_with_llm_conditions(
        self, trigger_service, mock_llm_condition_evaluator, mock_task_service
    ):
        """Test trigger execution with LLM condition evaluation."""
        trigger_id = uuid4()
        trigger = WebhookTrigger(
            id=trigger_id,
            name="File Processing Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            conditions={"type": "llm", "description": "when user uploads a document for analysis"},
            task_parameters={"llm_parameter_extraction": "extract file details and user intent"},
            created_by="test_user",
        )

        trigger_data = {
            "request": {
                "body": {
                    "document": {"file_name": "analysis.pdf"},
                    "message": "Please analyze this document",
                }
            }
        }

        # Mock repository to return the trigger
        trigger_service.trigger_repository.get.return_value = trigger

        # Mock condition evaluation to return True
        mock_llm_condition_evaluator.evaluate_condition.return_value = True

        # Mock parameter extraction
        mock_llm_condition_evaluator.extract_task_parameters.return_value = {
            "file_name": "analysis.pdf",
            "user_intent": "document_analysis",
        }

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task_service.create_task_from_params.return_value = mock_task

        # Mock execution recording
        trigger_service.trigger_execution_repository.create.return_value = MagicMock()
        trigger_service.trigger_repository.update_execution_tracking.return_value = None

        result = await trigger_service.execute_trigger(trigger_id, trigger_data)

        # Verify condition was evaluated
        mock_llm_condition_evaluator.evaluate_condition.assert_called_once()

        # Verify task was created with enhanced parameters
        mock_task_service.create_task_from_params.assert_called_once()
        task_params = mock_task_service.create_task_from_params.call_args[1]["task_parameters"]
        assert "file_name" in task_params
        assert "user_intent" in task_params
        assert task_params["trigger_id"] == str(trigger_id)

    @pytest.mark.asyncio
    async def test_execute_trigger_conditions_not_met(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test trigger execution when conditions are not met."""
        trigger_id = uuid4()
        trigger = WebhookTrigger(
            id=trigger_id,
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            conditions={"type": "llm", "description": "when user sends a file attachment"},
            created_by="test_user",
        )

        trigger_data = {"request": {"body": {"message": "Hello, how are you?"}}}

        # Mock repository to return the trigger
        trigger_service.trigger_repository.get.return_value = trigger

        # Mock condition evaluation to return False
        mock_llm_condition_evaluator.evaluate_condition.return_value = False

        # Mock execution recording
        trigger_service.trigger_execution_repository.create.return_value = MagicMock()

        result = await trigger_service.execute_trigger(trigger_id, trigger_data)

        # Should record failed execution due to conditions not met
        assert result is not None

        # Verify condition was evaluated
        mock_llm_condition_evaluator.evaluate_condition.assert_called_once()

        # Verify task was NOT created
        trigger_service.task_service.create_task_from_params.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_condition_syntax(self, trigger_service, mock_llm_condition_evaluator):
        """Test condition syntax validation."""
        conditions = {
            "type": "llm",
            "description": "when user sends a file",
            "context_fields": ["request.body"],
        }

        # Mock validation to return no errors
        mock_llm_condition_evaluator.validate_condition_syntax.return_value = []

        errors = await trigger_service.validate_condition_syntax(conditions)

        assert len(errors) == 0
        mock_llm_condition_evaluator.validate_condition_syntax.assert_called_once_with(conditions)

    @pytest.mark.asyncio
    async def test_validate_condition_syntax_with_errors(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test condition syntax validation with errors."""
        conditions = {
            "type": "llm"
            # Missing required description
        }

        # Mock validation to return errors
        mock_llm_condition_evaluator.validate_condition_syntax.return_value = [
            "LLM condition must have a 'description'"
        ]

        errors = await trigger_service.validate_condition_syntax(conditions)

        assert len(errors) == 1
        assert "must have a 'description'" in errors[0]

    @pytest.mark.asyncio
    async def test_cron_trigger_with_time_conditions(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test cron trigger with time-based conditions."""
        trigger = CronTrigger(
            id=uuid4(),
            name="Business Hours Trigger",
            agent_id=uuid4(),
            cron_expression="0 9 * * 1-5",  # 9 AM on weekdays
            conditions={
                "type": "combined",
                "conditions": [
                    {
                        "type": "rule",
                        "rules": [{"field": "time_conditions.hour_range", "operator": "exists"}],
                    },
                    {"type": "llm", "description": "during business hours on weekdays"},
                ],
                "logic": "AND",
            },
            created_by="test_user",
        )

        # Mock current time to be during business hours
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 15, 10, 0, 0)  # Monday 10 AM
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            # Mock LLM evaluation
            mock_llm_condition_evaluator.evaluate_condition.return_value = True

            event_data = {"execution_time": "2024-01-15T10:00:00Z"}

            result = await trigger_service.evaluate_trigger_conditions(trigger, event_data)

            assert result is True

    @pytest.mark.asyncio
    async def test_extract_task_parameters_with_llm_failure(
        self, trigger_service, mock_llm_condition_evaluator
    ):
        """Test task parameter extraction with LLM failure."""
        trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            task_parameters={"llm_parameter_extraction": "extract parameters"},
            created_by="test_user",
        )

        trigger_data = {"test": "data"}

        # Mock LLM extraction to fail
        from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluationError

        mock_llm_condition_evaluator.extract_task_parameters.side_effect = (
            LLMConditionEvaluationError("Extraction failed")
        )

        result = await trigger_service._build_task_parameters(trigger, trigger_data)

        # Should include basic parameters and trigger metadata
        assert result["trigger_id"] == str(trigger.id)
        assert result["trigger_data"] == trigger_data

        # Should not include LLM-extracted parameters due to failure
        assert "extracted" not in result

    @pytest.mark.asyncio
    async def test_trigger_service_without_llm_evaluator(self):
        """Test trigger service functionality without LLM evaluator."""
        # Create service without LLM evaluator
        service = TriggerService(
            trigger_repository=AsyncMock(),
            trigger_execution_repository=AsyncMock(),
            event_broker=AsyncMock(),
            agent_repository=AsyncMock(),
            task_service=AsyncMock(),
            llm_condition_evaluator=None,  # No LLM evaluator
        )

        trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Trigger",
            agent_id=uuid4(),
            webhook_id="webhook_123",
            conditions={"field_matches": {"request.method": "POST"}},
            created_by="test_user",
        )

        event_data = {"request": {"method": "POST"}}

        # Should fallback to simple evaluation
        result = await service.evaluate_trigger_conditions(trigger, event_data)
        assert result is True
