"""SubAgent middleware for delegating tasks to isolated agents.

Inspired by LangChain Deep Agents
Original work Copyright (c) LangChain, Inc. under MIT License
https://github.com/langchain-ai/langchain
"""

import logging
from typing import Any

from ..tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


TASK_SYSTEM_PROMPT = """## `task` (subagent spawner)

You have access to a `task` tool to launch short-lived subagents that handle isolated tasks. These agents are ephemeral — they live only for the duration of the task and return a single result.

When to use the task tool:
- When a task is complex and multi-step, and can be fully delegated in isolation
- When a task is independent of other tasks and can run in parallel
- When a task requires focused reasoning or heavy token/context usage that would bloat the orchestrator thread
- When sandboxing improves reliability (e.g. code execution, structured searches, data formatting)
- When you only care about the output of the subagent, and not the intermediate steps (ex. performing a lot of research and then returned a synthesized report, performing a series of computations or lookups to achieve a concise, relevant answer.)

CRITICAL RULE - Planning Before Delegation:
When you have access to `write_todos` tool AND the task has 3+ distinct steps:

YOU MUST FOLLOW THIS SEQUENCE:
1. FIRST: Create a complete plan using `write_todos` (list ALL steps, mark first as in_progress)
2. SECOND: YOU work through your plan step-by-step YOURSELF, updating todos as you progress
3. THIRD: ONLY if you encounter a specific independent subtask that benefits from isolation, you may delegate THAT SUBTASK ONLY to `task`

CRITICAL: After creating the plan, YOU must execute it step-by-step YOURSELF. DO NOT delegate the entire main task to a subagent - that defeats the purpose of planning! The plan is for YOU to follow and execute, not for a subagent to execute.

The user gave YOU the task because they want to see YOUR work process. Delegating everything to a subagent hides your work from the user.

NEVER skip planning and go directly to task delegation for multi-step tasks. The user needs visibility into both your planning AND execution process.

If the task is simple (1-2 steps), you can work on it directly without planning or delegation.

Subagent lifecycle:
1. **Spawn** → Provide clear role, instructions, and expected output
2. **Run** → The subagent completes the task autonomously
3. **Return** → The subagent provides a single structured result
4. **Reconcile** → Incorporate or synthesize the result into the main thread

When NOT to use the task tool:
- If you need to see the intermediate reasoning or steps after the subagent has completed (the task tool hides them)
- If the task is trivial (a few tool calls or simple lookup)
- If delegating does not reduce token usage, complexity, or context switching
- If splitting would add latency without benefit
- NEVER delegate the entire main user task to a subagent - your plan is for YOU to execute, not for delegation
- If you created a plan with write_todos, YOU must work through it yourself - don't immediately delegate the entire task
- Only delegate specific independent subtasks that genuinely benefit from isolation (e.g., parallel research, sandboxed execution)

## Important Task Tool Usage Notes to Remember
- Whenever possible, parallelize the work that you do. This is true for both tool_calls, and for tasks. Whenever you have independent steps to complete - make tool_calls, or kick off tasks (subagents) in parallel to accomplish them faster. This saves time for the user, which is incredibly important.
- Remember to use the `task` tool to silo independent tasks within a multi-part objective.
- You should use the `task` tool whenever you have a complex task that will take multiple steps, and is independent from other tasks that the agent needs to complete. These agents are highly competent and efficient."""


DEFAULT_GENERAL_PURPOSE_DESCRIPTION = (
    "General-purpose agent for researching complex questions, searching for files and content, "
    "and executing multi-step tasks. When you are searching for a keyword or file and are not "
    "confident that you will find the right match in the first few tries use this agent to "
    "perform the search for you. This agent has access to all tools as the main agent."
)


class TaskTool(BaseTool):
    """Tool for delegating tasks to subagents."""

    def __init__(self, subagent_manager: "SubAgentMiddleware"):
        self.subagent_manager = subagent_manager

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        """Generate dynamic description with available subagents."""
        available_agents = []

        if self.subagent_manager.general_purpose_agent:
            available_agents.append(f"- general-purpose: {DEFAULT_GENERAL_PURPOSE_DESCRIPTION}")

        for agent_spec in self.subagent_manager.subagents:
            available_agents.append(f"- {agent_spec['name']}: {agent_spec['description']}")

        agents_text = "\n".join(available_agents)

        return f"""Launch an ephemeral subagent to handle complex, multi-step independent tasks with isolated context windows.

Available agent types and the tools they have access to:
{agents_text}

When using the Task tool, you must specify a subagent_type parameter to select which agent type to use.

## Example Usage

# Example: After planning a multi-step task, delegate a specific research subtask
task(
    description="Research best practices for error handling in async Python. Focus on context managers, exception chaining, and logging patterns. Return a concise summary with 3-5 key recommendations.",
    subagent_type="general-purpose"
)

## Usage notes:
1. Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
2. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.
3. Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.
4. The agent's outputs should generally be trusted
5. Clearly tell the agent whether you expect it to create content, perform analysis, or just do research (search, file reads, web fetches, etc.), since it is not aware of the user's intent
6. If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
7. When only the general-purpose agent is provided, you should use it for all tasks. It is great for isolating context and token usage, and completing specific, complex tasks, as it has all the same capabilities as the main agent."""

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Detailed task description for the subagent. Be very specific about what you want the subagent to do and what information to return.",
                },
                "subagent_type": {
                    "type": "string",
                    "description": "Type of subagent to use (e.g., 'general-purpose' or custom type)",
                },
            },
            "required": ["description", "subagent_type"],
        }

    async def execute(self, description: str, subagent_type: str, **kwargs) -> dict[str, Any]:
        """Execute subagent task."""
        return await self.subagent_manager.run_subagent(description, subagent_type)


