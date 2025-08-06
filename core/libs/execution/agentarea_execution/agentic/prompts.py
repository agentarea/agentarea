"""Prompt templates for agent LLM interactions.

This module contains all prompt templates used by agents to interact with LLMs.
Following patterns from frameworks like AutoGen, CrewAI, and LangGraph, 
prompts are treated as core agentic components.
"""

from typing import Any, Final


class MessageTemplates:
    """Prompt templates for agent-LLM interactions following framework best practices."""
    
    # Main system prompt - follows AutoGen/LangChain patterns
    SYSTEM_PROMPT: Final[str] = """You are {agent_name}, an AI agent with the following role:

{agent_instruction}

CURRENT TASK:
{goal_description}

SUCCESS CRITERIA:
{success_criteria}

AVAILABLE TOOLS:
{available_tools}

INSTRUCTIONS:
- Follow your role and capabilities described above
- Work systematically towards completing the current task
- Use available tools when they can help achieve the goal
- Provide clear, actionable responses
- Ask for clarification if anything is unclear
- Call the task_complete tool when you have successfully finished the task

Remember: You are {agent_name} - stay in character and leverage your specific capabilities."""

    # Status and feedback messages (not part of system prompt)
    ITERATION_STATUS: Final[str] = "Iteration {current_iteration}/{max_iterations}"
    BUDGET_STATUS: Final[str] = "Budget remaining: ${budget_remaining:.2f}"
    
    BUDGET_WARNING: Final[str] = "Warning: Budget usage at {percentage:.1f}% (${used:.2f}/${total:.2f})"
    BUDGET_EXCEEDED: Final[str] = "Budget exceeded: ${used:.2f}/${total:.2f}. Stopping execution."
    
    TOOL_CALL_SUMMARY: Final[str] = "Called {tool_name} with result: {result}"
    ITERATION_SUMMARY: Final[str] = "Iteration {iteration}: {tool_calls} tool calls, ${cost:.4f} spent"


class PromptBuilder:
    """Builder for constructing agent prompts with dynamic context."""
    
    @staticmethod
    def build_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[dict]
    ) -> str:
        """Build system prompt with agent context and current task.
        
        Following best practices from AutoGen, LangChain, and ADK:
        - Agent identity and instruction come first (who are you?)
        - Current task is clearly separated (what are you doing?)
        - Tools are listed for reference (what can you use?)
        - Status info like iteration/budget is kept separate from system prompt
        """
        criteria_text = "\n".join(f"- {criteria}" for criteria in success_criteria)
        
        # Handle both old format and OpenAI function format for tools
        def get_tool_info(tool: dict) -> tuple[str, str]:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                return func.get("name", "Unknown"), func.get("description", "No description")
            else:
                return tool.get("name", "Unknown"), tool.get("description", "No description")
        
        tools_text = "\n".join(f"- {name}: {desc}" for name, desc in 
                               (get_tool_info(tool) for tool in available_tools))

        return MessageTemplates.SYSTEM_PROMPT.format(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=criteria_text,
            available_tools=tools_text
        )

    @staticmethod
    def build_iteration_status(current_iteration: int, max_iterations: int) -> str:
        """Build iteration status message (separate from system prompt)."""
        return MessageTemplates.ITERATION_STATUS.format(
            current_iteration=current_iteration,
            max_iterations=max_iterations
        )

    @staticmethod
    def build_budget_status(budget_remaining: float) -> str:
        """Build budget status message (separate from system prompt)."""
        return MessageTemplates.BUDGET_STATUS.format(budget_remaining=budget_remaining)

    @staticmethod
    def build_tool_call_summary(tool_name: str, result: Any) -> str:
        """Build tool call summary message."""
        result_str = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
        return MessageTemplates.TOOL_CALL_SUMMARY.format(
            tool_name=tool_name,
            result=result_str
        )

    @staticmethod
    def build_iteration_summary(iteration: int, tool_calls: int, cost: float) -> str:
        """Build iteration summary message."""
        return MessageTemplates.ITERATION_SUMMARY.format(
            iteration=iteration,
            tool_calls=tool_calls,
            cost=cost
        )