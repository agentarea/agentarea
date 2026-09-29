"""Routing the tool calls of one model turn to their handlers."""

import asyncio

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import ZERO
    from agentarea_governance.domain.tool_calls import metered_tool_call_count

    from ..models import Message, ToolCall


from .completion import CompletionMixin
from .delegation import DelegationMixin
from .disclosure import ToolDisclosureMixin
from .tools import ToolExecutionMixin
from .user_input import UserInputMixin


class ToolDispatchMixin(
    ToolExecutionMixin, ToolDisclosureMixin, DelegationMixin, CompletionMixin, UserInputMixin
):
    """Routing the tool calls of one model turn to their handlers."""

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Execute tools, running agent delegations in parallel.

        Agent delegations are started concurrently as child workflows.
        Regular MCP/code tools run sequentially (they may have side effects
        that depend on execution order).
        """
        execution_limits = (self.state.effective_policy or {}).get("execution") or {}
        max_per_turn = execution_limits.get("max_tool_calls_per_turn")
        max_total = execution_limits.get("max_tool_calls_total")
        if not isinstance(max_per_turn, int) or max_per_turn <= 0:
            raise ApplicationError(
                "effective policy is missing execution.max_tool_calls_per_turn",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        if not isinstance(max_total, int) or max_total <= 0:
            raise ApplicationError(
                "effective policy is missing execution.max_tool_calls_total",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        metered_calls_this_turn = metered_tool_call_count(
            tool_call.function["name"] for tool_call in tool_calls
        )
        if metered_calls_this_turn > max_per_turn:
            raise ApplicationError(
                f"model requested {metered_calls_this_turn} metered tool calls; "
                f"policy allows {max_per_turn} per turn",
                type="ToolCallLimitExceeded",
                non_retryable=True,
            )
        attempted_total = self.state.tool_calls_used + metered_calls_this_turn
        if attempted_total > max_total:
            raise ApplicationError(
                f"tool-call budget exceeded: {attempted_total}/{max_total}",
                type="ToolCallLimitExceeded",
                non_retryable=True,
            )
        self.state.tool_calls_used = attempted_total

        completion_calls: list[ToolCall] = []
        agent_calls: list[ToolCall] = []
        regular_calls: list[ToolCall] = []
        recall_calls: list[ToolCall] = []
        skill_calls: list[ToolCall] = []
        read_output_calls: list[ToolCall] = []
        activate_source_calls: list[ToolCall] = []
        load_tools_calls: list[ToolCall] = []
        input_calls: list[ToolCall] = []

        for tool_call in tool_calls:
            tool_name = tool_call.function["name"]
            if tool_name in {"completion", "task_complete"}:
                completion_calls.append(tool_call)
            elif tool_name == "request_user_input":
                input_calls.append(tool_call)
            elif tool_name == "recall_history":
                recall_calls.append(tool_call)
            elif tool_name == "read_tool_output":
                read_output_calls.append(tool_call)
            elif tool_name == "activate_tool_source":
                activate_source_calls.append(tool_call)
            elif tool_name == "load_tools":
                load_tools_calls.append(tool_call)
            elif tool_name == "activate_skill":
                skill_calls.append(tool_call)
            elif tool_name in self._agent_tool_registry:
                agent_calls.append(tool_call)
            else:
                regular_calls.append(tool_call)

        if len(completion_calls) > 1:
            # Two completions in one message is a malformed answer, not a policy
            # breach, and every other malformed completion here is handed back
            # for repair rather than killing the run and the budget spent on it.
            # None of them is accepted: picking one would be guessing which
            # answer the model meant.
            for duplicate in completion_calls:
                self._reject_invalid_completion_arguments(
                    duplicate, "exactly one completion call may be made per turn"
                )
            completion_calls = []
        completion_call = completion_calls[0] if completion_calls else None

        # User-input requests are exclusive: the workflow must pause and get a
        # reply before any further side effects or final completion happen.
        if input_calls:
            await self._execute_request_user_input(input_calls[0])
            skipped_calls = [
                *input_calls[1:],
                *recall_calls,
                *read_output_calls,
                *activate_source_calls,
                *load_tools_calls,
                *skill_calls,
                *agent_calls,
                *regular_calls,
            ]
            if self._interaction_contract_enabled and completion_call:
                skipped_calls.append(completion_call)
            for skipped in skipped_calls:
                skipped_name = skipped.function.get("name", "unknown")
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=(
                            "Skipped because the workflow requested user input. "
                            "Call this tool again after the user reply if it is still needed."
                        ),
                        tool_call_id=skipped.id,
                        name=skipped_name,
                    )
                )
            return

        # Run recall_history and read_tool_output calls (can run in parallel with agent calls)
        for tool_call in recall_calls:
            await self._execute_recall_history(tool_call)

        for tool_call in read_output_calls:
            await self._execute_read_tool_output(tool_call)

        # Execute tool source activations (DYNAMIC mode — local, no activity)
        for tool_call in activate_source_calls:
            await self._execute_activate_tool_source(tool_call)

        # Execute OpenAPI load_tools meta-calls (issue #115 — local, no activity)
        for tool_call in load_tools_calls:
            await self._execute_load_openapi_tools(tool_call)

        # Execute skill activations (local, no activity needed)
        for tool_call in skill_calls:
            await self._execute_skill_activation(tool_call)

        # Run agent delegations in parallel (fan-out)
        if agent_calls:
            remaining_budget = self._budget.get_remaining()
            if remaining_budget <= ZERO:
                raise ApplicationError(
                    "no inference budget remains for agent delegation",
                    type="BudgetExceeded",
                    non_retryable=True,
                )
            child_budget = remaining_budget / len(agent_calls)
            if len(agent_calls) == 1:
                await self._execute_agent_delegation(
                    agent_calls[0],
                    child_budget,
                )
            else:
                workflow.logger.info(
                    f"Fan-out: delegating to {len(agent_calls)} agents in parallel"
                )
                tasks = [self._execute_agent_delegation(tc, child_budget) for tc in agent_calls]
                await asyncio.gather(*tasks)

        # Run regular tools sequentially
        for tool_call in regular_calls:
            await self._execute_mcp_tool(tool_call)

        # Handle completion last
        if completion_call:
            await self._handle_task_completion(completion_call)
