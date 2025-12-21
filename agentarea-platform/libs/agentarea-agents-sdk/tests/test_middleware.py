"""Tests for middleware components."""

import pytest


class TestMiddlewareBase:
    """Test base middleware components."""

    def test_middleware_protocol(self):
        """Test Middleware protocol definition."""
        from agentarea_agents_sdk.middleware.base import Middleware

        # Verify protocol has required methods
        assert hasattr(Middleware, "before_llm_call")
        assert hasattr(Middleware, "after_llm_call")
        assert hasattr(Middleware, "before_tool_call")
        assert hasattr(Middleware, "after_tool_call")

    def test_middleware_stack_creation(self):
        """Test MiddlewareStack creation."""
        from agentarea_agents_sdk.middleware.base import MiddlewareStack

        stack = MiddlewareStack([])
        assert stack.middlewares == []

    def test_middleware_stack_with_middlewares(self):
        """Test MiddlewareStack with middlewares."""
        from agentarea_agents_sdk.middleware.base import MiddlewareStack
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        middleware = TodoListMiddleware()
        stack = MiddlewareStack([middleware])

        assert len(stack.middlewares) == 1
        assert stack.middlewares[0] == middleware


class TestStateBackend:
    """Test state management components."""

    def test_in_memory_state(self):
        """Test InMemoryState backend."""
        from agentarea_agents_sdk.middleware.state import InMemoryState

        state = InMemoryState()

        # Test set and get
        state.set("key1", "value1")
        assert state.get("key1") == "value1"

        # Test default value
        assert state.get("nonexistent", "default") == "default"

        # Test update
        state.update({"a": 1, "b": 2})
        assert state.get("a") == 1
        assert state.get("b") == 2

        # Test snapshot
        snapshot = state.snapshot()
        assert "key1" in snapshot
        assert "a" in snapshot
        assert "b" in snapshot


class TestTodoListMiddleware:
    """Test TodoListMiddleware."""

    def test_todolist_middleware_creation(self):
        """Test TodoListMiddleware creation."""
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        middleware = TodoListMiddleware()
        assert middleware.task_service is not None

    @pytest.mark.asyncio
    async def test_todolist_before_tool_call_passthrough(self):
        """Test that non-write_todos calls pass through."""
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        middleware = TodoListMiddleware()
        tool_call = {"function": {"name": "other_tool", "arguments": {}}}
        state = {}

        result_call, state_update = await middleware.before_tool_call(tool_call, state)

        assert result_call == tool_call
        assert state_update is None

    @pytest.mark.asyncio
    async def test_todolist_rejects_empty_todos(self):
        """Test that empty todos array is rejected."""
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        middleware = TodoListMiddleware()
        tool_call = {"function": {"name": "write_todos", "arguments": {"todos": []}}}
        state = {}

        result_call, _ = await middleware.before_tool_call(tool_call, state)

        assert result_call.get("_skip_execution") is True
        assert "error" in result_call.get("_result", {})

    @pytest.mark.asyncio
    async def test_todolist_processes_valid_todos(self):
        """Test that valid todos are processed."""
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        middleware = TodoListMiddleware()
        todos = [
            {"content": "Task 1", "activeForm": "Doing task 1", "status": "in_progress"},
            {"content": "Task 2", "activeForm": "Doing task 2", "status": "pending"},
        ]
        tool_call = {"function": {"name": "write_todos", "arguments": {"todos": todos}}}
        state = {}

        result_call, state_update = await middleware.before_tool_call(tool_call, state)

        assert result_call.get("_skip_execution") is True
        assert result_call.get("_result", {}).get("success") is True
        assert state_update is not None
        assert "todos" in state_update
        assert len(state_update["todos"]) == 2


class TestFilesystemMiddleware:
    """Test FilesystemMiddleware."""

    def test_filesystem_middleware_creation(self):
        """Test FilesystemMiddleware creation."""
        from agentarea_agents_sdk.middleware.filesystem import FilesystemMiddleware

        middleware = FilesystemMiddleware()
        assert middleware.eviction_threshold == 80_000

        middleware2 = FilesystemMiddleware(eviction_threshold=50_000)
        assert middleware2.eviction_threshold == 50_000

    @pytest.mark.asyncio
    async def test_filesystem_initializes_files_state(self):
        """Test that before_llm_call initializes files state."""
        from agentarea_agents_sdk.middleware.filesystem import FilesystemMiddleware

        middleware = FilesystemMiddleware()
        state = {}

        result = await middleware.before_llm_call(state)

        assert result is not None
        assert "files" in result
        assert result["files"] == {}

    @pytest.mark.asyncio
    async def test_filesystem_does_not_reinitialize(self):
        """Test that existing files state is not overwritten."""
        from agentarea_agents_sdk.middleware.filesystem import FilesystemMiddleware

        middleware = FilesystemMiddleware()
        state = {"files": {"existing": "data"}}

        result = await middleware.before_llm_call(state)

        assert result is None

    @pytest.mark.asyncio
    async def test_filesystem_evicts_large_results(self):
        """Test context eviction for large tool results."""
        from agentarea_agents_sdk.middleware.filesystem import FilesystemMiddleware

        middleware = FilesystemMiddleware(eviction_threshold=100)
        tool_call = {"id": "test123", "function": {"name": "some_tool"}}
        large_result = "x" * 150  # Exceeds threshold
        state = {"files": {}}

        result, state_update = await middleware.after_tool_call(tool_call, large_result, state)

        assert isinstance(result, dict)
        assert result.get("evicted") is True
        assert "file_path" in result
        assert state_update is not None
        assert result["file_path"] in state_update["files"]


