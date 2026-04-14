"""Completion tool for agents to signal task completion."""

from .decorator_tool import Toolset, tool_method


class CompletionTool(Toolset):
    """Finish the task and send your response to the user. The 'result' parameter is the message the user will see — write it as a complete, helpful answer (not a summary or status). You MUST call this tool when you are done."""

    @tool_method
    def complete(self, result: str) -> str:
        """Present your final answer to the user.

        Args:
            result: Your complete response to the user. This text is shown directly to them.

        Returns:
            The response text
        """
        return result
