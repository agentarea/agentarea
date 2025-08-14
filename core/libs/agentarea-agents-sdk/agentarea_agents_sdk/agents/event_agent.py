"""Event-driven Agent orchestrator that is infra-independent.

This agent focuses on orchestration via events and delegates actual side effects
(LLM calls, tool execution, storage, etc.) to pluggable executors/handlers.

Goals:
- Infra independence via dependency injection of executors
- Event-first design: the agent emits events for everything it does
- Minimal decision logic in the agent, keep it as an orchestrator

Default behavior:
- If no custom LLM executor is provided, falls back to the built-in LLMModel
- Uses the ToolExecutor for tool execution and supports built-in tools
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.llm_model import LLMModel, LLMRequest
from ..prompts import PromptBuilder, ToolInfo
from ..tools.completion_tool import CompletionTool
from ..tools.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Generic event structure for agent orchestration."""
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


# Signature for event subscribers/listeners. Can be sync or async.
EventListener = Callable[[Event], Any | Awaitable[Any]]


class EventAgent:
    """Event-driven Agent orchestrator.

    The EventAgent emits events throughout its lifecycle and delegates operations
    to injected executors. By default, it uses the SDK LLMModel and ToolExecutor,
    but callers can inject alternatives for different infrastructure.
    """

    def __init__(
        self,
        name: str,
        instruction: str,
        *,
        # LLM execution
        llm_executor: Any | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        endpoint_url: str | None = None,
        # Tool execution
        tool_executor: ToolExecutor | None = None,
        tools: list[Any] | None = None,
        include_default_tools: bool = True,
        # Generation params
        temperature: float = 0.3,
        max_tokens: int = 500,
        max_iterations: int = 10,
        # Events
        event_listener: EventListener | None = None,
    ) -> None:
        self.name = name
        self.instruction = instruction
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.event_listener = event_listener

        # Configure LLM executor (DI)
        if llm_executor is not None:
            self.llm = llm_executor
        else:
            if not (model_provider and model_name):
                raise ValueError(
                    "Either provide llm_executor or both model_provider and model_name"
                )
            self.llm = LLMModel(
                provider_type=model_provider,
                model_name=model_name,
                endpoint_url=endpoint_url,
            )

        # Configure Tool executor (DI)
        self.tool_executor = tool_executor or ToolExecutor()

        # Register built-in/default tools
        if include_default_tools:
            self.tool_executor.registry.register(CompletionTool())

        # Register custom tools
        if tools:
            for tool in tools:
                self.tool_executor.registry.register(tool)

    # ---------------------------- Events -----------------------------
    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.event_listener:
            return
        evt = Event(type=event_type, payload=payload)
        try:
            res = self.event_listener(evt)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.warning(f"Event listener raised error for {event_type}: {e}")

    # --------------------------- Utilities ---------------------------
    def _build_system_prompt(self, goal: str, success_criteria: list[str] | None = None) -> str:
        # Get available tools info
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

        # Default success criteria if none provided
        if success_criteria is None:
            success_criteria = [
                "Understand the task requirements",
                "Use available tools when needed",
                "Provide clear reasoning for actions",
                "Complete the task successfully",
            ]

        return PromptBuilder.build_react_system_prompt(
            agent_name=self.name,
            agent_instruction=self.instruction,
            goal_description=goal,
            success_criteria=success_criteria,
            available_tools=available_tools,
        )

    # ---------------------------- API -------------------------------
    async def run_stream(
        self,
        task: str,
        *,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run the agent and stream tokens while emitting events for orchestration."""
        goal = goal or task
        system_prompt = self._build_system_prompt(goal, success_criteria)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        tools = self.tool_executor.get_openai_functions()
        iteration = 0
        done = False

        while not done and iteration < self.max_iterations:
            iteration += 1
            await self._emit("iteration_started", {"iteration": iteration})

            request = LLMRequest(
                messages=messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            await self._emit("llm_request", {
                "iteration": iteration,
                # Expose only safe fields
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "tools_count": len(tools),
            })

            response_stream = self.llm.ainvoke_stream(request)
            full_content = ""
            final_tool_calls = None

            async for chunk in response_stream:
                if chunk.content:
                    full_content += chunk.content
                    await self._emit("llm_chunk", {
                        "iteration": iteration,
                        "content": chunk.content,
                    })
                    yield chunk.content
                if chunk.tool_calls:
                    final_tool_calls = chunk.tool_calls
                    await self._emit("llm_tool_calls_detected", {
                        "iteration": iteration,
                        "tool_calls": final_tool_calls,
                    })

            assistant_message = {"role": "assistant", "content": full_content}
            if final_tool_calls:
                assistant_message["tool_calls"] = final_tool_calls
            messages.append(assistant_message)
            await self._emit("assistant_message", {
                "iteration": iteration,
                "content": full_content,
                "tool_calls": final_tool_calls,
            })

            # Execute tools if any were called
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
                        await self._emit("tool_execution_started", {
                            "iteration": iteration,
                            "tool_name": tool_name,
                            "tool_call_id": tool_id,
                            "args": tool_args,
                        })

                        result = await self.tool_executor.execute_tool(tool_name, tool_args)

                        # Naive completion detection (kept simple to avoid breaking changes)
                        if tool_name == "completion":
                            done = True
                            await self._emit("completion_signaled", {
                                "iteration": iteration,
                                "by_tool": tool_name,
                                "result": result,
                            })

                        tool_result = str(result.get("result", result))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": tool_result,
                            }
                        )

                        await self._emit("tool_execution_finished", {
                            "iteration": iteration,
                            "tool_name": tool_name,
                            "tool_call_id": tool_id,
                            "success": bool(result.get("success", True)),
                            "result": result.get("result"),
                        })

                        yield f"\n[Tool {tool_name}: {tool_result}]\n"

                    except Exception as e:
                        error_msg = f"{e}"
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": f"Error: {error_msg}",
                            }
                        )
                        await self._emit("tool_execution_error", {
                            "iteration": iteration,
                            "tool_name": tool_name,
                            "tool_call_id": tool_id,
                            "error": error_msg,
                        })
                        yield f"\n[Tool Error: {error_msg}]\n"

            await self._emit("iteration_finished", {"iteration": iteration, "done": done})

        await self._emit("agent_completed", {"iterations": iteration, "done": done})

    async def run(
        self,
        task: str,
        *,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
    ) -> str:
        """Run the agent to completion and return a single string response."""
        result = ""
        async for content in self.run_stream(task, goal=goal, success_criteria=success_criteria):
            result += content
        return result

    # ---------------------------- Tools ------------------------------
    def add_tool(self, tool: Any) -> None:
        """Add a custom tool to the agent."""
        self.tool_executor.registry.register(tool)