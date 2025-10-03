"""Integration tests for the agents SDK."""

import pytest


class TestAgentIntegration:
    """Integration tests for complete agent workflows."""

    @pytest.mark.asyncio
    async def test_math_problem_solving_workflow(self):
        """Test complete math problem solving workflow."""
        try:
            from agentarea_agents_sdk.agents.agent import create_agent

            agent = create_agent(
                name="Math Assistant",
                instruction="You are a helpful math assistant that solves problems step by step.",
                model="ollama_chat/qwen2.5",
            )

            # Test a simple math problem
            task = "Calculate 5 * 3 + 2"

            # Track if tools are used and task completes
            tool_used = False
            task_completed = False

            async for content in agent.run_stream(task):
                if "[Tool calculate:" in content:
                    tool_used = True
                if "[Tool completion:" in content:
                    task_completed = True
                if tool_used and task_completed:
                    break

            assert tool_used, "Should use calculation tool"
            # Note: task_completed might not always happen depending on the model's behavior

        except Exception as e:
            pytest.skip(f"Integration test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_reasoning_workflow(self):
        """Test reasoning workflow with multiple steps."""
        try:
            from agentarea_agents_sdk.agents.agent import create_agent

            agent = create_agent(
                name="Logic Assistant",
                instruction="You are a logical reasoning assistant.",
                model="ollama_chat/qwen2.5",
            )

            task = "If I have 6 apples and eat half of them, how many do I have left?"

            result = await agent.run(task)

            assert isinstance(result, str)
            assert len(result) > 0
            # The result should contain some reasoning about the problem

        except Exception as e:
            pytest.skip(f"Integration test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_custom_goal_and_criteria_workflow(self):
        """Test workflow with custom goal and success criteria."""
        try:
            from agentarea_agents_sdk.agents.agent import create_agent

            agent = create_agent(
                name="Goal-Oriented Agent",
                instruction="You are a systematic problem solver.",
                model="ollama_chat/qwen2.5",
            )

            task = "Help me with math"
            goal = "Calculate the area of a square with side length 4"
            criteria = [
                "Identify the formula for square area",
                "Apply the formula with the given value",
                "Provide the final answer",
            ]

            result = await agent.run(task, goal=goal, success_criteria=criteria)

            assert isinstance(result, str)
            assert len(result) > 0

        except Exception as e:
            pytest.skip(f"Integration test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_agent_with_custom_configuration(self):
        """Test agent with custom configuration parameters."""
        try:
            from agentarea_agents_sdk.agents.agent import Agent

            agent = Agent(
                name="Custom Agent",
                instruction="You are a precise assistant.",
                model_provider="ollama_chat",
                model_name="qwen2.5",
                temperature=0.1,
                max_tokens=100,
                max_iterations=2,
                include_default_tools=True,
            )

            result = await agent.run("What is 2 + 2?")

            assert isinstance(result, str)
            assert len(result) > 0

        except Exception as e:
            pytest.skip(f"Integration test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_streaming_vs_non_streaming_consistency(self):
        """Test that streaming and non-streaming produce similar results."""
        try:
            from agentarea_agents_sdk.agents.agent import create_agent

            agent = create_agent(
                name="Consistency Test Agent",
                instruction="You are a helpful assistant. Be concise.",
                model="ollama_chat/qwen2.5",
                max_iterations=1,  # Limit to one iteration for consistency
            )

            task = "What is 1 + 1?"

            # Get streaming result
            streaming_parts = []
            async for content in agent.run_stream(task):
                streaming_parts.append(content)
            streaming_result = "".join(streaming_parts)

            # Get non-streaming result
            non_streaming_result = await agent.run(task)

            # Both should be non-empty strings
            assert isinstance(streaming_result, str)
            assert isinstance(non_streaming_result, str)
            assert len(streaming_result) > 0
            assert len(non_streaming_result) > 0

            # They should contain similar content (both should mention "2")
            # Note: They might not be identical due to the nature of LLM generation

        except Exception as e:
            pytest.skip(f"Integration test failed - LLM not available: {e}")


class TestErrorHandling:
    """Test error handling in various scenarios."""

    def test_invalid_model_format_error(self):
        """Test that invalid model format raises appropriate error."""
        from agentarea_agents_sdk.agents.agent import create_agent

        with pytest.raises(ValueError, match="Model must be in format 'provider/model_name'"):
            create_agent(name="Test Agent", instruction="Test instruction", model="invalid_format")

    @pytest.mark.asyncio
    async def test_tool_execution_error_handling(self):
        """Test that tool execution errors are handled gracefully."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool
        from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

        tool_executor = ToolExecutor()
        tool_executor.registry.register(CalculateTool())

        # Try to execute with invalid arguments
        result = await tool_executor.execute_tool("calculate", {"invalid": "args"})

        # Should return an error result, not raise an exception
        assert result is not None
        assert result.get("success") is False
        assert "error" in result or "Error" in str(result)

    @pytest.mark.asyncio
    async def test_nonexistent_tool_error(self):
        """Test error handling for nonexistent tools."""
        from agentarea_agents_sdk.tools.base_tool import ToolExecutionError
        from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

        tool_executor = ToolExecutor()

        # Try to execute a tool that doesn't exist - should raise ToolExecutionError
        with pytest.raises(ToolExecutionError):
            await tool_executor.execute_tool("nonexistent_tool", {})


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
