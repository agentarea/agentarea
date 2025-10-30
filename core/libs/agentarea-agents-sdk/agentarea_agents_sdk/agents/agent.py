"""High-level Agent class that simplifies the agentic SDK usage."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from ..models.llm_model import LLMModel, LLMRequest
from ..prompts import PromptBuilder, ToolInfo
from ..tools.completion_tool import CompletionTool
from ..tools.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class Agent:
    """High-level agent that simplifies LLM interaction with tools and structured prompts."""

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
    ):
        """Initialize the agent.

        Args:
            name: Agent name for prompts
            instruction: Agent instruction/role description
            model_provider: LLM provider type (e.g., "ollama_chat", "openai")
            model_name: Model name (e.g., "qwen2.5", "gpt-4")
            endpoint_url: Optional custom endpoint URL
            temperature: LLM temperature (0.0-1.0)
            max_tokens: Maximum tokens per response
            max_iterations: Maximum conversation iterations
            tools: Optional list of custom tools to register
            include_default_tools: Whether to include default tools (calculate, completion)
        """
        self.name = name
        self.instruction = instruction
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

        # Initialize LLM model
        self.model = LLMModel(
            provider_type=model_provider,
            model_name=model_name,
            endpoint_url=endpoint_url,
        )

        # Initialize tool executor
        self.tool_executor = ToolExecutor()

        # Register default tools if requested
        if include_default_tools:
            self.tool_executor.registry.register(CompletionTool())

        # Register custom tools if provided
        if tools:
            for tool in tools:
                self.tool_executor.registry.register(tool)

    def _build_system_prompt(self, goal: str, success_criteria: list[str] | None = None) -> str:
        """Build the system prompt using PromptBuilder."""
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

    async def _execute_agent_loop(
        self,
        task: str,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Internal method to execute the agent loop."""
        goal = goal or task
        system_prompt = self._build_system_prompt(goal, success_criteria)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        tools = self.tool_executor.get_openai_functions()
        iteration = 0
        done = False

        while not done and iteration < self.max_iterations:
            iteration += 1

            request = LLMRequest(
                messages=messages,
                tools=tools,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Stream the LLM response
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

            # Add assistant message to conversation
            assistant_message = {"role": "assistant", "content": full_content}
            if final_tool_calls:
                assistant_message["tool_calls"] = final_tool_calls
            messages.append(assistant_message)
            logger.debug("Assistant message: %s", assistant_message)

            # Execute tools if any were called
            if final_tool_calls:
                for tool_call in final_tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args_str = tool_call["function"]["arguments"]
                    tool_id = tool_call["id"]

                    try:
                        # Parse tool arguments
                        tool_args = (
                            json.loads(tool_args_str)
                            if isinstance(tool_args_str, str)
                            else tool_args_str
                        )

                        # Execute the tool
                        result = await self.tool_executor.execute_tool(tool_name, tool_args)

                        # Check for completion
                        if tool_name == "completion":
                            done = True

                        # Add tool result to conversation
                        tool_result = str(result.get("result", result))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": tool_result,
                            }
                        )

                        # Yield tool execution info if streaming
                        if stream:
                            yield f"\n[Tool {tool_name}: {tool_result}]\n"

                    except Exception as e:
                        error_msg = f"Error: {str(e)}"
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": error_msg,
                            }
                        )
                        if stream:
                            yield f"\n[Tool Error: {error_msg}]\n"

        if not stream:
            # Return the final conversation content
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
        """Run the agent on a task and stream content as it's generated.

        Args:
            task: The task/query to execute
            goal: Optional goal description (defaults to task)
            success_criteria: Optional list of success criteria

        Yields:
            Content strings as they are generated
        """
        async for content in self._execute_agent_loop(task, goal, success_criteria, stream=True):
            yield content

    async def run(
        self,
        task: str,
        goal: str | None = None,
        success_criteria: list[str] | None = None,
    ) -> str:
        """Run the agent on a task and return the complete result.

        Args:
            task: The task/query to execute
            goal: Optional goal description (defaults to task)
            success_criteria: Optional list of success criteria

        Returns:
            Complete response as a single string
        """
        result = ""
        async for content in self._execute_agent_loop(task, goal, success_criteria, stream=False):
            result += content
        return result

    def add_tool(self, tool: Any) -> None:
        """Add a custom tool to the agent.

        Args:
            tool: Tool instance that implements the BaseTool interface
        """
        self.tool_executor.registry.register(tool)

    def get_conversation_history(self) -> list[dict[str, Any]]:
        """Get the current conversation history.

        Returns:
            List of message dictionaries
        """
        # This would need to be implemented by storing messages in instance
        # For now, return empty list as this is a stateless implementation
        return []

    def reset(self) -> None:
        """Reset the agent state (clear conversation history)."""
        # For stateless implementation, this is a no-op
        # In a stateful version, this would clear stored messages
        pass


# Convenience function for quick agent creation
def create_agent(name: str, instruction: str, model: str, **kwargs) -> Agent:
    """Create an agent with simplified model specification.

    Args:
        name: Agent name
        instruction: Agent instruction/role
        model: Model in format "provider/model_name" (e.g., "ollama_chat/qwen2.5")
        **kwargs: Additional arguments passed to Agent constructor

    Returns:
        Configured Agent instance
    """
    if "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        raise ValueError(
            "Model must be in format 'provider/model_name' (e.g., 'ollama_chat/qwen2.5')"
        )

    return Agent(
        name=name,
        instruction=instruction,
        model_provider=provider,
        model_name=model_name,
        **kwargs,
    )
