"""Completion tool for agents to signal task completion."""

from .decorator_tool import Toolset, tool_method


class CompletionTool(Toolset):
    """Mark task as completed when you have finished the task successfully."""

    @tool_method
    def complete(self, result: str | None = "Task completed successfully") -> str:
        """Signal task completion with optional result summary.

        Args:
            result: Optional final result or summary of what was accomplished

        Returns:
            Completion message
        """
        return result
