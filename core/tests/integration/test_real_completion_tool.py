"""Test the real completion tool from agents SDK to ensure it works correctly."""

import pytest
from agentarea_agents_sdk.tools.completion_tool import CompletionTool


class TestRealCompletionTool:
    """Test the real completion tool implementation."""

    @pytest.mark.asyncio
    async def test_completion_tool_execution(self):
        """Test that the completion tool executes correctly."""
        tool = CompletionTool()

        # Test basic properties
        assert tool.name == "task_complete"
        assert "completed" in tool.description.lower()

        # Test execution with result
        result = await tool.execute(result="Task completed successfully")

        # Verify the result structure matches what workflow expects
        assert result.get("success") is True, f"Expected success=True, got {result.get('success')}"
        assert result.get("completed") is True, (
            f"Expected completed=True, got {result.get('completed')}"
        )
        assert result.get("result") == "Task completed successfully"
        assert result.get("tool_name") == "task_complete"
        assert result.get("error") is None

        print(f"Completion tool result: {result}")

    @pytest.mark.asyncio
    async def test_completion_tool_execution_no_args(self):
        """Test that the completion tool works with no arguments."""
        tool = CompletionTool()

        # Test execution without arguments
        result = await tool.execute()

        # Should still work with default message
        assert result.get("success") is True
        assert result.get("completed") is True
        assert "completed successfully" in result.get("result", "").lower()

        print(f"Completion tool result (no args): {result}")

    def test_completion_tool_openai_function_definition(self):
        """Test that the completion tool provides correct OpenAI function definition."""
        tool = CompletionTool()
        function_def = tool.get_openai_function_definition()

        assert isinstance(function_def, dict)
        assert function_def.get("type") == "function"
        assert "function" in function_def

        function_info = function_def["function"]
        assert function_info.get("name") == "task_complete"
        assert "description" in function_info
        assert "parameters" in function_info

        # Parameters should be optional
        params = function_info["parameters"]
        assert params.get("required") == []  # No required parameters

        print(f"OpenAI function definition: {function_def}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
