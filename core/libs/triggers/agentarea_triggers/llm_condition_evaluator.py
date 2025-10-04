"""LLM-based condition evaluation service for triggers.

This module provides LLM-powered natural language condition evaluation
for both cron and webhook triggers, allowing users to specify conditions
in natural language that are evaluated against event data.
"""

import json
import logging
from typing import Any
from uuid import UUID

import litellm
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_llm.application.model_instance_service import ModelInstanceService

logger = logging.getLogger(__name__)


class LLMConditionEvaluationError(Exception):
    """Raised when LLM condition evaluation fails."""

    pass


class LLMConditionEvaluator:
    """Service for evaluating trigger conditions using LLM."""

    def __init__(
        self,
        model_instance_service: ModelInstanceService,
        secret_manager: BaseSecretManager,
        default_model_id: UUID | None = None,
    ):
        """Initialize the LLM condition evaluator.

        Args:
            model_instance_service: Service for managing LLM model instances
            secret_manager: Service for managing API keys and secrets
            default_model_id: Default model instance ID to use if none specified
        """
        self.model_instance_service = model_instance_service
        self.secret_manager = secret_manager
        self.default_model_id = default_model_id

    async def evaluate_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
        model_id: UUID | None = None,
    ) -> bool:
        """Evaluate a condition against event data using LLM.

        Args:
            condition: The condition configuration to evaluate
            event_data: The event data to evaluate against
            trigger_context: Optional trigger context for evaluation
            model_id: Optional model instance ID to use for evaluation

        Returns:
            True if condition is met, False otherwise

        Raises:
            LLMConditionEvaluationError: If evaluation fails
        """
        try:
            # Determine condition type
            condition_type = condition.get("type", "llm")

            if condition_type == "rule":
                return await self._evaluate_rule_condition(condition, event_data)
            elif condition_type == "llm":
                return await self._evaluate_llm_condition(
                    condition, event_data, trigger_context, model_id
                )
            elif condition_type == "combined":
                return await self._evaluate_combined_condition(
                    condition, event_data, trigger_context, model_id
                )
            else:
                raise LLMConditionEvaluationError(f"Unknown condition type: {condition_type}")

        except Exception as e:
            logger.error(f"Condition evaluation failed: {e}")
            raise LLMConditionEvaluationError(f"Condition evaluation failed: {e}") from e

    async def _evaluate_rule_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
    ) -> bool:
        """Evaluate a rule-based condition.

        Args:
            condition: Rule condition configuration
            event_data: Event data to evaluate

        Returns:
            True if rule condition is met
        """
        rules = condition.get("rules", [])
        logic = condition.get("logic", "AND").upper()

        if not rules:
            return True

        results = []
        for rule in rules:
            field = rule.get("field", "")
            operator = rule.get("operator", "eq")
            expected_value = rule.get("value")

            # Extract field value from event data using dot notation
            actual_value = self._get_nested_value(event_data, field)

            # Evaluate rule based on operator
            if operator == "eq":
                result = actual_value == expected_value
            elif operator == "ne":
                result = actual_value != expected_value
            elif operator == "gt":
                result = actual_value > expected_value if actual_value is not None else False
            elif operator == "lt":
                result = actual_value < expected_value if actual_value is not None else False
            elif operator == "gte":
                result = actual_value >= expected_value if actual_value is not None else False
            elif operator == "lte":
                result = actual_value <= expected_value if actual_value is not None else False
            elif operator == "contains":
                result = expected_value in str(actual_value) if actual_value is not None else False
            elif operator == "not_contains":
                result = (
                    expected_value not in str(actual_value) if actual_value is not None else False
                )
            elif operator == "exists":
                result = actual_value is not None
            elif operator == "not_exists":
                result = actual_value is None
            else:
                logger.warning(f"Unknown operator: {operator}")
                result = False

            results.append(result)

        # Apply logic
        if logic == "AND":
            return all(results)
        elif logic == "OR":
            return any(results)
        else:
            logger.warning(f"Unknown logic operator: {logic}")
            return False

    async def _evaluate_llm_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
        model_id: UUID | None = None,
    ) -> bool:
        """Evaluate an LLM-based natural language condition.

        Args:
            condition: LLM condition configuration
            event_data: Event data to evaluate
            trigger_context: Optional trigger context
            model_id: Optional model instance ID

        Returns:
            True if LLM determines condition is met
        """
        description = condition.get("description", "")
        context_fields = condition.get("context_fields", [])
        examples = condition.get("examples", [])

        if not description:
            raise LLMConditionEvaluationError("LLM condition description is required")

        # Extract relevant context data
        context_data = {}
        for field in context_fields:
            context_data[field] = self._get_nested_value(event_data, field)

        # Build evaluation prompt
        prompt = self._build_evaluation_prompt(
            description, event_data, context_data, examples, trigger_context
        )

        # Call LLM for evaluation
        response = await self._call_llm(prompt, model_id)

        # Parse response
        return self._parse_evaluation_response(response)

    async def _evaluate_combined_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
        model_id: UUID | None = None,
    ) -> bool:
        """Evaluate a combined condition with multiple sub-conditions.

        Args:
            condition: Combined condition configuration
            event_data: Event data to evaluate
            trigger_context: Optional trigger context
            model_id: Optional model instance ID

        Returns:
            True if combined condition is met
        """
        conditions = condition.get("conditions", [])
        logic = condition.get("logic", "AND").upper()

        if not conditions:
            return True

        results = []
        for sub_condition in conditions:
            result = await self.evaluate_condition(
                sub_condition, event_data, trigger_context, model_id
            )
            results.append(result)

        # Apply logic
        if logic == "AND":
            return all(results)
        elif logic == "OR":
            return any(results)
        else:
            logger.warning(f"Unknown logic operator: {logic}")
            return False

    async def extract_task_parameters(
        self,
        instruction: str,
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
        model_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Extract task parameters from event data using LLM.

        Args:
            instruction: Natural language instruction for parameter extraction
            event_data: Event data to extract parameters from
            trigger_context: Optional trigger context
            model_id: Optional model instance ID

        Returns:
            Dictionary of extracted parameters

        Raises:
            LLMConditionEvaluationError: If parameter extraction fails
        """
        try:
            # Build parameter extraction prompt
            prompt = self._build_parameter_extraction_prompt(
                instruction, event_data, trigger_context
            )

            # Call LLM for parameter extraction
            response = await self._call_llm(prompt, model_id)

            # Parse response as JSON
            try:
                parameters = json.loads(response.strip())
                if not isinstance(parameters, dict):
                    raise ValueError("Response is not a dictionary")
                return parameters
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse LLM response as JSON: {e}")
                # Fallback: return basic parameters
                return {
                    "event_data": event_data,
                    "instruction": instruction,
                    "llm_response": response,
                }

        except Exception as e:
            logger.error(f"Parameter extraction failed: {e}")
            raise LLMConditionEvaluationError(f"Parameter extraction failed: {e}") from e

    async def validate_condition_syntax(
        self,
        condition: dict[str, Any],
    ) -> list[str]:
        """Validate condition syntax and return any errors.

        Args:
            condition: Condition configuration to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        return self._validate_condition_sync(condition)

    def _validate_condition_sync(
        self,
        condition: dict[str, Any],
    ) -> list[str]:
        """Synchronous condition validation helper.

        Args:
            condition: Condition configuration to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        try:
            condition_type = condition.get("type", "llm")

            if condition_type == "rule":
                errors.extend(self._validate_rule_condition(condition))
            elif condition_type == "llm":
                errors.extend(self._validate_llm_condition(condition))
            elif condition_type == "combined":
                errors.extend(self._validate_combined_condition(condition))
            else:
                errors.append(f"Unknown condition type: {condition_type}")

        except Exception as e:
            errors.append(f"Validation error: {e}")

        return errors

    def _validate_rule_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate rule-based condition syntax."""
        errors = []

        rules = condition.get("rules", [])
        if not rules:
            errors.append("Rule condition must have at least one rule")

        valid_operators = {
            "eq",
            "ne",
            "gt",
            "lt",
            "gte",
            "lte",
            "contains",
            "not_contains",
            "exists",
            "not_exists",
        }
        valid_logic = {"AND", "OR"}

        logic = condition.get("logic", "AND").upper()
        if logic not in valid_logic:
            errors.append(f"Invalid logic operator: {logic}. Must be one of {valid_logic}")

        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                errors.append(f"Rule {i} must be a dictionary")
                continue

            if "field" not in rule:
                errors.append(f"Rule {i} missing required 'field'")

            operator = rule.get("operator", "eq")
            if operator not in valid_operators:
                errors.append(f"Rule {i} has invalid operator: {operator}")

            if operator not in {"exists", "not_exists"} and "value" not in rule:
                errors.append(f"Rule {i} missing required 'value' for operator {operator}")

        return errors

    def _validate_llm_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate LLM-based condition syntax."""
        errors = []

        if not condition.get("description"):
            errors.append("LLM condition must have a 'description'")

        context_fields = condition.get("context_fields", [])
        if context_fields and not isinstance(context_fields, list):
            errors.append("context_fields must be a list")

        examples = condition.get("examples", [])
        if examples and not isinstance(examples, list):
            errors.append("examples must be a list")

        for i, example in enumerate(examples):
            if not isinstance(example, dict):
                errors.append(f"Example {i} must be a dictionary")
                continue

            if "input" not in example or "expected" not in example:
                errors.append(f"Example {i} must have 'input' and 'expected' fields")

        return errors

    def _validate_combined_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate combined condition syntax."""
        errors = []

        conditions = condition.get("conditions", [])
        if not conditions:
            errors.append("Combined condition must have at least one sub-condition")

        valid_logic = {"AND", "OR"}
        logic = condition.get("logic", "AND").upper()
        if logic not in valid_logic:
            errors.append(f"Invalid logic operator: {logic}. Must be one of {valid_logic}")

        for i, sub_condition in enumerate(conditions):
            if not isinstance(sub_condition, dict):
                errors.append(f"Sub-condition {i} must be a dictionary")
                continue

            # Recursively validate sub-conditions (sync validation only)
            try:
                sub_errors = self._validate_condition_sync(sub_condition)
                for error in sub_errors:
                    errors.append(f"Sub-condition {i}: {error}")
            except Exception as e:
                errors.append(f"Sub-condition {i}: Validation error: {e}")

        return errors

    def _get_nested_value(self, data: dict[str, Any], field_path: str) -> Any:
        """Extract nested value from data using dot notation.

        Args:
            data: Data dictionary to extract from
            field_path: Dot-separated field path (e.g., "request.body.message")

        Returns:
            The extracted value or None if not found
        """
        try:
            value = data
            for part in field_path.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
        except Exception:
            return None

    def _build_evaluation_prompt(
        self,
        description: str,
        event_data: dict[str, Any],
        context_data: dict[str, Any],
        examples: list[dict[str, Any]],
        trigger_context: dict[str, Any] | None = None,
    ) -> str:
        """Build prompt for LLM condition evaluation."""
        prompt_parts = [
            "You are an AI assistant that evaluates trigger conditions based on event data.",
            "",
            f"CONDITION TO EVALUATE: {description}",
            "",
            "EVENT DATA:",
            json.dumps(event_data, indent=2),
            "",
        ]

        if context_data:
            prompt_parts.extend(
                [
                    "RELEVANT CONTEXT:",
                    json.dumps(context_data, indent=2),
                    "",
                ]
            )

        if trigger_context:
            prompt_parts.extend(
                [
                    "TRIGGER CONTEXT:",
                    json.dumps(trigger_context, indent=2),
                    "",
                ]
            )

        if examples:
            prompt_parts.extend(
                [
                    "EXAMPLES:",
                ]
            )
            for i, example in enumerate(examples):
                prompt_parts.extend(
                    [
                        f"Example {i + 1}:",
                        f"Input: {json.dumps(example.get('input', {}), indent=2)}",
                        f"Expected: {example.get('expected')}",
                        "",
                    ]
                )

        prompt_parts.extend(
            [
                "Based on the event data and condition description, determine if the condition is met.",
                "Respond with exactly 'true' if the condition is met, or 'false' if it is not met.",
                "Do not include any explanation or additional text.",
            ]
        )

        return "\n".join(prompt_parts)

    def _build_parameter_extraction_prompt(
        self,
        instruction: str,
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
    ) -> str:
        """Build prompt for LLM parameter extraction."""
        prompt_parts = [
            "You are an AI assistant that extracts task parameters from event data.",
            "",
            f"INSTRUCTION: {instruction}",
            "",
            "EVENT DATA:",
            json.dumps(event_data, indent=2),
            "",
        ]

        if trigger_context:
            prompt_parts.extend(
                [
                    "TRIGGER CONTEXT:",
                    json.dumps(trigger_context, indent=2),
                    "",
                ]
            )

        prompt_parts.extend(
            [
                "Based on the instruction and event data, extract relevant parameters for task execution.",
                "Return your response as a valid JSON object containing the extracted parameters.",
                "Include any relevant data from the event that would be useful for the task.",
                "Example response format:",
                "{",
                '  "user_id": "extracted_user_id",',
                '  "message": "extracted_message_content",',
                '  "file_url": "extracted_file_url",',
                '  "additional_context": "any_other_relevant_data"',
                "}",
            ]
        )

        return "\n".join(prompt_parts)

    async def _call_llm(
        self,
        prompt: str,
        model_id: UUID | None = None,
    ) -> str:
        """Call LLM with the given prompt.

        Args:
            prompt: The prompt to send to the LLM
            model_id: Optional model instance ID to use

        Returns:
            The LLM response content

        Raises:
            LLMConditionEvaluationError: If LLM call fails
        """
        try:
            # Use provided model_id or default
            effective_model_id = model_id or self.default_model_id
            if not effective_model_id:
                raise LLMConditionEvaluationError(
                    "No model ID provided and no default model configured"
                )

            # Get model instance details
            model_instance = await self.model_instance_service.get(effective_model_id)
            if not model_instance:
                raise LLMConditionEvaluationError(f"Model instance {effective_model_id} not found")

            # Extract model configuration
            provider_type = model_instance.provider_config.provider_spec.provider_type
            model_type = model_instance.model_spec.model_name
            api_key = getattr(model_instance.provider_config, "api_key", None)
            endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)

            # Build litellm parameters
            litellm_model = f"{provider_type}/{model_type}"
            litellm_params = {
                "model": litellm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # Low temperature for consistent evaluation
                "max_tokens": 1000,
            }

            if api_key:
                litellm_params["api_key"] = api_key
            if endpoint_url:
                url = endpoint_url
                if not url.startswith("http"):
                    url = f"http://{url}"
                litellm_params["base_url"] = url

            # TODO: Remove this hardcoded override when proper configuration is available
            litellm_params["base_url"] = "http://host.docker.internal:11434"

            logger.debug(f"Calling LLM for condition evaluation with model {litellm_model}")

            # Make the LLM call
            response = await litellm.acompletion(**litellm_params)
            content = response.choices[0].message.content or ""

            logger.debug(f"LLM condition evaluation response: {content[:100]}...")
            return content.strip()

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise LLMConditionEvaluationError(f"LLM call failed: {e}") from e

    def _parse_evaluation_response(self, response: str) -> bool:
        """Parse LLM evaluation response to boolean.

        Args:
            response: The LLM response content

        Returns:
            True if response indicates condition is met
        """
        response_lower = response.lower().strip()

        # Direct boolean responses
        if response_lower == "true":
            return True
        elif response_lower == "false":
            return False

        # Common positive indicators
        positive_indicators = [
            "yes",
            "condition is met",
            "condition met",
            "true",
            "match",
            "matches",
            "satisfied",
            "fulfilled",
            "correct",
            "valid",
            "success",
        ]

        # Common negative indicators
        negative_indicators = [
            "no",
            "condition is not met",
            "condition not met",
            "false",
            "no match",
            "does not match",
            "not satisfied",
            "not fulfilled",
            "incorrect",
            "invalid",
            "fail",
            "not match",
        ]

        # Check for negative indicators first (more specific)
        if any(indicator in response_lower for indicator in negative_indicators):
            return False

        # Check for positive indicators
        if any(indicator in response_lower for indicator in positive_indicators):
            return True

        # Default to False if unclear
        logger.warning(f"Unclear LLM evaluation response: {response}")
        return False
