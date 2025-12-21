"""Base middleware protocol and stack implementation."""

from typing import Any, Protocol

from ..models.llm_model import LLMResponse


class Middleware(Protocol):
    """Protocol for middleware components.

    Middleware can modify state and control execution flow.
    Methods return dict of state updates to apply, or None.
    """

    async def before_llm_call(self, state: dict) -> dict[str, Any] | None:
        """Called before each LLM call.

        Args:
            state: Agent state (mutable dict)

        Returns:
            Dict of state updates to apply, or None
        """
        ...

    async def after_llm_call(self, state: dict, response: LLMResponse) -> dict[str, Any] | None:
        """Called after LLM responds.

        Args:
            state: Agent state (mutable dict)
            response: LLM response

        Returns:
            Dict of state updates to apply, or None
        """
        ...

    async def before_tool_call(self, tool_call: dict, state: dict) -> tuple[dict, dict[str, Any] | None]:
        """Called before tool execution.

        Args:
            tool_call: Tool call dict (can be modified)
            state: Agent state (mutable dict)

        Returns:
            Tuple of (modified_tool_call, state_updates)

        Note:
            Set tool_call['_skip_execution'] = True to skip execution.
            Set tool_call['_result'] to provide result without execution.
        """
        ...

    async def after_tool_call(self, tool_call: dict, result: Any, state: dict) -> tuple[Any, dict[str, Any] | None]:
        """Called after tool execution.

        Args:
            tool_call: Tool call dict
            result: Tool execution result (can be modified)
            state: Agent state (mutable dict)

        Returns:
            Tuple of (modified_result, state_updates)
        """
        ...


class MiddlewareStack:
    """Manages execution of multiple middleware."""

    def __init__(self, middlewares: list[Middleware]):
        self.middlewares = middlewares

    async def run_before_llm(self, state: dict) -> None:
        """Run before_llm_call hooks and apply state updates."""
        for mw in self.middlewares:
            updates = await mw.before_llm_call(state)
            if updates:
                state.update(updates)

    async def run_after_llm(self, state: dict, response: LLMResponse) -> None:
        """Run after_llm_call hooks and apply state updates."""
        for mw in self.middlewares:
            updates = await mw.after_llm_call(state, response)
            if updates:
                state.update(updates)

    async def run_before_tool(self, tool_call: dict, state: dict) -> dict:
        """Run before_tool_call hooks and apply state updates."""
        for mw in self.middlewares:
            tool_call, updates = await mw.before_tool_call(tool_call, state)
            if updates:
                state.update(updates)
        return tool_call

    async def run_after_tool(self, tool_call: dict, result: Any, state: dict) -> Any:
        """Run after_tool_call hooks and apply state updates."""
        for mw in self.middlewares:
            result, updates = await mw.after_tool_call(tool_call, result, state)
            if updates:
                state.update(updates)
        return result
