"""Tests for the high-level Agent class."""

import pytest

from agentarea_agents_sdk.agents.agent import Agent, create_agent


class TestAgentCreation:
    """Test agent creation and configuration."""

    def test_create_agent_with_valid_model(self, test_model):
        """Test creating an agent with valid model specification."""
        agent = create_agent(
            name="Test Agent", instruction="You are a test assistant.", model=test_model
        )

        assert agent.name == "Test Agent"
        assert agent.instruction == "You are a test assistant."
        assert agent.model.provider_type == "ollama_chat"
        assert agent.model.model_name == "qwen2.5"

    def test_create_agent_invalid_model_format(self):
        """Test that invalid model format raises ValueError."""
        with pytest.raises(ValueError, match="Model must be in format 'provider/model_name'"):
            create_agent(
                name="Test Agent", instruction="You are a test assistant.", model="invalid_format"
            )

    def test_agent_direct_construction(self):
        """Test direct Agent construction."""
        agent = Agent(
            name="Direct Agent",
            instruction="Direct construction test.",
            model_provider="ollama_chat",
            model_name="qwen2.5",
            temperature=0.5,
            max_tokens=200,
            max_iterations=5,
        )

        assert agent.name == "Direct Agent"
        assert agent.temperature == 0.5
        assert agent.max_tokens == 200
        assert agent.max_iterations == 5

    def test_agent_with_custom_tools(self, test_model):
        """Test agent creation with custom tools."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool

        custom_tool = CalculateTool()
        agent = create_agent(
            name="Tool Agent",
            instruction="Agent with custom tools.",
            model=test_model,
            tools=[custom_tool],
        )

        # Check that tools are registered
        tools = agent.tool_executor.registry.list_tools()
        tool_names = [tool.name for tool in tools]
        assert "calculate" in tool_names

    def test_agent_without_default_tools(self, test_model):
        """Test agent creation without default tools."""
        agent = Agent(
            name="No Tools Agent",
            instruction="Agent without default tools.",
            model_provider="ollama_chat",
            model_name="qwen2.5",
            include_default_tools=False,
        )

        # Should have no tools by default
        tools = agent.tool_executor.registry.list_tools()
        assert len(tools) == 0


class TestAgentExecution:
    """Test agent execution methods."""

    @pytest.mark.asyncio
    async def test_agent_run_basic(self, test_model, skip_if_no_llm):
        """Test basic agent run method."""
        skip_if_no_llm()

        agent = create_agent(
            name="Test Agent", instruction="You are a helpful assistant.", model=test_model
        )

        result = await agent.run("What is 2 + 2?")

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_agent_run_stream(self, test_model, skip_if_no_llm):
        """Test agent streaming method."""
        skip_if_no_llm()

        agent = create_agent(
            name="Streaming Agent", instruction="You are a helpful assistant.", model=test_model
        )

        content_received = False
        content_parts = []

        async for content in agent.run_stream("Say hello"):
            content_parts.append(content)
            if content.strip():
                content_received = True
                break  # Just test that we get content

        assert content_received
        assert len(content_parts) > 0

    @pytest.mark.asyncio
    async def test_agent_with_custom_goal_and_criteria(self, test_model, skip_if_no_llm):
        """Test agent with custom goal and success criteria."""
        skip_if_no_llm()

        agent = create_agent(
            name="Goal Agent", instruction="You are a systematic assistant.", model=test_model
        )

        task = "Help me understand"
        goal = "Explain what 1+1 equals"
        criteria = ["Provide the answer", "Explain briefly"]

        result = await agent.run(task, goal=goal, success_criteria=criteria)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_agent_tool_usage(self, test_model, skip_if_no_llm):
        """Test that agent can use tools."""
        skip_if_no_llm()
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool

        agent = create_agent(
            name="Calculator Agent",
            instruction="You are a math assistant that uses tools.",
            model=test_model,
            tools=[CalculateTool()],
        )

        tool_used = False
        async for content in agent.run_stream("Calculate 5 * 3"):
            if "[Tool calculate:" in content:
                tool_used = True
                break

        assert tool_used, "Agent should use calculation tool"


class TestAgentUtilities:
    """Test agent utility methods."""

    def test_add_tool(self, test_model):
        """Test adding custom tools to agent."""
        from agentarea_agents_sdk.tools.calculate_tool import CalculateTool

        agent = create_agent(
            name="Tool Agent",
            instruction="Agent for tool testing.",
            model=test_model,
            include_default_tools=False,
        )

        # Initially no tools
        assert len(agent.tool_executor.registry.list_tools()) == 0

        # Add a tool
        agent.add_tool(CalculateTool())

        # Should now have one tool
        tools = agent.tool_executor.registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "calculate"

    def test_get_conversation_history(self, test_model):
        """Test getting conversation history (currently returns empty list)."""
        agent = create_agent(
            name="History Agent", instruction="Agent for history testing.", model=test_model
        )

        history = agent.get_conversation_history()
        assert isinstance(history, list)
        # Currently returns empty list as it's stateless
        assert len(history) == 0

    def test_reset_agent(self, test_model):
        """Test resetting agent state."""
        agent = create_agent(
            name="Reset Agent", instruction="Agent for reset testing.", model=test_model
        )

        # Should not raise any errors
        agent.reset()
        assert True  # If we get here, reset worked
