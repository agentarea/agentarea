"""Synchronous agent execution runner for testing and framework-agnostic execution."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .base import AgentGoal, BaseAgentRunner, ExecutionResult, Message, RunnerConfig

logger = logging.getLogger(__name__)


@dataclass
class SyncExecutionState:
    """Execution state for sync runner."""
    goal: AgentGoal
    messages: list[Message] = field(default_factory=list)
    current_iteration: int = 0
    success: bool = False
    final_response: str | None = None
    total_cost: float = 0.0


class SyncAgentRunner(BaseAgentRunner):
    """Synchronous agent execution runner for testing and simple use cases.
    
    This runner provides a framework-agnostic way to execute agent workflows
    without Temporal dependencies, making it ideal for testing and simple
    automation scenarios.
    """

    def __init__(
        self,
        llm_model,
        tool_executor=None,
        goal_evaluator=None,
        config: RunnerConfig | None = None,
    ):
        """Initialize the sync runner.
        
        Args:
            llm_model: LLM model for making completions
            tool_executor: Tool executor for running tools (optional)
            goal_evaluator: Goal progress evaluator (optional)
            config: Runner configuration (optional)
        """
        super().__init__(config)
        self.llm_model = llm_model

        # Import here to avoid circular dependencies
        from ..services.goal_progress_evaluator import GoalProgressEvaluator
        from ..tools.tool_executor import ToolExecutor

        self.tool_executor = tool_executor or ToolExecutor()
        self.goal_evaluator = goal_evaluator or GoalProgressEvaluator()

    async def run(self, goal: AgentGoal) -> ExecutionResult:
        """Execute the agent workflow synchronously.
        
        Args:
            goal: The goal to achieve
            
        Returns:
            ExecutionResult with final results
        """
        state = SyncExecutionState(goal=goal)

        # Add system message
        system_prompt = self._build_system_prompt(goal)
        state.messages.append(Message(role="system", content=system_prompt))

        logger.info(f"Starting sync agent execution for goal: {goal.description}")

        # Use the unified main loop
        result = await self._execute_main_loop(state)

        return result

    async def _execute_iteration(self, state: SyncExecutionState) -> None:
        """Execute a single iteration."""
        # Import here to avoid circular dependencies
        from ..models.llm_model import LLMRequest

        # Prepare LLM request
        messages = [{"role": msg.role, "content": msg.content} for msg in state.messages]

        # Get available tools
        tools = self.tool_executor.get_openai_functions()

        request = LLMRequest(
            messages=messages,
            tools=tools if tools else None,
            temperature=self.config.temperature
        )

        # Call LLM
        response = await self.llm_model.complete(request)
        state.total_cost += response.cost

        # Add assistant message
        state.messages.append(Message(
            role="assistant",
            content=response.content
        ))

        # Handle tool calls
        if response.tool_calls:
            await self._handle_tool_calls(state, response.tool_calls)

        # Evaluate goal progress
        await self._evaluate_goal_progress(state)

    async def _handle_tool_calls(self, state: SyncExecutionState, tool_calls: list[dict[str, Any]]) -> None:
        """Handle tool calls from LLM response."""
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"]["arguments"]

            # Parse arguments if they're a string
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

            try:
                # Execute tool
                result = await self.tool_executor.execute_tool(tool_name, tool_args)

                # Add tool result message
                content = result.get("result", "")
                if result.get("error"):
                    content = f"Error: {result.get('error')}"
                elif not content:
                    content = str(result)

                state.messages.append(Message(
                    role="tool",
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                    content=str(content)
                ))

                # Check if completion tool was called
                if tool_name == "task_complete" and result.get("completed"):
                    state.success = True
                    state.final_response = result.get("result", "Task completed")

            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                state.messages.append(Message(
                    role="tool",
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                    content=f"Error: Tool execution failed: {e}"
                ))

    async def _evaluate_goal_progress(self, state: SyncExecutionState) -> None:
        """Evaluate if the goal has been achieved."""
        if state.success:
            return  # Already marked as successful by completion tool

        try:
            # Convert messages for evaluator
            messages_dict = [
                {"role": msg.role, "content": msg.content}
                for msg in state.messages
            ]

            evaluation = await self.goal_evaluator.evaluate_progress(
                goal_description=state.goal.description,
                success_criteria=state.goal.success_criteria,
                conversation_history=messages_dict,
                current_iteration=state.current_iteration
            )

            if evaluation.get("goal_achieved", False):
                state.success = True
                state.final_response = evaluation.get("final_response", "Goal achieved")

        except Exception as e:
            logger.warning(f"Goal evaluation failed: {e}")

    def _build_system_prompt(self, goal: AgentGoal) -> str:
        """Build system prompt for the agent."""
        tools_info = ""
        tools = self.tool_executor.get_available_tools()
        if tools:
            tool_names = [tool.name for tool in tools]
            tools_info = f"\n\nAvailable tools: {', '.join(tool_names)}"
            tools_info += "\nUse the 'task_complete' tool when you have successfully completed the task."

        return f"""You are an AI assistant helping to achieve the following goal:

GOAL: {goal.description}

SUCCESS CRITERIA:
{chr(10).join(f"- {criterion}" for criterion in goal.success_criteria)}

You have a maximum of {goal.max_iterations} iterations to complete this task.{tools_info}

Work step by step towards achieving the goal. When you have successfully completed the task, use the task_complete tool to signal completion."""
