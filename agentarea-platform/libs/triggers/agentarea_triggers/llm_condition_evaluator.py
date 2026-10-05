"""LLM-based condition evaluation service for triggers.

This module provides LLM-powered natural language condition evaluation
for both cron and webhook triggers, allowing users to specify conditions
in natural language that are evaluated against event data.
"""

import json
import logging
import re
from typing import Any, cast
from uuid import UUID

import litellm
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.model_service import ModelService
from agentarea_llm.domain.media import DecisionQuestionType
from agentarea_llm.domain.model_kind import ModelKind
from agentarea_llm.domain.provider_profiles import profile_for
from agentarea_secrets.secret_manager_factory import SecretManagerFactory
from pydantic import ValidationError

from .domain.enums import ConditionType
from .domain.models import ConditionVerdict

logger = logging.getLogger(__name__)


def _condition_type(condition: dict[str, Any]) -> ConditionType | None:
    """The condition's type (untyped means LLM), or None when it names no known one."""
    try:
        return ConditionType(condition.get("type", ConditionType.LLM))
    except ValueError:
        return None


class LLMConditionEvaluationError(Exception):
    """Raised when LLM condition evaluation fails."""

    pass


# The one question a decision model is asked about a condition, and its options.
_CONDITION_QUESTION = "condition_met"
_MET = "true"
_NOT_MET = "false"

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_verdict(response: str) -> ConditionVerdict:
    """The model's JSON verdict, or an error. Prose is not a verdict."""
    text = response.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMConditionEvaluationError(
            f"Condition model did not answer in JSON: {response[:200]!r}"
        ) from error
    try:
        return ConditionVerdict.model_validate(payload)
    except ValidationError as error:
        raise LLMConditionEvaluationError(
            f"Condition model gave no valid verdict: {error}"
        ) from error


def condition_syntax_errors(condition: dict[str, Any]) -> list[str]:
    """Syntax errors in a condition body, or an empty list when it is well-formed.

    Independent of any evaluator instance, so trigger save-time validation
    (``trigger_validation.py``) can call it without a model service.
    """
    errors: list[str] = []

    try:
        condition_type = _condition_type(condition)
        if condition_type is None:
            errors.append(f"Unknown condition type: {condition.get('type')}")
        elif condition_type is ConditionType.RULE:
            errors.extend(_rule_condition_errors(condition))
        elif condition_type is ConditionType.LLM:
            errors.extend(_llm_condition_errors(condition))
        else:
            errors.extend(_combined_condition_errors(condition))

    except Exception as e:
        errors.append(f"Validation error: {e}")

    return errors


def _rule_condition_errors(condition: dict[str, Any]) -> list[str]:
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

    logic = condition.get("logic")
    if not logic:
        errors.append("Rule condition must name its 'logic' (AND or OR)")
    elif logic.upper() not in valid_logic:
        errors.append(f"Invalid logic operator: {logic}. Must be one of {valid_logic}")

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"Rule {i} must be a dictionary")
            continue

        if "field" not in rule:
            errors.append(f"Rule {i} missing required 'field'")

        operator = rule.get("operator")
        if not operator:
            errors.append(f"Rule {i} missing required 'operator'")
        elif operator not in valid_operators:
            errors.append(f"Rule {i} has invalid operator: {operator}")

        if operator not in {"exists", "not_exists"} and "value" not in rule:
            errors.append(f"Rule {i} missing required 'value' for operator {operator}")

    return errors


def _llm_condition_errors(condition: dict[str, Any]) -> list[str]:
    """Validate LLM-based condition syntax."""
    errors = []

    if not condition.get("description"):
        errors.append("LLM condition must have a 'description'")
    if not condition.get("model_id"):
        errors.append("LLM condition must name its 'model_id'")

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