class TestSummarizationMiddleware:
    """Test SummarizationMiddleware."""

    def test_summarization_middleware_creation(self):
        """Test SummarizationMiddleware creation."""
        from agentarea_agents_sdk.middleware.summarization import SummarizationMiddleware

        middleware = SummarizationMiddleware()
        assert middleware.max_tokens == 50_000
        assert middleware.keep_last == 6

    def test_count_tokens_approx(self):
        """Test approximate token counting."""
        from agentarea_agents_sdk.middleware.summarization import count_tokens_approx

        text = "Hello world!"  # 12 chars
        assert count_tokens_approx(text) == 3  # 12 // 4

    def test_count_messages_tokens(self):
        """Test message token counting."""
        from agentarea_agents_sdk.middleware.summarization import count_messages_tokens

        messages = [
            {"role": "user", "content": "Hello"},  # 5 chars = 1 token
            {"role": "assistant", "content": "Hi there!"},  # 9 chars = 2 tokens
        ]
        tokens = count_messages_tokens(messages)
        assert tokens == 3

    def test_format_messages_for_summary(self):
        """Test message formatting for summary."""
        from agentarea_agents_sdk.middleware.summarization import format_messages_for_summary

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!", "tool_calls": [{"function": {"name": "calc"}}]},
        ]
        formatted = format_messages_for_summary(messages)

        assert "Message 1 (user): Hello" in formatted
        assert "Message 2 (assistant): Hi!" in formatted
        assert "Tools called: calc" in formatted


class TestSubAgentMiddleware:
    """Test SubAgentMiddleware."""

    def test_subagent_middleware_creation(self):
        """Test SubAgentMiddleware creation."""
        from agentarea_agents_sdk.middleware.subagents import SubAgentMiddleware

        # Mock agent class
        class MockAgent:
            pass

        middleware = SubAgentMiddleware(
            default_agent_class=MockAgent,
            general_purpose_agent=True,
        )

        assert middleware.default_agent_class == MockAgent
        assert middleware.general_purpose_agent is True

    def test_subagent_get_tools(self):
        """Test that SubAgentMiddleware provides task tool."""
        from agentarea_agents_sdk.middleware.subagents import SubAgentMiddleware, TaskTool

        class MockAgent:
            pass

        middleware = SubAgentMiddleware(default_agent_class=MockAgent)
        tools = middleware.get_tools()

        assert len(tools) == 1
        assert isinstance(tools[0], TaskTool)

    def test_task_tool_schema(self):
        """Test TaskTool schema."""
        from agentarea_agents_sdk.middleware.subagents import SubAgentMiddleware, TaskTool

        class MockAgent:
            pass

        middleware = SubAgentMiddleware(default_agent_class=MockAgent)
        task_tool = TaskTool(middleware)

        schema = task_tool.get_schema()

        assert "properties" in schema
        assert "description" in schema["properties"]
        assert "subagent_type" in schema["properties"]
        assert schema["required"] == ["description", "subagent_type"]

    @pytest.mark.asyncio
    async def test_subagent_blocks_task_without_plan(self):
        """Test that task delegation is blocked without a plan."""
        from agentarea_agents_sdk.middleware.subagents import SubAgentMiddleware

        class MockAgent:
            pass

        middleware = SubAgentMiddleware(default_agent_class=MockAgent)
        tool_call = {
            "function": {
                "name": "task",
                "arguments": {"description": "Do something", "subagent_type": "general-purpose"},
            }
        }
        state = {"todos": []}  # Empty plan

        result_call, _ = await middleware.before_tool_call(tool_call, state)

        assert result_call.get("_skip_execution") is True
        assert "Planning required" in result_call.get("_result", {}).get("error", "")

    @pytest.mark.asyncio
    async def test_subagent_allows_task_with_plan(self):
        """Test that task delegation is allowed with a plan."""
        from agentarea_agents_sdk.middleware.subagents import SubAgentMiddleware

        class MockAgent:
            pass

        middleware = SubAgentMiddleware(default_agent_class=MockAgent)
        tool_call = {
            "function": {
                "name": "task",
                "arguments": {"description": "Do something", "subagent_type": "general-purpose"},
            }
        }
        state = {"todos": [{"content": "Step 1", "status": "in_progress"}]}

        result_call, state_update = await middleware.before_tool_call(tool_call, state)

        # Should not block
        assert result_call.get("_skip_execution") is not True