class SubAgentMiddleware:
    """Middleware that provides subagent capabilities via task tool.

    Inspired by LangChain Deep Agents SubAgentMiddleware.
    """

    def __init__(
        self,
        default_agent_class: type,
        default_agent_kwargs: dict[str, Any] | None = None,
        subagents: list[dict[str, Any]] | None = None,
        general_purpose_agent: bool = True,
        system_prompt: str = TASK_SYSTEM_PROMPT,
        parent_tools: list | None = None,
    ):
        """Initialize SubAgent middleware.

        Args:
            default_agent_class: Agent class to use for subagents (e.g., StatefulAgent)
            default_agent_kwargs: Default kwargs for creating agents
            subagents: List of custom subagent specifications
            general_purpose_agent: Whether to include general-purpose subagent
            system_prompt: Custom system prompt override
            parent_tools: Tools from parent agent to pass to subagents
        """
        self.default_agent_class = default_agent_class
        self.default_agent_kwargs = default_agent_kwargs or {}
        self.subagents = subagents or []
        self.general_purpose_agent = general_purpose_agent
        self.system_prompt = system_prompt
        self.parent_tools = parent_tools or []

        self._compiled_agents: dict[str, Any] = {}
        self._task_tool: TaskTool | None = None

    def get_tools(self) -> list[BaseTool]:
        """Get tools to add to agent."""
        if self._task_tool is None:
            self._task_tool = TaskTool(self)
        return [self._task_tool]

    async def run_subagent(self, description: str, subagent_type: str) -> dict[str, Any]:
        """Run a subagent with given task description."""
        # Get or create subagent
        if subagent_type not in self._compiled_agents:
            agent = self._create_subagent(subagent_type)
            if agent is None:
                allowed_types = list(self._get_available_agent_types())
                return {
                    "error": f"Subagent type '{subagent_type}' not found. Available: {', '.join(allowed_types)}"
                }
            self._compiled_agents[subagent_type] = agent

        agent = self._compiled_agents[subagent_type]

        logger.info(f"Running subagent '{subagent_type}' with task: {description[:100]}...")

        try:
            # Run subagent with isolated task
            result = await agent.run(description)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Subagent '{subagent_type}' failed: {e}")
            return {"success": False, "error": str(e)}

    def _create_subagent(self, subagent_type: str) -> Any:
        """Create a subagent instance."""
        if subagent_type == "general-purpose" and self.general_purpose_agent:
            # Create general-purpose agent with default tools from parent
            agent_kwargs = {**self.default_agent_kwargs}
            if self.parent_tools:
                agent_kwargs["tools"] = self.parent_tools
            return self.default_agent_class(**agent_kwargs)

        # Look for custom subagent
        for spec in self.subagents:
            if spec["name"] == subagent_type:
                agent_kwargs = {**self.default_agent_kwargs}
                agent_kwargs["instruction"] = spec.get("system_prompt", spec.get("description", ""))

                if "tools" in spec:
                    agent_kwargs["tools"] = spec["tools"]
                elif self.parent_tools:
                    agent_kwargs["tools"] = self.parent_tools

                return self.default_agent_class(**agent_kwargs)

        return None

    def _get_available_agent_types(self) -> list[str]:
        """Get list of available subagent types."""
        types = []
        if self.general_purpose_agent:
            types.append("general-purpose")
        types.extend(spec["name"] for spec in self.subagents)
        return types

    async def before_llm_call(self, state: dict) -> dict[str, Any] | None:
        """Add system prompt before LLM call."""
        # System prompt will be added at agent initialization
        return None

    async def after_llm_call(self, state: dict, response: Any) -> dict[str, Any] | None:
        return None

    async def before_tool_call(
        self, tool_call: dict, state: dict
    ) -> tuple[dict, dict[str, Any] | None]:
        # Enforce planning-before-delegation rule programmatically
        if tool_call.get("function", {}).get("name") == "task":
            # Check if todos exist in state (plan was created)
            todos = state.get("todos", [])

            if not todos or len(todos) == 0:
                # BLOCK task delegation without plan
                tool_call["_skip_execution"] = True
                tool_call["_result"] = {
                    "success": False,
                    "error": (
                        "Planning required before delegation. You MUST create a plan using write_todos before delegating tasks. "
                        "For multi-step work (3+ steps): FIRST create a complete plan showing all steps, "
                        "THEN work through your plan step-by-step, and ONLY AFTER that you may delegate specific subtasks if isolation benefits them. "
                        "This ensures the user sees your planning process. Call write_todos() with your plan first."
                    )
                }
                return tool_call, None

        return tool_call, None

    async def after_tool_call(
        self, tool_call: dict, result: Any, state: dict
    ) -> tuple[Any, dict[str, Any] | None]:
        return result, None
