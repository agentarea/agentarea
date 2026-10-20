"""Tests for LLM condition evaluator."""

import json
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from litellm import ModelResponse
from agentarea_common.auth.context import UserContext
from agentarea_llm.infrastructure.model_clients import ModelEndpoint, ModelTarget
from agentarea_triggers.llm_condition_evaluator import (
    LLMConditionEvaluationError,
    LLMConditionEvaluator,
)


@pytest.fixture
def mock_model_instance_service():
    """Mock model instance service."""
    service = AsyncMock()

    # Mock model instance
    mock_instance = MagicMock()
    mock_instance.provider_config.provider_spec.provider_type = "openai"
    mock_instance.model_spec.model_name = "gpt-4"
    mock_instance.provider_config.api_key = "test-api-key"
    mock_instance.model_spec.endpoint_url = None
    mock_instance.model_spec.kind = "chat"

    service.get.return_value = mock_instance
    return service


@pytest.fixture
def mock_secret_manager():
    """Mock secret manager."""
    return AsyncMock()


def _response(content: str) -> ModelResponse:
    return ModelResponse(choices=[{"message": {"role": "assistant", "content": content}}])


def _target(endpoint_url: str | None = None, managed_by: str | None = None) -> ModelTarget:
    return ModelTarget(
        instance_id=str(uuid4()),
        provider_type="openai",
        model_name="gpt-4",
        endpoint_url=endpoint_url,
        managed_by=managed_by,
        input_cost_per_token=None,
        output_cost_per_token=None,
    )


async def _connect(target: ModelTarget, funding) -> ModelEndpoint:
    return ModelEndpoint(**asdict(target), api_key="test-api-key")


@pytest.fixture
def model_service():
    service = AsyncMock()
    service.describe.return_value = _target()
    service.connect.side_effect = _connect
    return service


@pytest.fixture
def llm_evaluator(mock_model_instance_service, mock_secret_manager, model_service):
    """Create LLM condition evaluator with mocked dependencies."""
    return LLMConditionEvaluator(
        model_instance_service=mock_model_instance_service,
        secret_manager=mock_secret_manager,
        model_service=model_service,
        user_context=UserContext(user_id="user-1", workspace_id="ws-1"),
        record_costs=AsyncMock(),
        refuse_at_spend_cap=AsyncMock(),
    )


