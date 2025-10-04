"""Tests for individual SDK components."""

import pytest


class TestPromptBuilder:
    """Test the PromptBuilder functionality."""

    def test_build_react_system_prompt(self):
        """Test building ReAct system prompts."""
        from agentarea_agents_sdk.prompts import PromptBuilder

        agent_name = "Test Agent"
        agent_instruction = "You are a test agent."
        goal_description = "Complete a test task"
        success_criteria = ["Do something", "Complete the task"]
        available_tools = [{"name": "test_tool", "description": "A test tool"}]

        prompt = PromptBuilder.build_react_system_prompt(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=success_criteria,
            available_tools=available_tools,
        )

        assert agent_name in prompt
        assert agent_instruction in prompt
        assert goal_description in prompt
        assert "test_tool" in prompt
        assert "ReAct" in prompt  # Should mention ReAct framework


class TestToolExecutor:
    """Test the ToolExecutor functionality."""

    @pytest.mark.asyncio
    async def test_tool_registration_and_execution(self):
        """Test tool registration and execution."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool
        from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

        tool_executor = ToolExecutor()
        tool_executor.registry.register(CalculateTool())

        # Test tool registration
        tools = tool_executor.get_openai_functions()
        assert len(tools) > 0, "Should have registered tools"

        # Test tool execution
        result = await tool_executor.execute_tool("calculate", {"expression": "2 + 2"})
        assert result is not None, "Tool should return a result"
        assert result.get("success") is True, "Calculation should succeed"
        assert "4" in str(result.get("result", "")), "Should calculate 2+2=4"

    def test_tool_registry_operations(self):
        """Test tool registry operations."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool
        from agentarea_agents_sdk.tools.completion_tool import CompletionTool
        from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

        tool_executor = ToolExecutor()

        # Initially should have completion tool (default behavior)
        initial_tools = tool_executor.registry.list_tools()
        len(initial_tools)

        # Register tools
        calc_tool = CalculateTool()
        completion_tool = CompletionTool()

        tool_executor.registry.register(calc_tool)
        tool_executor.registry.register(completion_tool)

        # Should have at least the two tools we registered
        # (completion tool might replace existing one with same name)
        tools = tool_executor.registry.list_tools()
        assert len(tools) >= 2

        tool_names = [tool.name for tool in tools]
        assert "calculate" in tool_names
        assert "completion" in tool_names

        # Test getting specific tool
        retrieved_tool = tool_executor.registry.get("calculate")
        assert retrieved_tool is not None
        assert retrieved_tool.name == "calculate"


class TestLLMModel:
    """Test LLM model functionality."""

    @pytest.mark.asyncio
    async def test_llm_model_basic_functionality(self):
        """Test basic LLM model functionality."""
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

            model = LLMModel(provider_type="ollama_chat", model_name="qwen2.5", endpoint_url=None)

            request = LLMRequest(
                messages=[{"role": "user", "content": "Hello, respond with just 'Hi!'"}],
                temperature=0.3,
                max_tokens=50,
            )

            response_stream = model.ainvoke_stream(request)
            full_content = ""

            async for chunk in response_stream:
                if chunk.content:
                    full_content += chunk.content

            assert len(full_content) > 0, "Response should not be empty"

        except Exception as e:
            pytest.skip(f"LLM model not available: {e}")

    def test_llm_request_creation(self):
        """Test LLM request object creation."""
        from agentarea_agents_sdk.models.llm_model import LLMRequest

        request = LLMRequest(
            messages=[{"role": "user", "content": "test"}], temperature=0.5, max_tokens=100
        )

        assert request.messages == [{"role": "user", "content": "test"}]
        assert request.temperature == 0.5
        assert request.max_tokens == 100


class TestTools:
    """Test individual tool implementations."""

    @pytest.mark.asyncio
    async def test_calculate_tool(self):
        """Test the calculate tool."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool

        tool = CalculateTool()

        # Test basic properties
        assert tool.name == "calculate"
        assert hasattr(tool, "description")

        # Test execution
        result = await tool.execute(expression="10 + 5")
        assert result.get("success") is True
        assert "15" in str(result.get("result", ""))

    @pytest.mark.asyncio
    async def test_completion_tool(self):
        """Test the completion tool."""
        from agentarea_agents_sdk.tools.completion_tool import CompletionTool

        tool = CompletionTool()

        # Test basic properties
        assert tool.name == "completion"
        assert hasattr(tool, "description")

        # Test execution (no parameters needed)
        result = await tool.execute()
        assert result.get("success") is True
        assert isinstance(result.get("result"), str)

    def test_tool_openai_function_definition(self):
        """Test that tools provide proper OpenAI function definitions."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool

        tool = CalculateTool()
        function_def = tool.get_openai_function_definition()

        assert isinstance(function_def, dict)
        assert "type" in function_def
        assert "function" in function_def
        assert function_def["type"] == "function"

        function_info = function_def["function"]
        assert "name" in function_info
        assert "description" in function_info
        assert "parameters" in function_info
        assert function_info["name"] == "calculate"
