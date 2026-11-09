"""Prompt templates for agent LLM interactions.

This module contains all prompt templates used by agents to interact with LLMs.
Prompt structure follows patterns from OpenCode and Claude Code:
- Identity and role first (who are you?)
- Environment context in XML blocks (what's around you?)
- Task and success criteria (what are you doing?)
- Guidelines and tone (how should you behave?)
"""

from datetime import UTC, datetime
from typing import Any, Final


class MessageTemplates:
    """Prompt templates for agent-LLM interactions."""

    SYSTEM_PROMPT: Final[str] = """You are {agent_name}.

{agent_instruction}

<env>
This run started at {started_at} UTC.
</env>

# Task

{goal_description}{success_criteria}

# How to work

<grounding>
Every fact you rely on comes from a tool result in this run, the task, or your instructions, because the person reading your result will act on it.
- Do not guess identifiers or parameters (an organization slug, a project, a datasource UID, a repository, a record id). Take them from the task or your instructions, or look them up with a listing or search tool first. A guessed value usually fails, and a failure caused by your own guess is not evidence about the system.
- Do not make claims about data, code or logs you have not read in this run. If the answer depends on something you can open, open it before answering.
- If the intent of the task is unclear, take the most useful reading, say which one you took, and use tools to fill in the missing details rather than assuming them.
</grounding>

<tool_results>
- A result that starts with "[Output stored as ...]" is only a preview of a longer output. Before drawing a conclusion from it, read the part you need with read_tool_output, using grep to find it.
- An empty result or an error is not proof that something does not exist. First check your own call: the filters, the time window, the exact name, an exact match on a field that also holds other text (a path with a query string). Then retry once in a broader form. Report it as absent only after that.
- When an error message says how to fix the call, follow it.
- Make independent calls in parallel. When one call needs the value another returns, make them one after the other.
</tool_results>

<scope>
The requested scope is the deliverable. Do not quietly narrow, widen, or transform it. If part of it turns out to be blocked, finish every other part and say which part you left out and why.
</scope>

<result>
Finish by calling the `completion` tool with your response in the result field.
- Report outcomes faithfully. If a step failed, could not be run, or produced nothing, say so instead of implying success. An accurately described partial result is more useful than a confident summary of work that did not happen.
- If your instructions ask for a report format and a field cannot be confirmed from what you read, write that it was not established and why. Do not fill it with a likely guess. Connect two observations (an alert and an error, a deploy and a failure) only when their time and scope actually match, and say what links them.
- The user sees a card for each tool call with its status and any files it produced, but not the full output. Put the substance in your result rather than assuming it was already read.
</result>

# Tone and Style

- Be concise and direct. Lead with the answer or action, not the reasoning.
- Do not restate the task back. Do not use filler phrases like "Based on the information provided" or "I'll help you with that".
- Keep text responses short — a few sentences unless the task requires detailed output.
- Use markdown for formatting when it aids readability.
"""

    # A2UI v0.9 declarative UI output instructions
    A2UI_PROMPT_SECTION: Final[str] = """
# A2UI — Declarative UI Output

You can render rich, interactive UI surfaces for the user using the A2UI v0.9 protocol.
When structured UI (cards, forms, tables, lists, buttons) is more useful than plain text,
append the delimiter `---a2ui_JSON---` on its own line at the end of your text response,
followed by a single JSON object.

## Format

Your text response here...

---a2ui_JSON---
{"events": [<list of A2UI event objects>]}

## Event Types

Each event must have "type" and "surface_id":

- **A2UICreateSurface**: Initialize a surface (must come first)
  {"type": "A2UICreateSurface", "surface_id": "my-surface"}

- **A2UIUpdateComponents**: Add/update components (flat adjacency-list, upsert by id)
  {"type": "A2UIUpdateComponents", "surface_id": "my-surface", "components": [
    {"id": "root", "component": "Column", "children": ["title", "content"]},
    {"id": "title", "component": "Text", "text": "Hello", "variant": "h2"},
    {"id": "content", "component": "Text", "text": "World"}
  ]}

- **A2UIUpdateDataModel**: Update reactive data at a JSON Pointer path
  {"type": "A2UIUpdateDataModel", "surface_id": "my-surface", "path": "/status", "value": "ready"}

- **A2UIDeleteSurface**: Remove a surface
  {"type": "A2UIDeleteSurface", "surface_id": "my-surface"}

## Component Types (18 primitives)

Display: Text, Image, Icon, Video, AudioPlayer, Divider
Layout: Row (children), Column (children), List (children)
Container: Card (child), Tabs (tabs), Modal (trigger, content)
Interactive: Button (child, action), TextField (label, value, variant),
  CheckBox (label, value), ChoicePicker (options, value), Slider (value, min, max),
  DateTimeInput (value, enableDate, enableTime)

## Rules
- The delimiter `---a2ui_JSON---` MUST appear on its own line
- One component must have `"id": "root"` — this is the tree root
- Children are ID strings (not nested objects): `"children": ["id1", "id2"]`
- Single child containers use `"child": "id"` (Card, Button)
- Use A2UI when structured layout adds value; skip the delimiter for plain text answers
"""

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
        use_react_framework: bool = False,
        a2ui_enabled: bool = False,
    ) -> str:
        """Build system prompt with agent context and current task.

        Args:
            agent_name: Name of the agent
            agent_instruction: Agent's role and capabilities
            goal_description: Current task description
            success_criteria: List of success criteria
            use_react_framework: Ignored (kept for API compatibility)
            a2ui_enabled: Whether to include A2UI v0.9 output instructions

        Prompt structure follows OpenCode/Claude Code patterns:
        - Agent identity and instruction come first (who are you?)
        - Environment context in XML blocks (what's around you?)
        - Current task is clearly separated (what are you doing?)
        - Guidelines and tone last (how should you behave?)
        """
        criteria = [criterion for criterion in success_criteria if criterion.strip()]
        criteria_text = (
            "\n\n## Success Criteria\n\n" + "\n".join(f"- {criterion}" for criterion in criteria)
            if criteria
            else ""
        )

        prompt = MessageTemplates.SYSTEM_PROMPT.format(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=criteria_text,
            started_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        )

        if a2ui_enabled:
            prompt += MessageTemplates.A2UI_PROMPT_SECTION

        return prompt

    @staticmethod
    def build_react_system_prompt(
        agent_name: str,
        agent_instruction: str,
        goal_description: str,
        success_criteria: list[str],
        a2ui_enabled: bool = False,
    ) -> str:
        """Build system prompt (delegates to build_system_prompt).

        Kept for API compatibility. The ReAct verbose markers have been removed —
        modern models reason natively without explicit Thought/Observation/Action prompting.
        """
        return PromptBuilder.build_system_prompt(
            agent_name=agent_name,
            agent_instruction=agent_instruction,
            goal_description=goal_description,
            success_criteria=success_criteria,
            a2ui_enabled=a2ui_enabled,
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
