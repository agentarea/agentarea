"""Completion tool for agents to signal task completion."""

from typing import Any

from .base_tool import BaseTool


class CompletionTool(BaseTool):
    """Tool that allows agents to explicitly signal task completion.

    This follows patterns from AutoGen (TERMINATE) and other agentic frameworks
    for explicit completion signaling.
    """

    @property
    def name(self) -> str:
        return "task_complete"

    @property
    def description(self) -> str:
        return "Mark task as completed when you have finished the task successfully. Call this when you're done."

    def get_schema(self) -> dict[str, Any]:
        """Get the tool parameter schema."""
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "Optional final result or summary of what was accomplished"
                    }
                },
                "required": []  # No required parameters - LLM can call with no args
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the completion tool.

        Args:
            **kwargs: Optional tool arguments - LLM can call with no parameters

        Returns:
            Dict containing completion information
        """
        result = kwargs.get("result", "Task completed successfully")

        return {
            "success": True,
            "result": result,
            "completed": True,
            "tool_name": self.name,
            "error": None,
        }