class TestLLMConditionEvaluator:
    """Test cases for LLM condition evaluator."""

    @pytest.mark.asyncio
    async def test_evaluate_rule_condition_simple_match(self, llm_evaluator):
        """Test simple rule condition evaluation with matching data."""
        condition = {
            "type": "rule",
            "rules": [{"field": "request.method", "operator": "eq", "value": "POST"}],
            "logic": "AND",
        }

        event_data = {"request": {"method": "POST", "body": {"message": "test"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_rule_condition_no_match(self, llm_evaluator):
        """Test simple rule condition evaluation with non-matching data."""
        condition = {
            "type": "rule",
            "rules": [{"field": "request.method", "operator": "eq", "value": "POST"}],
            "logic": "AND",
        }

        event_data = {"request": {"method": "GET", "body": {"message": "test"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_rule_condition_multiple_rules_and(self, llm_evaluator):
        """Test multiple rules with AND logic."""
        condition = {
            "type": "rule",
            "rules": [
                {"field": "request.method", "operator": "eq", "value": "POST"},
                {"field": "request.body.type", "operator": "eq", "value": "file"},
            ],
            "logic": "AND",
        }

        event_data = {
            "request": {"method": "POST", "body": {"type": "file", "name": "document.pdf"}}
        }

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_rule_condition_multiple_rules_or(self, llm_evaluator):
        """Test multiple rules with OR logic."""
        condition = {
            "type": "rule",
            "rules": [
                {"field": "request.method", "operator": "eq", "value": "POST"},
                {"field": "request.method", "operator": "eq", "value": "PUT"},
            ],
            "logic": "OR",
        }

        event_data = {"request": {"method": "PUT", "body": {"message": "test"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_rule_condition_operators(self, llm_evaluator):
        """Test different operators in rule conditions."""
        # Test contains operator
        condition = {
            "type": "rule",
            "rules": [{"field": "request.body.message", "operator": "contains", "value": "file"}],
            "logic": "AND",
        }

        event_data = {"request": {"body": {"message": "I have a file to upload"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

        # Test exists operator
        condition = {
            "type": "rule",
            "rules": [{"field": "request.body.attachment", "operator": "exists"}],
            "logic": "AND",
        }

        event_data = {"request": {"body": {"attachment": {"name": "file.pdf"}}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    @patch("agentarea_agents_sdk.models.llm_model.acompletion")
    async def test_evaluate_llm_condition_true(self, mock_completion, llm_evaluator):
        """Test LLM condition evaluation returning true."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"verdict": "met", "score": 0.9, "reason": "matches"}'
        )
        mock_completion.return_value = _response(mock_response.choices[0].message.content)

        condition = {
            "type": "llm",
            "description": "when user sends a file attachment",
            "context_fields": ["request.body"],
            "model_id": str(uuid4()),
        }

        event_data = {
            "request": {
                "body": {"document": {"file_name": "report.pdf"}, "message": "Here's the report"}
            }
        }

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

        # Verify LLM was called
        mock_completion.assert_called_once()

    @pytest.mark.asyncio
    @patch("agentarea_agents_sdk.models.llm_model.acompletion")
    async def test_evaluate_llm_condition_false(self, mock_completion, llm_evaluator):
        """Test LLM condition evaluation returning false."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"verdict": "not_met", "score": 0.9, "reason": "does not match"}'
        )
        mock_completion.return_value = _response(mock_response.choices[0].message.content)

        condition = {
            "type": "llm",
            "description": "when user sends a file attachment",
            "context_fields": ["request.body"],
            "model_id": str(uuid4()),
        }

        event_data = {"request": {"body": {"message": "Hello, how are you?"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_combined_condition_and(self, llm_evaluator):
        """Test combined condition with AND logic."""
        condition = {
            "type": "combined",
            "conditions": [
                {
                    "type": "rule",
                    "rules": [{"field": "request.method", "operator": "eq", "value": "POST"}],
                    "logic": "AND",
                },
                {
                    "type": "rule",
                    "rules": [{"field": "request.body.type", "operator": "eq", "value": "file"}],
                    "logic": "AND",
                },
            ],
            "logic": "AND",
        }

        event_data = {
            "request": {"method": "POST", "body": {"type": "file", "name": "document.pdf"}}
        }

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_combined_condition_or(self, llm_evaluator):
        """Test combined condition with OR logic."""
        condition = {
            "type": "combined",
            "conditions": [
                {
                    "type": "rule",
                    "rules": [{"field": "request.method", "operator": "eq", "value": "GET"}],
                    "logic": "AND",
                },
                {
                    "type": "rule",
                    "rules": [{"field": "request.body.type", "operator": "eq", "value": "file"}],
                    "logic": "AND",
                },
            ],
            "logic": "OR",
        }

        event_data = {
            "request": {"method": "POST", "body": {"type": "file", "name": "document.pdf"}}
        }

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    @patch("agentarea_agents_sdk.models.llm_model.acompletion")
    async def test_extract_task_parameters(self, mock_completion, llm_evaluator):
        """Test LLM-based task parameter extraction."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"user_id": "123", "file_name": "report.pdf", "action": "analyze_document"}
        )
        mock_completion.return_value = _response(mock_response.choices[0].message.content)

        instruction = "analyze the uploaded file and respond with insights"
        event_data = {
            "request": {"body": {"user": {"id": "123"}, "document": {"file_name": "report.pdf"}}}
        }

        result = await llm_evaluator.extract_task_parameters(
            instruction, event_data, model_id=uuid4()
        )

        assert result["user_id"] == "123"
        assert result["file_name"] == "report.pdf"
        assert result["action"] == "analyze_document"

    @pytest.mark.asyncio
    @patch("agentarea_agents_sdk.models.llm_model.acompletion")
    async def test_extract_task_parameters_invalid_json(self, mock_completion, llm_evaluator):
        """Test parameter extraction with invalid JSON response."""
        # Mock LLM response with invalid JSON
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is not valid JSON"
        mock_completion.return_value = _response(mock_response.choices[0].message.content)

        instruction = "extract parameters"
        event_data = {"test": "data"}

        result = await llm_evaluator.extract_task_parameters(
            instruction, event_data, model_id=uuid4()
        )

        # Should fallback to basic parameters
        assert "event_data" in result
        assert "instruction" in result
        assert "llm_response" in result

    def test_validate_rule_condition_syntax(self, llm_evaluator):
        """Test rule condition syntax validation."""
        # Valid condition
        valid_condition = {
            "type": "rule",
            "rules": [{"field": "request.method", "operator": "eq", "value": "POST"}],
            "logic": "AND",
        }

        errors = llm_evaluator._validate_rule_condition(valid_condition)
        assert len(errors) == 0

        # Invalid condition - missing field
        invalid_condition = {"type": "rule", "rules": [{"operator": "eq", "value": "POST"}]}

        errors = llm_evaluator._validate_rule_condition(invalid_condition)
        assert len(errors) > 0
        assert any("missing required 'field'" in error for error in errors)

    def test_validate_llm_condition_syntax(self, llm_evaluator):
        """Test LLM condition syntax validation."""
        # Valid condition
        valid_condition = {
            "type": "llm",
            "description": "when user sends a file",
            "model_id": str(uuid4()),
            "context_fields": ["request.body"],
            "examples": [{"input": {"body": {"file": "test.pdf"}}, "expected": True}],
        }

        errors = llm_evaluator._validate_llm_condition(valid_condition)
        assert len(errors) == 0

        # Invalid condition - missing description
        invalid_condition = {"type": "llm", "context_fields": ["request.body"]}

        errors = llm_evaluator._validate_llm_condition(invalid_condition)
        assert len(errors) > 0
        assert any("must have a 'description'" in error for error in errors)
        assert any("must name its 'model_id'" in error for error in errors)

    def test_get_nested_value(self, llm_evaluator):
        """Test nested value extraction."""
        data = {"request": {"body": {"user": {"id": "123", "name": "John"}, "message": "Hello"}}}

        # Test successful extraction
        assert llm_evaluator._get_nested_value(data, "request.body.user.id") == "123"
        assert llm_evaluator._get_nested_value(data, "request.body.message") == "Hello"

        # Test non-existent path
        assert llm_evaluator._get_nested_value(data, "request.body.nonexistent") is None
        assert llm_evaluator._get_nested_value(data, "nonexistent.path") is None

    @pytest.mark.asyncio
    async def test_llm_call_failure(self, llm_evaluator):
        """Test handling of LLM call failures."""
        condition = {"type": "llm", "description": "test condition", "model_id": str(uuid4())}

        event_data = {"test": "data"}

        # Mock model instance service to return None (model not found)
        llm_evaluator.model_instance_service.get.return_value = None

        with pytest.raises(LLMConditionEvaluationError):
            await llm_evaluator.evaluate_condition(condition, event_data)

    @pytest.mark.asyncio
    async def test_unknown_condition_type(self, llm_evaluator):
        """Test handling of unknown condition types."""
        condition = {"type": "unknown_type", "description": "test condition"}

        event_data = {"test": "data"}

        with pytest.raises(LLMConditionEvaluationError):
            await llm_evaluator.evaluate_condition(condition, event_data)

    @pytest.mark.asyncio
    async def test_validate_condition_syntax_comprehensive(self, llm_evaluator):
        """Test comprehensive condition syntax validation."""
        # Test valid combined condition
        valid_condition = {
            "type": "combined",
            "conditions": [
                {
                    "type": "rule",
                    "rules": [{"field": "test", "operator": "eq", "value": "value"}],
                    "logic": "AND",
                },
                {"type": "llm", "description": "test description", "model_id": str(uuid4())},
            ],
            "logic": "AND",
        }

        errors = await llm_evaluator.validate_condition_syntax(valid_condition)
        assert len(errors) == 0

        # Test invalid combined condition
        invalid_condition = {
            "type": "combined",
            "conditions": [
                {
                    "type": "rule",
                    "rules": [{"operator": "eq", "value": "value"}],  # Missing field
                }
            ],
            "logic": "INVALID",  # Invalid logic
        }

        errors = await llm_evaluator.validate_condition_syntax(invalid_condition)
        assert len(errors) > 0


@pytest.mark.asyncio
@patch("agentarea_agents_sdk.models.llm_model.acompletion")
async def test_a_member_endpoint_on_a_private_address_is_refused(
    mock_completion, llm_evaluator, model_service
):
    # GHSA-pprc-x767-m6jg: a member-set endpoint must not reach what the platform can.
    model_service.describe.return_value = _target("http://10.0.0.5:8080/v1")

    with pytest.raises(LLMConditionEvaluationError):
        await llm_evaluator._call_llm("p", uuid4(), purpose="test", trigger_context=None)
    mock_completion.assert_not_called()


@pytest.mark.asyncio
@patch("agentarea_agents_sdk.models.llm_model.acompletion")
async def test_a_platform_endpoint_is_called_as_configured(
    mock_completion, llm_evaluator, model_service
):
    model_service.describe.return_value = _target("http://10.0.0.5:8080/v1", "platform")
    mock_completion.return_value = _response("ok")

    assert await llm_evaluator._call_llm("p", uuid4(), purpose="test", trigger_context=None) == "ok"
    assert mock_completion.call_args.kwargs["base_url"] == "http://10.0.0.5:8080/v1"
