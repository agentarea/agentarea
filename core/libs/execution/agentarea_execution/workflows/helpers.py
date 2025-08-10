"""Helper classes and utilities for agent execution workflows."""

from datetime import UTC, datetime
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import uuid4

from agentarea_agents_sdk.prompts import MessageTemplates, PromptBuilder


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
    """Enhanced message builder with ReAct framework support.
    
    Provides improved prompting strategies including ReAct (Reasoning + Acting) framework
    for better agent reasoning and decision-making.
    """

    @staticmethod
    def build_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[dict[str, Any]]
    ) -> str:
        """Build system prompt with ReAct framework instructions."""
        return PromptBuilder.build_react_system_prompt(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=success_criteria,
            available_tools=available_tools
        )

    @staticmethod
    def build_tool_call_summary(tool_name: str, result: Any) -> str:
        """Build tool call summary message."""
        return PromptBuilder.build_tool_call_summary(tool_name, result)

    @staticmethod
    def build_iteration_summary(iteration: int, tool_calls: int, cost: float) -> str:
        """Build iteration summary message."""
        return PromptBuilder.build_iteration_summary(iteration, tool_calls, cost)


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
        """Extract tool calls from LLM response message and return ToolCall objects."""
        # Import here to avoid circular imports
        from ..workflows.agent_execution_workflow import ToolCall

        # Handle both dataclass and dict formats
        tool_calls = None
        if hasattr(message, 'tool_calls'):
            tool_calls = message.tool_calls
        elif isinstance(message, dict) and 'tool_calls' in message:
            tool_calls = message['tool_calls']

        if not tool_calls:
            return []

        # Convert to ToolCall dataclass objects
        result = []
        for i, tool_call in enumerate(tool_calls):
            if isinstance(tool_call, dict):
                # Handle dict format from LLM activity
                result.append(ToolCall(
                    id=tool_call.get("id", f"call_{i}"),
                    type=tool_call.get("type", "function"),
                    function={
                        "name": tool_call.get("function", {}).get("name", ""),
                        "arguments": tool_call.get("function", {}).get("arguments", "{}"),
                    }
                ))
            else:
                # Handle object format (if any)
                result.append(ToolCall(
                    id=getattr(tool_call, 'id', f"call_{i}"),
                    type=getattr(tool_call, 'type', "function"),
                    function={
                        "name": getattr(tool_call.function, 'name', ''),
                        "arguments": getattr(tool_call.function, 'arguments', '{}'),
                    }
                ))

        return result

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