def _combined_condition_errors(condition: dict[str, Any]) -> list[str]:
    """Validate combined condition syntax."""
    errors = []

    conditions = condition.get("conditions", [])
    if not conditions:
        errors.append("Combined condition must have at least one sub-condition")

    valid_logic = {"AND", "OR"}
    logic = condition.get("logic")
    if not logic:
        errors.append("Combined condition must name its 'logic' (AND or OR)")
    elif logic.upper() not in valid_logic:
        errors.append(f"Invalid logic operator: {logic}. Must be one of {valid_logic}")

    for i, sub_condition in enumerate(conditions):
        if not isinstance(sub_condition, dict):
            errors.append(f"Sub-condition {i} must be a dictionary")
            continue

        try:
            sub_errors = condition_syntax_errors(sub_condition)
            for error in sub_errors:
                errors.append(f"Sub-condition {i}: {error}")
        except Exception as e:
            errors.append(f"Sub-condition {i}: Validation error: {e}")

    return errors


def build_condition_evaluator(
    *,
    session: Any,
    user_context: Any,
    secret_manager: BaseSecretManager,
    secret_manager_factory: SecretManagerFactory,
    event_broker: Any,
) -> "LLMConditionEvaluator | None":
    """The evaluator a TriggerService gets outside a request, when enabled.

    For the worker's trigger activities and the inbound channel consumer, which
    have a session and the trigger's workspace context but no request
    dependencies.
    """
    from agentarea_common.config import get_settings
    from agentarea_llm.application.model_service import build_model_service
    from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository

    if not get_settings().triggers.LLM_ENABLED:
        return None
    return LLMConditionEvaluator(
        model_instance_service=ModelInstanceService(
            repository=ModelInstanceRepository(session, user_context),
            event_broker=event_broker,
            secret_manager=secret_manager,
        ),
        secret_manager=secret_manager,
        model_service=build_model_service(
            session=session,
            user_context=user_context,
            secret_manager_factory=secret_manager_factory,
        ),
    )


