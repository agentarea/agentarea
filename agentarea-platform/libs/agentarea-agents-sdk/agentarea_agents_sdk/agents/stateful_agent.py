"""Stateful agent with middleware support."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from ..middleware.base import Middleware, MiddlewareStack
from ..middleware.filesystem import FilesystemMiddleware
from ..middleware.state import InMemoryState, StateBackend
from ..middleware.subagents import SubAgentMiddleware
from ..middleware.summarization import SummarizationMiddleware
from ..middleware.todolist import TodoListMiddleware
from ..models.llm_model import LLMModel, LLMRequest
from ..prompts import PromptBuilder, ToolInfo
from ..tools.completion_tool import CompletionTool
from ..tools.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class StatefulAgent:
    """Stateful agent with middleware support."""

    def __init__(
        self,
        name: str,
        instruction: str,
        model_provider: str,
        model_name: str,
        endpoint_url: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 500,
        max_iterations: int = 10,
        tools: list[Any] | None = None,
        include_default_tools: bool = True,
        middlewares: list[Middleware] | None = None,
        state_backend: StateBackend | None = None,
        # Middleware configuration
        enable_default_middleware: bool = True,
        enable_todolist: bool = True,
        enable_filesystem: bool = True,
        enable_subagents: bool = True,
        enable_summarization: bool = True,
        subagents: list[dict[str, Any]] | None = None,
        max_tokens_before_summary: int = 50_000,
        messages_to_keep: int = 6,
    ):
        """Initialize StatefulAgent with middleware support.

        Args:
            name: Agent name
            instruction: Agent system instruction
            model_provider: LLM provider (e.g., "ollama_chat")
            model_name: Model name (e.g., "qwen2.5:3b")
            endpoint_url: Optional endpoint URL
            temperature: Sampling temperature
            max_tokens: Max tokens per generation
            max_iterations: Max agent loop iterations
            tools: Additional tools to register
            include_default_tools: Include CompletionTool and WriteTodosTool
            middlewares: Additional custom middlewares
            state_backend: State backend (defaults to InMemoryState)
            enable_default_middleware: Enable default Deep Agents middleware stack
            enable_todolist: Enable TodoListMiddleware
            enable_filesystem: Enable FilesystemMiddleware
            enable_subagents: Enable SubAgentMiddleware
            enable_summarization: Enable SummarizationMiddleware
            subagents: List of subagent configurations for SubAgentMiddleware
            max_tokens_before_summary: Token threshold for summarization
            messages_to_keep: Number of recent messages to keep after summarization
        """
        self.name = name
        self.instruction = instruction
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.model_provider = model_provider
        self.model_name = model_name
        self.endpoint_url = endpoint_url

        self.model = LLMModel(
            provider_type=model_provider,
            model_name=model_name,
            endpoint_url=endpoint_url,
        )

        self.tool_executor = ToolExecutor()

        if include_default_tools:
            self.tool_executor.registry.register(CompletionTool())
            # Import here to avoid circular dependency
            from ..tools.write_todos_tool import WriteTodosTool
            self.tool_executor.registry.register(WriteTodosTool())

        if tools:
            for tool in tools:
                self.tool_executor.registry.register(tool)

        self.state = state_backend or InMemoryState()

        # Build middleware stack similar to Deep Agents
        default_middlewares: list[Middleware] = []

        if enable_default_middleware:
            # 1. TodoListMiddleware (managed by WriteTodosTool + TodoListMiddleware)
            if enable_todolist:
                default_middlewares.append(TodoListMiddleware())

            # 2. FilesystemMiddleware (context eviction)
            if enable_filesystem:
                default_middlewares.append(FilesystemMiddleware())

            # 3. SubAgentMiddleware (task delegation)
            if enable_subagents:
                # SubAgentMiddleware needs recursive middleware for subagents
                subagent_middleware = [
                    TodoListMiddleware(),
                    FilesystemMiddleware(),
                    SummarizationMiddleware(
                        model_provider=model_provider,
                        model_name=model_name,
                        endpoint_url=endpoint_url,
                        max_tokens_before_summary=max_tokens_before_summary,
                        messages_to_keep=messages_to_keep,
                    ),
                ]

                # Default kwargs for subagents
                default_agent_kwargs = {
                    "name": "subagent",
                    "instruction": "You are a helpful assistant that completes tasks autonomously.",
                    "model_provider": model_provider,
                    "model_name": model_name,
                    "endpoint_url": endpoint_url,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "max_iterations": max_iterations,
                    "tools": tools,
                    "include_default_tools": True,
                    "middlewares": subagent_middleware,
                    "enable_default_middleware": False,  # Subagent uses explicit middleware
                }

                default_middlewares.append(
                    SubAgentMiddleware(
                        default_agent_class=StatefulAgent,
                        default_agent_kwargs=default_agent_kwargs,
                        subagents=subagents or [],
                        general_purpose_agent=True,
                        parent_tools=self.tool_executor.registry.list_tools(),
                    )
                )

            # 4. SummarizationMiddleware (token management)
            if enable_summarization:
                default_middlewares.append(
                    SummarizationMiddleware(
                        model_provider=model_provider,
                        model_name=model_name,
                        endpoint_url=endpoint_url,
                        max_tokens_before_summary=max_tokens_before_summary,
                        messages_to_keep=messages_to_keep,
                    )
                )

        # Combine default + custom middlewares
        all_middlewares = default_middlewares + (middlewares or [])
        self.middlewares = MiddlewareStack(all_middlewares)

        # Register tools from middleware (e.g., TaskTool from SubAgentMiddleware)
        for middleware in all_middlewares:
            if hasattr(middleware, "get_tools"):
                for tool in middleware.get_tools():
                    self.tool_executor.registry.register(tool)

    def _build_system_prompt(self, goal: str, success_criteria: list[str] | None = None) -> str:
        available_tools: list[ToolInfo] = []
        for tool_instance in self.tool_executor.registry.list_tools():
            available_tools.append(
                {
                    "name": tool_instance.name,
                    "description": getattr(
                        tool_instance, "description", f"Tool: {tool_instance.name}"
                    ),
                }
            )

        if success_criteria is None:
            success_criteria = [
                "Understand the task requirements",
                "Use available tools when needed",
                "Provide clear reasoning for actions",
                "Complete the task successfully",
            ]

        base_prompt = PromptBuilder.build_react_system_prompt(
            agent_name=self.name,
            agent_instruction=self.instruction,
            goal_description=goal,
            success_criteria=success_criteria,
            available_tools=available_tools,
        )

        # Collect additional system prompts from middleware
        middleware_prompts = []
        for middleware in self.middlewares.middlewares:
            if hasattr(middleware, "system_prompt"):
                middleware_prompts.append(middleware.system_prompt)

        if middleware_prompts:
            return base_prompt + "\n\n" + "\n\n".join(middleware_prompts)

        return base_prompt

    async def _execute_agent_loop(
        self,
        task: str,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        goal = goal or task

        # Initialize state if needed
        if not self.state.get("initialized"):
            self.state.update(
                {
                    "messages": [],
                    "iteration": 0,
                    "initialized": True,
                }
            )

        system_prompt = self._build_system_prompt(goal, success_criteria)
        messages = self.state.get("messages", [])

        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": task})
        self.state.set("messages", messages)

        tools = self.tool_executor.get_openai_functions()
        iteration = 0
        done = False

        while not done and iteration < self.max_iterations:
            iteration += 1
            self.state.set("iteration", iteration)

            # Before LLM - pass state._data directly for mutations
            await self.middlewares.run_before_llm(self.state._data)

            messages = self.state.get("messages", [])
            request = LLMRequest(
                messages=messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            response_stream = self.model.ainvoke_stream(request)
            full_content = ""
            final_tool_calls = None

            async for chunk in response_stream:
                if chunk.content:
                    full_content += chunk.content
                    if stream:
                        yield chunk.content
                if chunk.tool_calls:
                    final_tool_calls = chunk.tool_calls

            assistant_message = {"role": "assistant", "content": full_content}
            if final_tool_calls:
                assistant_message["tool_calls"] = final_tool_calls

            messages.append(assistant_message)
            self.state.set("messages", messages)

            # After LLM (mock response object)
            class MockResponse:
                def __init__(self, content, tool_calls):
                    self.content = content
                    self.tool_calls = tool_calls

            await self.middlewares.run_after_llm(
                self.state._data, MockResponse(full_content, final_tool_calls)
            )

            if final_tool_calls:
                for tool_call in final_tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args_str = tool_call["function"]["arguments"]
                    tool_id = tool_call["id"]

                    try:
                        tool_args = (
                            json.loads(tool_args_str)
                            if isinstance(tool_args_str, str)
                            else tool_args_str
                        )

                        # Before tool
                        tool_call_dict = {
                            "id": tool_id,
                            "name": tool_name,
                            "function": {"name": tool_name, "arguments": tool_args},
                        }
                        tool_call_dict = await self.middlewares.run_before_tool(
                            tool_call_dict, self.state._data
                        )

                        # Check if middleware wants to skip execution
                        if tool_call_dict.get("_skip_execution"):
                            result = tool_call_dict.get("_result", {"success": True})
                        else:
                            result = await self.tool_executor.execute_tool(tool_name, tool_args)

                        if tool_name == "completion":
                            done = True

                        # After tool
                        result = await self.middlewares.run_after_tool(
                            tool_call_dict, result, self.state._data
                        )

                        tool_result = str(result.get("result", result))
                        messages = self.state.get("messages", [])
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": tool_result,
                            }
                        )
                        self.state.set("messages", messages)

                        if stream:
                            yield f"\n[Tool {tool_name}: {tool_result}]\n"

                    except Exception as e:
                        error_msg = f"Error: {str(e)}"
                        messages = self.state.get("messages", [])
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": error_msg,
                            }
                        )
                        self.state.set("messages", messages)
                        if stream:
                            yield f"\n[Tool Error: {error_msg}]\n"

        if not stream:
            messages = self.state.get("messages", [])
            final_content = ""
            for msg in messages:
                if msg["role"] == "assistant":
                    final_content += msg["content"] + "\n"
            yield final_content.strip()

    async def run_stream(
        self,
        task: str,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        async for content in self._execute_agent_loop(task, goal, success_criteria, stream=True):
            yield content

    async def run(
        self,
        task: str,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
    ) -> str:
        result = ""
        async for content in self._execute_agent_loop(task, goal, success_criteria, stream=False):
            result += content
        return result

    def add_tool(self, tool: Any) -> None:
        self.tool_executor.registry.register(tool)
