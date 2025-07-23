"""Helper classes and utilities for agent execution workflows."""

from datetime import UTC, datetime
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import uuid4

from .constants import MessageTemplates


class EventManager:
    """Manages workflow events with consistent formatting."""

    def __init__(self, task_id: str, agent_id: str, execution_id: str, publish_immediately: bool = True):
        self.task_id = task_id
        self.agent_id = agent_id
        self.execution_id = execution_id
        self.publish_immediately = publish_immediately
        self._events: list[dict[str, Any]] = []
        self._pending_events: list[dict[str, Any]] = []

    def add_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Add an event to the workflow event log."""
        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "task_id": self.task_id,
                "agent_id": self.agent_id,
                "execution_id": self.execution_id,
                **data
            }
        }
        self._events.append(event)

        if self.publish_immediately:
            # Add to pending events for immediate publishing
            self._pending_events.append(event)
            workflow.logger.debug(f"Added workflow event for immediate publishing: {event_type}")
        else:
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
    """Tracks budget usage and provides warnings."""

    def __init__(self, budget_usd: float | None = None):
        from .constants import BUDGET_WARNING_THRESHOLD, DEFAULT_BUDGET_USD

        self.budget_limit = budget_usd or DEFAULT_BUDGET_USD
        self.cost = 0.0
        self.warning_threshold = BUDGET_WARNING_THRESHOLD
        self._warning_sent = False

    def add_cost(self, amount: float) -> None:
        """Add cost to the current total."""
        self.cost += amount
        workflow.logger.info(f"Added cost: ${amount:.6f}, total: ${self.cost:.6f}")

    def get_remaining(self) -> float:
        """Get remaining budget."""
        return max(0.0, self.budget_limit - self.cost)

    def get_usage_percentage(self) -> float:
        """Get budget usage as percentage."""
        return (self.cost / self.budget_limit) * 100 if self.budget_limit > 0 else 0

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
            percentage=self.get_usage_percentage(),
            used=self.cost,
            total=self.budget_limit
        )

    def get_exceeded_message(self) -> str:
        """Get budget exceeded message."""
        return MessageTemplates.BUDGET_EXCEEDED.format(
            used=self.cost,
            total=self.budget_limit
        )


class MessageBuilder:
    """Builds consistent message formats."""

    @staticmethod
    def build_system_prompt(
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[dict[str, Any]],
        current_iteration: int,
        max_iterations: int,
        budget_remaining: float
    ) -> str:
        """Build system prompt with current context."""
        criteria_text = "\n".join(f"- {criteria}" for criteria in success_criteria)
        tools_text = "\n".join(f"- {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}"
                               for tool in available_tools)

        return MessageTemplates.SYSTEM_PROMPT.format(
            goal_description=goal_description,
            success_criteria=criteria_text,
            available_tools=tools_text,
            current_iteration=current_iteration,
            max_iterations=max_iterations,
            budget_remaining=budget_remaining
        )

    @staticmethod
    def build_tool_call_summary(tool_name: str, result: Any) -> str:
        """Build tool call summary message."""
        result_str = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
        return MessageTemplates.TOOL_CALL_SUMMARY.format(
            tool_name=tool_name,
            result=result_str
        )

    @staticmethod
    def build_iteration_summary(iteration: int, tool_calls: int, cost: float) -> str:
        """Build iteration summary message."""
        return MessageTemplates.ITERATION_SUMMARY.format(
            iteration=iteration,
            tool_calls=tool_calls,
            cost=cost
        )


class StateValidator:
    """Validates workflow state and provides error checking."""

    @staticmethod
    def validate_agent_config(config: dict[str, Any]) -> bool:
        """Validate agent configuration."""
        required_fields = ["id", "name", "model_id"]
        return all(field in config for field in required_fields)

    @staticmethod
    def validate_tools(tools: list[dict[str, Any]]) -> bool:
        """Validate available tools."""
        if not tools:
            return True  # Empty tools list is valid

        required_fields = ["name", "description"]
        return all(
            all(field in tool for field in required_fields)
            for tool in tools
        )

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
    def extract_tool_calls(message: Any) -> list[dict[str, Any]]:
        """Extract tool calls from LLM response message."""
        if not hasattr(message, 'tool_calls') or not message.tool_calls:
            return []

        return [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]

    @staticmethod
    def extract_usage_info(response: Any) -> dict[str, Any]:
        """Extract usage and cost information from LLM response."""
        usage_info = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        }

        if not hasattr(response, 'usage') or not response.usage:
            return usage_info

        usage = response.usage
        usage_info.update({
            "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
            "completion_tokens": getattr(usage, 'completion_tokens', 0),
            "total_tokens": getattr(usage, 'total_tokens', 0),
        })

        # Calculate cost
        cost = 0.0
        if hasattr(usage, 'completion_tokens_cost'):
            cost += getattr(usage, 'completion_tokens_cost', 0.0)
        if hasattr(usage, 'prompt_tokens_cost'):
            cost += getattr(usage, 'prompt_tokens_cost', 0.0)
        elif hasattr(usage, 'total_tokens'):
            # Fallback estimate: $0.01 per 1K tokens
            cost = getattr(usage, 'total_tokens', 0) * 0.00001

        usage_info["cost"] = cost
        return usage_info