class LLMConditionEvaluator:
    """Service for evaluating trigger conditions using LLM."""

    def __init__(
        self,
        model_instance_service: ModelInstanceService,
        secret_manager: BaseSecretManager,
        model_service: ModelService,
    ):
        """Initialize the LLM condition evaluator.

        Args:
            model_instance_service: Service for managing LLM model instances
            secret_manager: Service for managing API keys and secrets
            model_service: Resolves decision models, which answer a condition directly
        """
        self.model_instance_service = model_instance_service
        self.secret_manager = secret_manager
        self.model_service = model_service

    async def evaluate_structured(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
    ) -> ConditionVerdict:
        """Decide a condition against an event. Any failure raises; nothing defaults to met.

        Raises:
            LLMConditionEvaluationError: The condition could not be decided.
        """
        try:
            condition_type = _condition_type(condition)
            if condition_type is None:
                raise LLMConditionEvaluationError(
                    f"Unknown condition type: {condition.get('type')}"
                )
            if condition_type is ConditionType.RULE:
                return await self._evaluate_rule_condition(condition, event_data)
            if condition_type is ConditionType.LLM:
                return await self._evaluate_llm_condition(condition, event_data, trigger_context)
            return await self._evaluate_combined_condition(condition, event_data, trigger_context)
        except LLMConditionEvaluationError:
            raise
        except Exception as e:
            logger.exception(f"Condition evaluation failed: {e}")
            raise LLMConditionEvaluationError(f"Condition evaluation failed: {e}") from e

    async def evaluate_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
    ) -> bool:
        """Whether the condition is met; see ``evaluate_structured``."""
        return (await self.evaluate_structured(condition, event_data, trigger_context)).met

    async def _evaluate_rule_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
    ) -> ConditionVerdict:
        """Evaluate a rule-based condition.

        Args:
            condition: Rule condition configuration
            event_data: Event data to evaluate

        Returns:
            The verdict, with a reason naming how many rules matched.
        """
        rules = condition.get("rules")
        if not rules:
            raise LLMConditionEvaluationError("Rule condition needs at least one rule")

        logic = condition.get("logic")
        if not logic:
            raise LLMConditionEvaluationError("Rule condition needs its 'logic' (AND or OR)")
        logic = logic.upper()

        results = []
        for rule in rules:
            field = rule.get("field")
            if not field:
                raise LLMConditionEvaluationError("Rule is missing its 'field'")
            operator = rule.get("operator")
            if not operator:
                raise LLMConditionEvaluationError("Rule is missing its 'operator'")
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
                raise LLMConditionEvaluationError(f"Unknown operator: {operator}")

            results.append(result)

        # Apply logic
        if logic == "AND":
            met = all(results)
        elif logic == "OR":
            met = any(results)
        else:
            raise LLMConditionEvaluationError(f"Unknown rule logic: {logic}")
        return ConditionVerdict(
            verdict="met" if met else "not_met",
            reason=f"rule ({logic}): {sum(results)} of {len(results)} rules matched",
        )

    async def _evaluate_llm_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
    ) -> ConditionVerdict:
        """Evaluate an LLM-based natural language condition.

        Args:
            condition: LLM condition configuration, naming its model in ``model_id``
            event_data: Event data to evaluate
            trigger_context: Optional trigger context

        Returns:
            The structured verdict the model gave.
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

        raw_model_id = condition.get("model_id")
        if not raw_model_id:
            raise LLMConditionEvaluationError("LLM condition has no model_id")
        try:
            effective_model_id = UUID(str(raw_model_id))
        except ValueError as error:
            raise LLMConditionEvaluationError(
                f"LLM condition model_id '{raw_model_id}' is not a model instance id"
            ) from error
        model_instance = await self.model_instance_service.get(effective_model_id)
        if not model_instance:
            raise LLMConditionEvaluationError(f"Model instance {effective_model_id} not found")
        kind = model_instance.model_spec.kind
        if kind == ModelKind.DECISION:
            return await self._decide_condition(
                effective_model_id, description, event_data, context_data, examples, trigger_context
            )
        if kind != ModelKind.CHAT:
            raise LLMConditionEvaluationError(
                f"Model instance {effective_model_id} is a {kind} model; "
                "a condition needs a chat or decision model"
            )

        # Build evaluation prompt
        prompt = self._build_evaluation_prompt(
            description, event_data, context_data, examples, trigger_context
        )

        # Call LLM for evaluation
        response = await self._call_llm(prompt, effective_model_id)

        # Parse response
        return _parse_verdict(response)

    async def _decide_condition(
        self,
        model_id: UUID,
        description: str,
        event_data: dict[str, Any],
        context_data: dict[str, Any],
        examples: list[dict[str, Any]],
        trigger_context: dict[str, Any] | None,
    ) -> ConditionVerdict:
        """Ask a decision model whether the event meets the condition."""
        state: dict[str, Any] = {"event": event_data}
        if context_data:
            state["relevant_context"] = context_data
        if trigger_context:
            state["trigger_context"] = trigger_context
        if examples:
            state["examples"] = examples
        model = await self.model_service.decision_model(model_id)
        result = await model.evaluate(
            state,
            {
                _CONDITION_QUESTION: {
                    "type": DecisionQuestionType.CHOICE,
                    "instructions": f"Is this condition met by the event: {description}",
                    "criteria": {
                        _MET: "The event meets the condition",
                        _NOT_MET: "The event does not meet the condition",
                    },
                }
            },
        )
        choice = result.answers[_CONDITION_QUESTION][DecisionQuestionType.CHOICE]
        if choice not in (_MET, _NOT_MET):
            raise LLMConditionEvaluationError(f"Decision model answered {choice!r}")
        return ConditionVerdict(
            verdict="met" if choice == _MET else "not_met",
            reason=f"decision model {model_id} chose {choice}",
        )

    async def _evaluate_combined_condition(
        self,
        condition: dict[str, Any],
        event_data: dict[str, Any],
        trigger_context: dict[str, Any] | None = None,
    ) -> ConditionVerdict:
        """Evaluate a combined condition with multiple sub-conditions.

        Args:
            condition: Combined condition configuration
            event_data: Event data to evaluate
            trigger_context: Optional trigger context

        Returns:
            The combined verdict, with the weakest (AND) or strongest (OR) score.
        """
        conditions = condition.get("conditions")
        if not conditions:
            raise LLMConditionEvaluationError("Combined condition needs at least one sub-condition")

        logic = condition.get("logic")
        if not logic:
            raise LLMConditionEvaluationError("Combined condition needs its 'logic' (AND or OR)")
        logic = logic.upper()

        verdicts = [
            await self.evaluate_structured(sub, event_data, trigger_context) for sub in conditions
        ]

        # Apply logic
        if logic == "AND":
            met = all(v.met for v in verdicts)
        elif logic == "OR":
            met = any(v.met for v in verdicts)
        else:
            raise LLMConditionEvaluationError(f"Unknown combined logic: {logic}")
        scores = [v.score for v in verdicts if v.score is not None]
        score = (min(scores) if logic == "AND" else max(scores)) if scores else None
        return ConditionVerdict(
            verdict="met" if met else "not_met",
            score=score,
            reason=f"{logic}: " + "; ".join(v.reason for v in verdicts),
        )

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
                logger.warning(f"Failed to parse LLM response as JSON: {e}", exc_info=True)
                # Fallback: return basic parameters
                return {
                    "event_data": event_data,
                    "instruction": instruction,
                    "llm_response": response,
                }

        except Exception as e:
            logger.exception(f"Parameter extraction failed: {e}")
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
        return condition_syntax_errors(condition)

    def _validate_condition_sync(
        self,
        condition: dict[str, Any],
    ) -> list[str]:
        """Synchronous condition validation helper; see ``condition_syntax_errors``."""
        return condition_syntax_errors(condition)

    def _validate_rule_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate rule-based condition syntax; see ``_rule_condition_errors``."""
        return _rule_condition_errors(condition)

    def _validate_llm_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate LLM-based condition syntax; see ``_llm_condition_errors``."""
        return _llm_condition_errors(condition)

    def _validate_combined_condition(self, condition: dict[str, Any]) -> list[str]:
        """Validate combined condition syntax; see ``_combined_condition_errors``."""
        return _combined_condition_errors(condition)

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
                "Decide whether the event meets the condition.",
                'Reply with one JSON object and nothing else: {"verdict": "met" or "not_met", '
                '"score": a number from 0 to 1 for how sure you are, "reason": one short '
                "sentence}.",
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
            model_id: The model instance ID to use; there is no default

        Returns:
            The LLM response content

        Raises:
            LLMConditionEvaluationError: If LLM call fails
        """
        try:
            if model_id is None:
                raise LLMConditionEvaluationError("No model instance named for this LLM call")
            effective_model_id = model_id

            # The credential is read by reference from the workspace that owns
            # it; the configuration only stores the secret's name.
            endpoint = await self.model_service.resolve(effective_model_id, ModelKind.CHAT)
            provider_type = endpoint.provider_type

            # Build litellm parameters
            litellm_model = f"{provider_type}/{endpoint.model_name}"
            litellm_params = {
                "model": litellm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # Low temperature for consistent evaluation
                "max_tokens": 1000,
            }

            if endpoint.api_key:
                litellm_params["api_key"] = endpoint.api_key
            if endpoint.endpoint_url:
                url = endpoint.endpoint_url
                if not url.startswith("http"):
                    url = f"http://{url}"
                litellm_params["base_url"] = url
            elif profile_for(provider_type).requires_endpoint_url:
                # Self-hosted provider: there is no public address to fall back
                # to, so the call would go nowhere.
                raise ValueError(
                    f"model instance {effective_model_id} uses self-hosted provider "
                    f"{provider_type!r} but has no endpoint_url configured"
                )

            logger.debug(f"Calling LLM for condition evaluation with model {litellm_model}")

            # Make the LLM call
            response = cast(Any, await litellm.acompletion(**litellm_params))
            content = response.choices[0].message.content or ""

            logger.debug(f"LLM condition evaluation response: {content[:100]}...")
            return content.strip()

        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            raise LLMConditionEvaluationError(f"LLM call failed: {e}") from e