class TestWriteTodosTool:
    """Test WriteTodosTool."""

    def test_write_todos_tool_properties(self):
        """Test WriteTodosTool basic properties."""
        from agentarea_agents_sdk.tools.write_todos_tool import WriteTodosTool

        tool = WriteTodosTool()

        assert tool.name == "write_todos"
        assert "write_todos" in tool.description.lower() or "todo" in tool.description.lower()

    def test_write_todos_tool_schema(self):
        """Test WriteTodosTool schema."""
        from agentarea_agents_sdk.tools.write_todos_tool import WriteTodosTool

        tool = WriteTodosTool()
        schema = tool.get_schema()

        assert "properties" in schema
        assert "todos" in schema["properties"]
        assert schema["properties"]["todos"]["type"] == "array"

    @pytest.mark.asyncio
    async def test_write_todos_tool_execute(self):
        """Test WriteTodosTool execution (no-op)."""
        from agentarea_agents_sdk.tools.write_todos_tool import WriteTodosTool

        tool = WriteTodosTool()
        result = await tool.execute(todos=[{"content": "Test", "status": "pending"}])

        assert result.get("success") is True


class TestStatefulAgent:
    """Test StatefulAgent."""

    def test_stateful_agent_creation(self):
        """Test StatefulAgent creation."""
        from agentarea_agents_sdk.agents.stateful_agent import StatefulAgent

        agent = StatefulAgent(
            name="TestAgent",
            instruction="Test agent",
            model_provider="ollama_chat",
            model_name="qwen2.5",
            enable_default_middleware=False,  # Disable for simple test
        )

        assert agent.instruction == "Test agent"
        assert agent.name == "TestAgent"
        assert agent.state is not None

    def test_stateful_agent_with_custom_middleware(self):
        """Test StatefulAgent with custom middlewares."""
        from agentarea_agents_sdk.agents.stateful_agent import StatefulAgent
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        custom_middleware = TodoListMiddleware()

        agent = StatefulAgent(
            name="TestAgent",
            instruction="Test agent",
            model_provider="ollama_chat",
            model_name="qwen2.5",
            middlewares=[custom_middleware],
            enable_default_middleware=False,
        )

        assert agent.middlewares is not None
        assert len(agent.middlewares.middlewares) == 1


class TestPromptBuilderWithPlanning:
    """Test PromptBuilder PLANNING_INSTRUCTIONS integration."""

    def test_planning_instructions_exists(self):
        """Test that PLANNING_INSTRUCTIONS constant exists."""
        from agentarea_agents_sdk.prompts import MessageTemplates

        assert hasattr(MessageTemplates, "PLANNING_INSTRUCTIONS")
        assert "write_todos" in MessageTemplates.PLANNING_INSTRUCTIONS

    def test_build_system_prompt_adds_planning(self):
        """Test that planning instructions are added when write_todos is available."""
        from agentarea_agents_sdk.prompts import PromptBuilder

        tools_with_todos = [{"name": "write_todos", "description": "Write todos"}]
        prompt = PromptBuilder.build_system_prompt(
            agent_name="Test",
            agent_instruction="Test",
            goal_description="Test",
            success_criteria=["Test"],
            available_tools=tools_with_todos,
        )

        assert "write_todos" in prompt
        assert "RECORD your plan" in prompt

    def test_build_system_prompt_no_planning_without_tool(self):
        """Test that planning instructions are NOT added without write_todos."""
        from agentarea_agents_sdk.prompts import PromptBuilder

        tools_without_todos = [{"name": "calculate", "description": "Calculate"}]
        prompt = PromptBuilder.build_system_prompt(
            agent_name="Test",
            agent_instruction="Test",
            goal_description="Test",
            success_criteria=["Test"],
            available_tools=tools_without_todos,
        )

        assert "RECORD your plan" not in prompt


class TestMiddlewareIntegration:
    """Integration tests for middleware stack."""

    @pytest.mark.asyncio
    async def test_middleware_stack_before_llm_call(self):
        """Test middleware stack before_llm_call execution."""
        from agentarea_agents_sdk.middleware.base import MiddlewareStack
        from agentarea_agents_sdk.middleware.filesystem import FilesystemMiddleware
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        stack = MiddlewareStack([FilesystemMiddleware(), TodoListMiddleware()])

        state = {}
        await stack.run_before_llm(state)

        # FilesystemMiddleware should have added 'files'
        assert "files" in state

    @pytest.mark.asyncio
    async def test_middleware_stack_before_tool_call(self):
        """Test middleware stack before_tool_call execution."""
        from agentarea_agents_sdk.middleware.base import MiddlewareStack
        from agentarea_agents_sdk.middleware.todolist import TodoListMiddleware

        stack = MiddlewareStack([TodoListMiddleware()])

        tool_call = {"function": {"name": "other_tool"}}
        state = {}

        result_call = await stack.run_before_tool(tool_call, state)

        assert result_call == tool_call
