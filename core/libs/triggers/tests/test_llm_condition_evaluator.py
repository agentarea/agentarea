"""Tests for LLM condition evaluator."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
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

    service.get.return_value = mock_instance
    return service


@pytest.fixture
def mock_secret_manager():
    """Mock secret manager."""
    return AsyncMock()


@pytest.fixture
def llm_evaluator(mock_model_instance_service, mock_secret_manager):
    """Create LLM condition evaluator with mocked dependencies."""
    return LLMConditionEvaluator(
        model_instance_service=mock_model_instance_service,
        secret_manager=mock_secret_manager,
        default_model_id=uuid4(),
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
        }

        event_data = {"request": {"body": {"message": "I have a file to upload"}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

        # Test exists operator
        condition = {
            "type": "rule",
            "rules": [{"field": "request.body.attachment", "operator": "exists"}],
        }

        event_data = {"request": {"body": {"attachment": {"name": "file.pdf"}}}}

        result = await llm_evaluator.evaluate_condition(condition, event_data)
        assert result is True

    @pytest.mark.asyncio
    @patch("agentarea_triggers.llm_condition_evaluator.litellm.acompletion")
    async def test_evaluate_llm_condition_true(self, mock_completion, llm_evaluator):
        """Test LLM condition evaluation returning true."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "true"
        mock_completion.return_value = mock_response

        condition = {
            "type": "llm",
            "description": "when user sends a file attachment",
            "context_fields": ["request.body"],
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
    @patch("agentarea_triggers.llm_condition_evaluator.litellm.acompletion")
    async def test_evaluate_llm_condition_false(self, mock_completion, llm_evaluator):
        """Test LLM condition evaluation returning false."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "false"
        mock_completion.return_value = mock_response

        condition = {
            "type": "llm",
            "description": "when user sends a file attachment",
            "context_fields": ["request.body"],
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
                },
                {
                    "type": "rule",
                    "rules": [{"field": "request.body.type", "operator": "eq", "value": "file"}],
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
                },
                {
                    "type": "rule",
                    "rules": [{"field": "request.body.type", "operator": "eq", "value": "file"}],
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
    @patch("agentarea_triggers.llm_condition_evaluator.litellm.acompletion")
    async def test_extract_task_parameters(self, mock_completion, llm_evaluator):
        """Test LLM-based task parameter extraction."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"user_id": "123", "file_name": "report.pdf", "action": "analyze_document"}
        )
        mock_completion.return_value = mock_response

        instruction = "analyze the uploaded file and respond with insights"
        event_data = {
            "request": {"body": {"user": {"id": "123"}, "document": {"file_name": "report.pdf"}}}
        }

        result = await llm_evaluator.extract_task_parameters(instruction, event_data)

        assert result["user_id"] == "123"
        assert result["file_name"] == "report.pdf"
        assert result["action"] == "analyze_document"

    @pytest.mark.asyncio
    @patch("agentarea_triggers.llm_condition_evaluator.litellm.acompletion")
    async def test_extract_task_parameters_invalid_json(self, mock_completion, llm_evaluator):
        """Test parameter extraction with invalid JSON response."""
        # Mock LLM response with invalid JSON
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is not valid JSON"
        mock_completion.return_value = mock_response

        instruction = "extract parameters"
        event_data = {"test": "data"}

        result = await llm_evaluator.extract_task_parameters(instruction, event_data)

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

    def test_get_nested_value(self, llm_evaluator):
        """Test nested value extraction."""
        data = {"request": {"body": {"user": {"id": "123", "name": "John"}, "message": "Hello"}}}

        # Test successful extraction
        assert llm_evaluator._get_nested_value(data, "request.body.user.id") == "123"
        assert llm_evaluator._get_nested_value(data, "request.body.message") == "Hello"

        # Test non-existent path
        assert llm_evaluator._get_nested_value(data, "request.body.nonexistent") is None
        assert llm_evaluator._get_nested_value(data, "nonexistent.path") is None

    def test_parse_evaluation_response(self, llm_evaluator):
        """Test parsing of LLM evaluation responses."""
        # Direct boolean responses
        assert llm_evaluator._parse_evaluation_response("true") is True
        assert llm_evaluator._parse_evaluation_response("false") is False

        # Positive indicators
        assert llm_evaluator._parse_evaluation_response("yes, condition is met") is True
        assert llm_evaluator._parse_evaluation_response("The condition matches") is True

        # Negative indicators
        assert llm_evaluator._parse_evaluation_response("no, condition not met") is False
        assert llm_evaluator._parse_evaluation_response("does not match") is False

        # Unclear response defaults to False
        assert llm_evaluator._parse_evaluation_response("unclear response") is False

    @pytest.mark.asyncio
    async def test_llm_call_failure(self, llm_evaluator):
        """Test handling of LLM call failures."""
        condition = {"type": "llm", "description": "test condition"}

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
                {"type": "rule", "rules": [{"field": "test", "operator": "eq", "value": "value"}]},
                {"type": "llm", "description": "test description"},
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
