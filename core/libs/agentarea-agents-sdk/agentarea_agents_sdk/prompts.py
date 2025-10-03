"""Prompt templates for agent LLM interactions.

This module contains all prompt templates used by agents to interact with LLMs.
Following patterns from frameworks like AutoGen, CrewAI, and LangGraph,
prompts are treated as core agentic components.
"""

from typing import Any, Final, TypedDict


class ToolInfo(TypedDict, total=False):
    """Type definition for tool information."""

    name: str
    description: str
    type: str
    function: dict[str, Any]


class MessageTemplates:
    """Prompt templates for agent-LLM interactions following framework best practices."""

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
- Call the completion tool when you have successfully finished the task

Remember: You are {agent_name} - stay in character and leverage your specific capabilities."""

    # ReAct framework system prompt - enhanced reasoning pattern
    REACT_SYSTEM_PROMPT: Final[
        str
    ] = """You are {agent_name}, an AI agent that follows the ReAct (Reasoning + Acting) framework.

{agent_instruction}

## Current Task
Goal: {goal_description}

Success Criteria:
{success_criteria}

## Available Tools
{available_tools}

## ReAct Framework Instructions
You MUST follow this exact pattern for EVERY action you take:

1. **Thought**: First, analyze the current situation and what needs to be done
2. **Observation**: Note what information you have and what you're missing
3. **Action**: Decide on the next action (tool call or response)
4. **Result**: After a tool call, observe and interpret the results

For each step, explicitly state your reasoning process using these markers:

**Thought:** [Your reasoning about the current situation]
**Observation:** [What you observe from previous results or current context]
**Action:** [What action you decide to take and why]

After receiving tool results, always provide:
**Result Analysis:** [Interpretation of the tool results and what they mean]

Example flow:
**Thought:** I need to search for information about X to complete the task.
**Observation:** I don't have current information about X in my knowledge.
**Action:** I'll use the web_search tool to find recent information.
[Tool call happens]
**Result Analysis:** The search returned Y, which shows that...
**Thought:** Now that I have Y, I need to...

CRITICAL RULES:
- NEVER call tools without first showing your **Thought** and **Observation**
- NEVER call completion without first demonstrating your work step-by-step
- You must show your reasoning process for EVERY action, including the final completion
- The completion tool requires detailed summary, reasoning, and result - prepare these thoughtfully

Continue this pattern until the task is complete, then use the completion tool with comprehensive details.

Remember: ALWAYS show your reasoning before taking actions. Users want to see your thought process."""

    # Status and feedback messages (not part of system prompt)
    ITERATION_STATUS: Final[str] = "Iteration {current_iteration}/{max_iterations}"
    BUDGET_STATUS: Final[str] = "Budget remaining: ${budget_remaining:.2f}"

    BUDGET_WARNING: Final[str] = (
        "Warning: Budget usage at {percentage:.1f}% (${used:.2f}/${total:.2f})"
    )
    BUDGET_EXCEEDED: Final[str] = "Budget exceeded: ${used:.2f}/${total:.2f}. Stopping execution."

    TOOL_CALL_SUMMARY: Final[str] = "Called {tool_name} with result: {result}"
    ITERATION_SUMMARY: Final[str] = (
        "Iteration {iteration}: {tool_calls} tool calls, ${cost:.4f} spent"
    )


class PromptBuilder:
    """Builder for constructing agent prompts with dynamic context."""

    @staticmethod
    def build_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[ToolInfo],
        use_react_framework: bool = False,
    ) -> str:
        """Build system prompt with agent context and current task.

        Args:
            agent_name: Name of the agent
            agent_instruction: Agent's role and capabilities
            goal_description: Current task description
            success_criteria: List of success criteria
            available_tools: List of available tools
            use_react_framework: Whether to use ReAct framework prompting

        Following best practices from AutoGen, LangChain, and ADK:
        - Agent identity and instruction come first (who are you?)
        - Current task is clearly separated (what are you doing?)
        - Tools are listed for reference (what can you use?)
        - Status info like iteration/budget is kept separate from system prompt
        """
        criteria_text = "\n".join(f"- {criteria}" for criteria in success_criteria)

        # Handle both old format and OpenAI function format for tools
        def get_tool_info(tool: ToolInfo) -> tuple[str, str]:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                return func.get("name", "Unknown"), func.get("description", "No description")
            else:
                return tool.get("name", "Unknown"), tool.get("description", "No description")

        tools_text = "\n".join(
            f"- {name}: {desc}" for name, desc in (get_tool_info(tool) for tool in available_tools)
        )

        # Choose template based on framework preference
        template = (
            MessageTemplates.REACT_SYSTEM_PROMPT
            if use_react_framework
            else MessageTemplates.SYSTEM_PROMPT
        )

        return template.format(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=criteria_text,
            available_tools=tools_text,
        )

    @staticmethod
    def build_react_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        available_tools: list[ToolInfo],
    ) -> str:
        """Build system prompt with ReAct framework instructions.

        This is a convenience method that explicitly uses ReAct framework.
        """
        return PromptBuilder.build_system_prompt(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=success_criteria,
            available_tools=available_tools,
            use_react_framework=True,
        )

    @staticmethod
    def build_iteration_status(current_iteration: int, max_iterations: int) -> str:
        """Build iteration status message (separate from system prompt)."""
        return MessageTemplates.ITERATION_STATUS.format(
            current_iteration=current_iteration, max_iterations=max_iterations
        )

    @staticmethod
    def build_budget_status(budget_remaining: float) -> str:
        """Build budget status message (separate from system prompt)."""
        return MessageTemplates.BUDGET_STATUS.format(budget_remaining=budget_remaining)

    @staticmethod
    def build_tool_call_summary(tool_name: str, result: Any) -> str:
        """Build tool call summary message."""
        result_str = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
        return MessageTemplates.TOOL_CALL_SUMMARY.format(tool_name=tool_name, result=result_str)

    @staticmethod
    def build_iteration_summary(iteration: int, tool_calls: int, cost: float) -> str:
        """Build iteration summary message."""
        return MessageTemplates.ITERATION_SUMMARY.format(
            iteration=iteration, tool_calls=tool_calls, cost=cost
        )
