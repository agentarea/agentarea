"""Service for evaluating goal progress and completion detection."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GoalProgressEvaluator:
    """Service for evaluating progress toward agent goals."""

    async def evaluate_progress(
        self,
        goal_description: str,
        success_criteria: list[str],
        conversation_history: list[dict[str, Any]],
        current_iteration: int,
    ) -> dict[str, Any]:
        """Evaluate progress toward the goal.

        Args:
            goal_description: Description of the goal
            success_criteria: List of success criteria
            conversation_history: List of conversation messages
            current_iteration: Current iteration count

        Returns:
            Dict containing evaluation results
        """
        # Convert to old format for compatibility
        goal = {"description": goal_description, "success_criteria": success_criteria}
        return self._evaluate_progress_internal(goal, conversation_history, current_iteration)

    def _evaluate_progress_internal(
        self,
        goal: dict[str, Any],
        messages: list[dict[str, Any]],
        current_iteration: int,
    ) -> dict[str, Any]:
        """Internal evaluation logic."""
        try:
            # Analyze the conversation to determine if goal is achieved
            goal_achieved = False
            final_response = None
            completion_method = None

            if messages:
                # Check if the last few messages indicate task completion
                recent_messages = messages[-5:]  # Look at last 5 messages

                # Method 1: Check for explicit completion tool calls
                goal_achieved, final_response, completion_method = self._check_explicit_completion(
                    recent_messages
                )

                # Method 2: Check for single completion word (fallback for simple LLMs)
                if not goal_achieved:
                    goal_achieved, final_response, completion_method = (
                        self._check_single_word_completion(recent_messages)
                    )

                # Method 3: Fallback - check successful tool executions
                if not goal_achieved:
                    goal_achieved, final_response, completion_method = (
                        self._check_tool_pattern_completion(recent_messages)
                    )

            # Evaluate against success criteria if available
            success_criteria_met = self._evaluate_success_criteria(goal, messages)

            return {
                "goal_achieved": goal_achieved,
                "final_response": final_response,
                "completion_method": completion_method,
                "success_criteria_met": success_criteria_met,
                "progress_indicators": {
                    "message_count": len(messages),
                    "tool_calls": sum(1 for msg in messages if msg.get("role") == "tool"),
                    "assistant_responses": sum(
                        1 for msg in messages if msg.get("role") == "assistant"
                    ),
                    "iteration": current_iteration,
                },
            }

        except Exception as e:
            logger.error(f"Failed to evaluate goal progress: {e}")
            return {
                "goal_achieved": False,
                "final_response": None,
                "completion_method": None,
                "success_criteria_met": [],
                "progress_indicators": {"error": str(e)},
            }

    def _check_explicit_completion(
        self, recent_messages: list[dict[str, Any]]
    ) -> tuple[bool, str | None, str | None]:
        """Check for explicit completion tool calls."""
        for message in reversed(recent_messages):
            if message.get("role") == "tool" and message.get("name") == "completion":
                # Found completion tool call - parse the result
                tool_content = message.get("content", "")
                if isinstance(tool_content, dict):
                    if tool_content.get("completed", False):
                        return (
                            True,
                            tool_content.get("result", "Task completed via tool"),
                            "explicit_tool",
                        )
                elif "completed" in str(tool_content) or "success" in str(tool_content):
                    # Tool call detected, assume completion
                    return True, str(tool_content), "explicit_tool"
        return False, None, None

    def _check_single_word_completion(
        self, recent_messages: list[dict[str, Any]]
    ) -> tuple[bool, str | None, str | None]:
        """Check for single completion word (fallback for simple LLMs)."""
        for message in reversed(recent_messages):
            if message.get("role") == "assistant":
                content = message.get("content", "").upper()

                # Single unique completion word - easy for any LLM
                if "TASKDONE" in content:
                    return True, message.get("content", "Task completed"), "single_word"
        return False, None, None

    def _check_tool_pattern_completion(
        self, recent_messages: list[dict[str, Any]]
    ) -> tuple[bool, str | None, str | None]:
        """Check successful tool executions for completion patterns."""
        tool_successes = sum(
            1
            for msg in recent_messages
            if msg.get("role") == "tool"
            and "error" not in str(msg.get("content", "")).lower()
            and msg.get("name") != "completion"  # Don't count completion tool
        )

        if tool_successes >= 2:  # Multiple successful tool calls might indicate progress
            # Check if assistant is providing a summary or conclusion
            for message in reversed(recent_messages):
                if message.get("role") == "assistant" and len(message.get("content", "")) > 50:
                    content = message.get("content", "")
                    if any(word in content.lower() for word in ["summary", "result", "conclusion"]):
                        return True, content, "inference"
        return False, None, None

    def _evaluate_success_criteria(
        self, goal: dict[str, Any], messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Evaluate against success criteria if available."""
        success_criteria_met = []
        if goal.get("success_criteria"):
            # This is a simplified evaluation - could be enhanced with LLM analysis
            for criteria in goal["success_criteria"]:
                # Simple keyword matching for now
                criteria_met = any(
                    keyword in " ".join(msg.get("content", "") for msg in messages[-5:]).lower()
                    for keyword in criteria.lower().split()[:3]  # First 3 words of criteria
                )
                success_criteria_met.append({"criteria": criteria, "met": criteria_met})
        return success_criteria_met
