"""Helper classes and utilities for agent execution workflows."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    decide_tool_policy,
)
from agentarea_common.events.contract import canonical_type, ensure_terminal_message
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import uuid4

    from agentarea_common.money import ZERO, Money, to_money

from agentarea_agents_sdk.prompts import MessageTemplates, PromptBuilder


def resolve_effective_budget(
    request_budget: Money | None,
    effective_policy: dict[str, Any] | None,
    key: str = "run_budget_usd",
) -> Money | None:
    """Single source of truth for the run budget.

    The per-request ``request.budget_usd`` and the governance policy ceiling
    (``effective_policy.budget.run_budget_usd``) are reconciled so the
    loop-level PEP (BudgetTracker) and the call-level PEP (CostBudgetGuard)
    enforce the same number. The tightest of the two wins — a lower ceiling
    can never be loosened by the other source.
    """
    policy_budget = None
    if effective_policy:
        policy_budget = (effective_policy.get("budget") or {}).get(key)

    candidates = [to_money(b) for b in (request_budget, policy_budget) if b is not None]
    if not candidates:
        return None
    return min(candidates)


def policy_requires_approval(effective_policy: dict[str, Any] | None, tool_name: str) -> bool:
    """Whether a tool call needs human approval — driven solely by ApprovalPolicy.

    The policy engine is the single source of truth: either approval is required
    globally (``requires_human_approval``) or the tool is explicitly listed in
    ``escalation_rules``. When approval is required the workflow pauses on the
    existing human-in-the-loop path (HUMAN_APPROVAL_REQUESTED -> resolve_escalation).
    """
    approval = (effective_policy or {}).get("approval") or {}
    if approval.get("requires_human_approval") is True:
        return True
    return tool_name in (approval.get("escalation_rules") or [])


def policy_approvers(effective_policy: dict[str, Any] | None) -> list[str]:
    """Global subject refs allowed to approve, from ApprovalPolicy.approvers."""
    return list(((effective_policy or {}).get("approval") or {}).get("approvers") or [])


def approvers_for_tool(effective_policy: dict[str, Any] | None, tool_name: str) -> list[str]:
    """Subject refs allowed to approve a specific tool.

    Per-tool approvers (ApprovalPolicy.approvers_by_tool) win when present, so a
    tool signed off by one team does not inherit another tool's approvers. Falls
    back to the global approvers list, and finally to empty (any member — the
    existing soft default, see issue #198).
    """
    approval = (effective_policy or {}).get("approval") or {}
    per_tool = (approval.get("approvers_by_tool") or {}).get(tool_name)
    if per_tool:
        return list(per_tool)
    return list(approval.get("approvers") or [])


class ToolAction(StrEnum):
    """Verdict of the tool-call policy decision (single PEP for every tool)."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


def decide_tool_action(effective_policy: dict[str, Any] | None, tool_name: str) -> ToolAction:
    """Deterministic workflow preflight view of the tool authorization PDP."""
    decision = decide_tool_policy(effective_policy, tool_name)
    if decision.action is ToolAuthorizationAction.ALLOW:
        return ToolAction.ALLOW
    if decision.action is ToolAuthorizationAction.REQUIRE_APPROVAL:
        return ToolAction.REQUIRE_APPROVAL
    return ToolAction.DENY


# Workflow control flow, not capabilities: these tools reach no external system,
# are never policy-gated on execution, and must survive a deny-by-default policy
# — without completion the agent can never finish, without request_user_input it
# can never ask. Keep in sync with the ungated branches of _execute_tool_calls.
CONTROL_FLOW_TOOLS = frozenset(
    {
        "completion",
        "task_complete",
        "request_user_input",
        "recall_history",
        "read_tool_output",
        "activate_tool_source",
        "load_tools",
    }
)


def tool_definition_name(tool: dict[str, Any]) -> str | None:
    """Read a tool's name from either definition shape (OpenAI function or bare)."""
    if tool.get("type") == "function":
        return cast(dict[str, Any], tool.get("function") or {}).get("name")
    return tool.get("name")


def filter_disclosed_tools(
    effective_policy: dict[str, Any] | None, tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Offer the model only the capability tools policy would actually let it call.

    Disclosure is a PDP decision, not a presentation detail: showing a tool the
    gate will reject pollutes the context with capabilities the agent cannot
    have and invites calls that can only fail. Tools needing approval stay
    disclosed — the gate escalates them to a human rather than rejecting them.
    """
    disclosed: list[dict[str, Any]] = []
    for tool in tools:
        name = tool_definition_name(tool)
        if not name:
            continue
        if name in CONTROL_FLOW_TOOLS:
            disclosed.append(tool)
            continue
        if decide_tool_action(effective_policy, name) is not ToolAction.DENY:
            disclosed.append(tool)
    return disclosed


def caller_can_approve(approvers: list[str], caller_user_id: str) -> bool:
    """Whether the caller may resolve an escalation.

    Empty ``approvers`` is the soft default — any workspace member may approve
    (see issue #198 for the zero-trust posture). Otherwise the caller must be a
    direct user subject ``user:<id>``. Group/userset subjects are stored but not
    resolved until a membership/roles model exists, so they do not grant approval.
    """
    if not approvers:
        return True
    return bool(caller_user_id) and f"user:{caller_user_id}" in approvers


_EVENT_CONTENT_KEYS = frozenset(
    {
        "base64",
        "blob",
        "body",
        "bytes",
        "code",
        "content",
        "contents",
        "data",
        "file_content",
        "payload",
        "result",
        "script",
        "stderr",
        "stdout",
    }
)
_EVENT_SECRET_KEYS = frozenset(
    {"api_key", "authorization", "credential", "password", "secret", "token"}
)
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/=_-]{256,}$")
_MAX_EVENT_STRING_CHARS = 2000


def _event_omission(value: Any) -> str:
    size = len(value) if isinstance(value, str | bytes | bytearray) else 0
    return f"[omitted from event log: {size} units]"


def _looks_binary_or_bulk(value: str) -> bool:
    if len(value) > _MAX_EVENT_STRING_CHARS or _BASE64_LIKE.fullmatch(value):
        return True
    if "\x00" in value:
        return True
    controls = sum(ord(character) < 32 and character not in "\n\r\t" for character in value)
    return bool(value) and controls / len(value) > 0.02


def sanitize_tool_event_value(value: Any, *, field_name: str = "", _depth: int = 0) -> Any:
    """Bound event metadata without file bodies, secrets, or binary blobs.

    This helper applies only to Redis/DB event projections. Activities and the
    LLM still receive the original tool arguments and results.
    """
    if _depth >= 10:
        return "[nested value omitted from event log]"
    normalized_name = field_name.lower()
    if any(fragment in normalized_name for fragment in _EVENT_SECRET_KEYS):
        return "[redacted]"
    if normalized_name in _EVENT_CONTENT_KEYS:
        return _event_omission(value)
    if normalized_name == "command":
        return _event_omission(value)
    if isinstance(value, str):
        return _event_omission(value) if _looks_binary_or_bulk(value) else value
    if isinstance(value, bytes | bytearray):
        return _event_omission(value)
    if isinstance(value, dict):
        return {
            str(key): sanitize_tool_event_value(
                item, field_name=str(key), _depth=_depth + 1
            )
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list | tuple):
        return [sanitize_tool_event_value(item, _depth=_depth + 1) for item in value[:100]]
    if value is None or isinstance(value, bool | int | float):
        return value
    return f"[{type(value).__name__} omitted from event log]"


def _bounded_llm_display_content(value: Any) -> str:
    if not isinstance(value, str):
        return str(sanitize_tool_event_value(value, field_name="llm_content"))
    if len(value) <= _MAX_EVENT_STRING_CHARS:
        return value
    omitted = len(value) - _MAX_EVENT_STRING_CHARS
    return f"{value[:_MAX_EVENT_STRING_CHARS]}\n[truncated {omitted} characters from event log]"


def _sanitize_llm_completed_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keep display text useful while making nested LLM event data bounded."""
    sanitized = dict(data)
    sanitized["content"] = _bounded_llm_display_content(data.get("content", ""))
    sanitized["tool_calls"] = sanitize_tool_event_value(data.get("tool_calls", []))
    if "thinking" in sanitized:
        sanitized["thinking"] = sanitize_tool_event_value(
            sanitized["thinking"], field_name="thinking"
        )
    return sanitized


class EventManager:
    """Manages workflow events with consistent formatting."""

    def __init__(
        self, task_id: str, agent_id: str, execution_id: str, publish_immediately: bool = True
    ):
        self.task_id = task_id
        self.agent_id = agent_id
        self.execution_id = execution_id
        self.publish_immediately = publish_immediately
        self._events: list[dict[str, Any]] = []
        self._pending_events: list[dict[str, Any]] = []

    def add_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Add an event to the workflow event log.

        The ``EventTypes`` constants already hold canonical dotted names, so the
        wire speaks one vocabulary. ``canonical_type`` is applied defensively
        (it only strips a leading ``workflow.`` prefix; a no-op for canonical
        inputs).

        Terminal events (completed/failed/cancelled) get a user-facing
        ``message`` (and ``reason``) so a client attaching after completion
        renders the final state from catch-up alone. No-op for other types.
        """
        event_type = canonical_type(event_type)
        if event_type == "llm.call.completed":
            data = _sanitize_llm_completed_data(data)
        elif event_type == "tool.result":
            sanitized = sanitize_tool_event_value(data)
            if not isinstance(sanitized, dict):
                raise ValueError("tool result event data must be a mapping")
            data = sanitized
        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": ensure_terminal_message(
                event_type,
                {
                    "task_id": self.task_id,
                    "agent_id": self.agent_id,
                    "execution_id": self.execution_id,
                    **data,
                },
            ),
        }
        if self.publish_immediately:
            # Add only to pending events for immediate publishing; NOT to _events
            # to avoid publishing the same event twice (once immediately, once in
            # the regular publish cycle that drains _events).
            self._pending_events.append(event)
            workflow.logger.debug(f"Added workflow event for immediate publishing: {event_type}")
        else:
            self._events.append(event)
            workflow.logger.debug(f"Added workflow event: {event_type}")

    def get_events(self) -> list[dict[str, Any]]:
        """Get all workflow events."""
        return self._events.copy()

    def get_latest_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the latest workflow events."""
        return self._events[-limit:] if self._events else []

    def get_pending_events(self) -> list[dict[str, Any]]:
        """Get pending events that need to be published immediately."""
        return self._pending_events.copy()

    def clear_pending_events(self) -> None:
        """Clear pending events (called after immediate publishing)."""
        self._pending_events.clear()

    def clear_events(self) -> None:
        """Clear all events (called after publishing)."""
        self._events.clear()


class BudgetTracker:
    """Tracks budget usage and provides warnings.

    All monetary values use the Money type (Decimal) internally.
    Use serialize_money() when putting values into dicts/events.
    """

    def __init__(
        self,
        budget_usd: Money | float | None = None,
        service_budget_usd: Money | float | None = None,
    ):
        from .constants import BUDGET_WARNING_THRESHOLD, DEFAULT_BUDGET_USD

        self.budget_limit: Money = to_money(budget_usd or DEFAULT_BUDGET_USD)
        self.cost: Money = ZERO
        self.warning_threshold = BUDGET_WARNING_THRESHOLD
        self._warning_sent = False
        # Service budget tracking
        self._service_limit: Money = to_money(service_budget_usd or 0)
        self._service_cost: Money = ZERO
        self._service_warning_sent = False

    def add_cost(self, amount: Money | float) -> None:
        """Add cost to the current total."""
        added = to_money(amount)
        self.cost += added
        workflow.logger.info(f"Added cost: ${added}, total: ${self.cost}")

    def set_limit(self, amount: Money | float) -> None:
        """Replace the inference budget with a validated positive limit."""
        limit = to_money(amount)
        if limit <= ZERO:
            raise ValueError("budget limit must be greater than zero")
        self.budget_limit = limit
        self._warning_sent = False

    def add_budget(self, amount: Money | float) -> None:
        """Increase the inference budget without changing accumulated cost."""
        additional = to_money(amount)
        if additional <= ZERO:
            raise ValueError("additional budget must be greater than zero")
        self.budget_limit += additional
        self._warning_sent = False

    def get_remaining(self) -> Money:
        """Get remaining budget."""
        return max(ZERO, self.budget_limit - self.cost)

    def get_usage_percentage(self) -> float:
        """Get budget usage as percentage."""
        return float(self.cost / self.budget_limit) * 100 if self.budget_limit > 0 else 0

    def is_exceeded(self) -> bool:
        """Check if budget is exceeded."""
        return self.cost >= self.budget_limit

    def should_warn(self) -> bool:
        """Check if budget warning should be sent."""
        usage_percent = self.get_usage_percentage() / 100
        return usage_percent >= self.warning_threshold and not self._warning_sent

    def mark_warning_sent(self) -> None:
        """Mark that warning has been sent."""
        self._warning_sent = True

    def get_warning_message(self) -> str:
        """Get budget warning message."""
        return MessageTemplates.BUDGET_WARNING.format(
            percentage=self.get_usage_percentage(), used=self.cost, total=self.budget_limit
        )

    def get_exceeded_message(self) -> str:
        """Get budget exceeded message."""
        return MessageTemplates.BUDGET_EXCEEDED.format(used=self.cost, total=self.budget_limit)

    # --- Service budget tracking ---

    def add_service_cost(self, amount: float) -> None:
        """Track a service payment cost."""
        self._service_cost += to_money(amount)
        workflow.logger.info(f"Added service cost: ${amount:.6f}, total: ${self._service_cost}")

    def get_service_remaining(self) -> Money:
        """Get remaining service budget."""
        if self._service_limit <= 0:
            return to_money("Infinity")
        return max(ZERO, self._service_limit - self._service_cost)

    def is_service_exceeded(self) -> bool:
        """Check if service budget is exhausted."""
        if self._service_limit <= 0:
            return False
        return self._service_cost >= self._service_limit

    def should_warn_service(self) -> bool:
        """Check if service budget warning should be sent."""
        if self._service_limit <= 0:
            return False
        return (
            float(self._service_cost / self._service_limit)
        ) >= self.warning_threshold and not self._service_warning_sent

    def mark_service_warning_sent(self) -> None:
        """Mark that service budget warning has been sent."""
        self._service_warning_sent = True

    @property
    def service_cost(self) -> Money:
        """Get total service cost."""
        return self._service_cost


class MessageBuilder:
    """Enhanced message builder with ReAct framework support.

    Provides improved prompting strategies including ReAct (Reasoning + Acting) framework
    for better agent reasoning and decision-making.
    """

    @staticmethod
    def normalize_message_dict(message_dict: dict[str, Any]) -> dict[str, Any]:
        """Normalize message dict by removing None values to match agent SDK format.

        This ensures consistent message formatting between the agent SDK and execution workflow.
        The agent SDK only includes fields with actual values, so we follow the same pattern.

        Args:
            message_dict: Raw message dictionary that may contain None values

        Returns:
            Normalized message dictionary with None values filtered out
        """
        normalized = {
            "role": message_dict["role"],
            "content": message_dict["content"],
        }

        # Only add optional fields if they have actual values (not None)
        optional_fields = ["tool_call_id", "name", "tool_calls"]
        for field in optional_fields:
            if field in message_dict and message_dict[field] is not None:
                normalized[field] = message_dict[field]

        return normalized

    @staticmethod
    def build_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[dict[str, Any]],
        a2ui_enabled: bool = False,
    ) -> str:
        """Build system prompt with ReAct framework instructions."""
        return PromptBuilder.build_react_system_prompt(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=success_criteria,
            available_tools=cast(Any, available_tools),
            a2ui_enabled=a2ui_enabled,
        )

    @staticmethod
    def build_tool_call_summary(tool_name: str, result: Any) -> str:
        """Build tool call summary message."""
        return PromptBuilder.build_tool_call_summary(tool_name, result)

    @staticmethod
    def build_iteration_summary(iteration: int, tool_calls: int, cost: float) -> str:
        """Build iteration summary message."""
        return PromptBuilder.build_iteration_summary(iteration, tool_calls, cost)


def build_output_summary(content: str, output_id: str) -> str:
    """Create a compact summary of a large tool output with reference to stored version."""
    from .constants import OUTPUT_SUMMARY_HEAD_CHARS, OUTPUT_SUMMARY_TAIL_CHARS

    lines = content.split("\n")
    head = content[:OUTPUT_SUMMARY_HEAD_CHARS]
    total_chars = len(content)
    total_lines = len(lines)

    summary = f"[Output stored as {output_id} — {total_chars:,} chars, {total_lines} lines]\n"
    summary += f"Preview:\n{head}\n"

    if total_chars > OUTPUT_SUMMARY_HEAD_CHARS + OUTPUT_SUMMARY_TAIL_CHARS:
        tail = content[-OUTPUT_SUMMARY_TAIL_CHARS:]
        summary += f"...\n{tail}\n"

    summary += (
        f'\nUse read_tool_output("{output_id}") for full content, '
        f'or read_tool_output("{output_id}", grep="pattern") to search.'
    )
    return summary


class StateValidator:
    """Validates workflow state and provides error checking."""

    @staticmethod
    def validate_agent_config(config: dict[str, Any]) -> bool:
        """Validate agent configuration."""
        required_fields = ["id", "name", "model_id"]
        return all(field in config for field in required_fields)

    @staticmethod
    def validate_tools(tools: list[dict[str, Any]]) -> bool:
        """Validate available tools (supports both old format and OpenAI function format)."""
        if not tools:
            return True  # Empty tools list is valid

        for tool in tools:
            # Check if it's OpenAI function format
            if tool.get("type") == "function" and "function" in tool:
                function_def = tool["function"]
                if not function_def.get("name") or not function_def.get("description"):
                    return False
            # Check if it's old format
            elif "name" in tool and "description" in tool:
                continue  # Valid old format
            else:
                return False  # Invalid format
        return True

    @staticmethod
    def validate_goal(goal: dict[str, Any]) -> bool:
        """Validate goal structure."""
        required_fields = ["description", "success_criteria", "max_iterations"]
        return all(field in goal for field in required_fields)

    # Note: should_continue_execution method moved to workflow class
    # for better access to workflow state and more comprehensive checking


class ToolCallExtractor:
    """Extracts and formats tool calls from LLM responses."""

    @staticmethod
    def extract_tool_calls(message: Any) -> list[Any]:
        """Extract tool calls from LLM response message and return ToolCall objects.

        Handles multiple formats:
        1. Standard format: tool_calls field contains proper tool call objects
        2. Malformed format: tool_calls is null but content contains JSON tool call data
        3. Mixed format: content contains tool call JSON strings
        """
        # Import here to avoid circular imports
        import json
        import re

        from ..workflows.agent_execution_workflow import ToolCall

        # Handle both dataclass and dict formats
        tool_calls = None
        content = None

        if hasattr(message, "tool_calls"):
            tool_calls = message.tool_calls
        elif isinstance(message, dict) and "tool_calls" in message:
            tool_calls = message["tool_calls"]

        if not isinstance(message, dict) and hasattr(message, "content"):
            content = message.content
        elif isinstance(message, dict) and "content" in message:
            content = message["content"]

        result = []

        # Method 1: Extract from proper tool_calls field
        if tool_calls:
            for i, tool_call in enumerate(tool_calls):
                if isinstance(tool_call, dict):
                    # Handle dict format from LLM activity
                    result.append(
                        ToolCall(
                            id=tool_call.get("id", f"call_{i}"),
                            type=tool_call.get("type", "function"),
                            function={
                                "name": tool_call.get("function", {}).get("name", ""),
                                "arguments": tool_call.get("function", {}).get("arguments", "{}"),
                            },
                        )
                    )
                else:
                    # Handle object format (if any)
                    result.append(
                        ToolCall(
                            id=getattr(tool_call, "id", f"call_{i}"),
                            type=getattr(tool_call, "type", "function"),
                            function={
                                "name": getattr(tool_call.function, "name", ""),
                                "arguments": getattr(tool_call.function, "arguments", "{}"),
                            },
                        )
                    )

        # Method 2: Extract from malformed content field (for production bug)
        if not result and content and isinstance(content, str):
            try:
                # Try to parse the entire content as JSON (case 1: pure JSON tool call)
                parsed_content = json.loads(content.strip())
                if isinstance(parsed_content, dict) and "name" in parsed_content:
                    # This looks like a tool call
                    arguments = parsed_content.get("arguments", {})
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments)
                    elif not isinstance(arguments, str):
                        arguments = json.dumps(arguments)

                    result.append(
                        ToolCall(
                            id="call_from_content_0",
                            type="function",
                            function={"name": parsed_content["name"], "arguments": arguments},
                        )
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                # Method 3: Extract using regex patterns for embedded JSON
                try:
                    # Look for JSON-like patterns in content
                    # Pattern 1: {"name": "tool_name", "arguments": {...}}
                    json_pattern = r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\}|\{[^}]*\})\s*\}'
                    matches = re.findall(json_pattern, content)

                    for i, (tool_name, args_str) in enumerate(matches):
                        try:
                            # Validate arguments JSON
                            json.loads(args_str)
                            result.append(
                                ToolCall(
                                    id=f"call_from_regex_{i}",
                                    type="function",
                                    function={"name": tool_name, "arguments": args_str},
                                )
                            )
                        except json.JSONDecodeError:
                            # If arguments aren't valid JSON, wrap them
                            result.append(
                                ToolCall(
                                    id=f"call_from_regex_{i}",
                                    type="function",
                                    function={
                                        "name": tool_name,
                                        "arguments": json.dumps({"raw_args": args_str}),
                                    },
                                )
                            )

                    # Pattern 2: Look for task_complete specifically (common case)
                    if not result and "task_complete" in content.lower():
                        # Extract any JSON-like arguments
                        args_pattern = r'"arguments"\s*:\s*(\{[^}]*\})'
                        args_match = re.search(args_pattern, content)

                        if args_match:
                            args_str = args_match.group(1)
                        else:
                            # No arguments found, use empty object
                            args_str = "{}"

                        result.append(
                            ToolCall(
                                id="call_task_complete_fallback",
                                type="function",
                                function={"name": "task_complete", "arguments": args_str},
                            )
                        )

                except Exception:
                    # If all parsing fails, but we detect task_complete, create a basic call
                    if "task_complete" in content.lower():
                        result.append(
                            ToolCall(
                                id="call_task_complete_emergency",
                                type="function",
                                function={"name": "task_complete", "arguments": "{}"},
                            )
                        )

        return result

    @staticmethod
    def extract_usage_info(response: Any) -> dict[str, Any]:
        """Extract usage and cost information from LLM response."""
        usage_info = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}

        if not hasattr(response, "usage") or not response.usage:
            return usage_info

        usage = response.usage
        usage_info.update(
            {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            }
        )

        # Calculate cost — try multiple sources
        cost = 0.0

        # LiteLLM stores cost in _hidden_params.response_cost
        if hasattr(response, "_hidden_params"):
            hidden = response._hidden_params
            if isinstance(hidden, dict):
                cost = hidden.get("response_cost", 0.0) or 0.0
            elif hasattr(hidden, "response_cost"):
                cost = getattr(hidden, "response_cost", 0.0) or 0.0

        # Try usage-level cost attributes
        if cost == 0.0 and hasattr(usage, "completion_tokens_cost"):
            cost += getattr(usage, "completion_tokens_cost", 0.0) or 0.0
        if cost == 0.0 and hasattr(usage, "prompt_tokens_cost"):
            cost += getattr(usage, "prompt_tokens_cost", 0.0) or 0.0

        # Fallback estimate: $0.01 per 1K tokens
        if cost == 0.0 and getattr(usage, "total_tokens", 0):
            cost = getattr(usage, "total_tokens", 0) * 0.00001

        usage_info["cost"] = cost
        return usage_info
