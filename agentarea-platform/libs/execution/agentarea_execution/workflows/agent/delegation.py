"""Agent tools: delegating to another agent as a child workflow."""

import json
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_common.money import Money

    from ..models import Message, ToolCall

from ...models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    CreateDelegationTaskRequest,
    CreateDelegationTaskResult,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    DELEGATION_TIMEOUT,
    Activities,
    EventTypes,
)
from ..retry import make_retry_policy
from .approval import ToolApprovalMixin
from .patches import DELEGATION_ON_OWN_QUEUE_PATCH

LEGACY_DELEGATION_TASK_QUEUE = "agent-tasks"


class DelegationMixin(ToolApprovalMixin):
    """Agent tools: delegating to another agent as a child workflow."""

    async def _resolve_agent_tools(self) -> None:
        """Build agent tool registry by resolving agent names to IDs.

        Identifies agent-type tools from config and resolves their IDs
        so the workflow can start child workflows directly instead of
        routing through the activity-level polling delegation.
        """
        tools_config = self.state.agent_config.get("tools", [])
        agent_names = [
            str(tc.get("name"))
            for tc in tools_config
            if isinstance(tc, dict) and tc.get("type") == "agent" and tc.get("name")
        ]

        if not agent_names:
            return

        resolve_request = ResolveAgentToolsRequest(
            agent_names=agent_names,
            workspace_id=self.state.workspace_id,
            user_context_data=self.state.user_context_data,
        )

        result: ResolveAgentToolsResult = await workflow.execute_activity(
            Activities.RESOLVE_AGENT_TOOLS,
            args=[resolve_request],
            result_type=ResolveAgentToolsResult,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )

        # Build registry: sanitized tool name → {agent_id, agent_name, config}
        import re

        for agent_name, agent_id in result.agent_map.items():
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
            sanitized = re.sub(r"_+", "_", sanitized).strip("_")
            if not sanitized or sanitized[0].isdigit():
                sanitized = f"agent_{sanitized}"
            tool_name = f"delegate_to_{sanitized}"

            self._agent_tool_registry[tool_name] = {
                "agent_id": agent_id,
                "agent_name": agent_name,
            }

        if self._agent_tool_registry:
            workflow.logger.info(
                f"Registered {len(self._agent_tool_registry)} agent tools for delegation: "
                f"{list(self._agent_tool_registry.keys())}"
            )

    async def _execute_agent_delegation(
        self,
        tool_call: ToolCall,
        run_budget_usd: Money,
    ) -> None:
        """Delegate to another agent via Temporal child workflow.

        Instead of routing through execute_mcp_tool_activity (which polls),
        starts a child workflow directly and awaits its result. This is
        efficient (no polling), durable (survives worker crashes), and
        supports cancellation propagation.
        """
        from ..agent_execution_workflow import AgentExecutionWorkflow

        if not await self._gate_tool_call(tool_call):
            return
        tool_name = tool_call.function["name"]
        agent_info = self._agent_tool_registry[tool_name]
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Parse the message argument
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        message = tool_args.get("message", "")

        self._events.add_event(
            EventTypes.AGENT_DELEGATION_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "target_agent_id": agent_id,
                "target_agent_name": agent_name,
                "iteration": self.state.current_iteration,
                "message": message[:200],
            },
        )
        await self._publish_events_immediately()

        child_task_created = False
        child_cost_accounted = False
        try:
            # Create a task record in DB for the child agent
            create_task_request = CreateDelegationTaskRequest(
                parent_agent_id=self.state.agent_id,
                parent_task_id=self.state.task_id,
                target_agent_id=agent_id,
                target_agent_name=agent_name,
                message=message,
                user_id=self.state.user_id,
                workspace_id=self.state.workspace_id,
                parent_effective_policy=self.state.effective_policy,
                run_budget_usd=run_budget_usd,
            )
            create_task_result: CreateDelegationTaskResult = await workflow.execute_activity(
                Activities.CREATE_DELEGATION_TASK,
                args=[create_task_request],
                result_type=CreateDelegationTaskResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )

            if create_task_result.status != "created" or not create_task_result.task_id:
                raise ApplicationError(
                    f"Failed to create delegation task: {create_task_result.error}"
                )
            if create_task_result.effective_policy is None:
                raise ApplicationError(
                    "delegation task was created without an effective-policy snapshot",
                    type="InvalidExecutionSnapshot",
                    non_retryable=True,
                )

            child_task_id = create_task_result.task_id
            child_task_created = True

            # Build child workflow request with its own task_id
            child_request = AgentExecutionRequest(
                task_id=child_task_id,
                agent_id=UUID(agent_id),
                user_id=self.state.user_id,
                workspace_id=self.state.workspace_id,
                task_query=message,
                workflow_metadata={
                    "source": "agent_delegation",
                    "parent_execution_id": self.state.execution_id,
                    "parent_agent_id": self.state.agent_id,
                    "parent_task_id": self.state.task_id,
                },
                effective_policy=create_task_result.effective_policy,
            )

            # Start child workflow and await result
            # - execution_timeout: caps total child runtime
            # - parent_close_policy: TERMINATE ensures child is cancelled
            #   if the parent workflow is cancelled or completed
            child_workflow_id = f"delegation-{self.state.execution_id}-{tool_call.id}"
            child_result: AgentExecutionResult = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                args=[child_request],
                id=child_workflow_id,
                task_queue=(
                    workflow.info().task_queue
                    if workflow.patched(DELEGATION_ON_OWN_QUEUE_PATCH)
                    else LEGACY_DELEGATION_TASK_QUEUE
                ),
                execution_timeout=DELEGATION_TIMEOUT,
                parent_close_policy=ParentClosePolicy.TERMINATE,
            )

            # Build a structured envelope for the parent's LLM. Same shape
            # for success and failure so the parent can branch on `status`.
            # `final_response` is the child's own narrative; `task_id` lets
            # the parent call get_task_summary later for the full record.
            if child_result.success:
                envelope: dict[str, Any] = {
                    "status": "completed",
                    "agent": agent_name,
                    "task_id": str(child_task_id),
                    "final_response": child_result.final_response
                    or "(Agent completed without response)",
                    "iterations": child_result.reasoning_iterations_used,
                    "cost_usd": float(child_result.total_cost),
                }
            else:
                envelope = {
                    "status": "failed",
                    "agent": agent_name,
                    "task_id": str(child_task_id),
                    "error": child_result.error_message or "(Agent failed without details)",
                    "iterations": child_result.reasoning_iterations_used,
                    "cost_usd": float(child_result.total_cost),
                }

            self.state.messages.append(
                Message(
                    role="tool",
                    content=json.dumps(envelope),
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self._events.add_event(
                EventTypes.AGENT_DELEGATION_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_id": agent_id,
                    "target_agent_name": agent_name,
                    "child_task_id": str(child_task_id),
                    "success": child_result.success,
                    "iteration": self.state.current_iteration,
                    "child_iterations": child_result.reasoning_iterations_used,
                    "child_cost": float(child_result.total_cost),
                },
            )
            await self._publish_events_immediately()

            # Account for child's cost in parent budget
            if child_result.total_cost > 0:
                self._delegated_cost += child_result.total_cost
                self._budget.add_cost(child_result.total_cost)
            child_cost_accounted = True

            workflow.logger.info(
                f"Agent delegation to '{agent_name}' completed "
                f"(success={child_result.success}, cost=${child_result.total_cost:.4f})"
            )

        except Exception as e:
            if child_task_created and not child_cost_accounted:
                # A failed child does not return AgentExecutionResult, so the
                # parent cannot recover its exact spend from Temporal. Consume
                # the full allocation as a fail-closed reservation; the child
                # task still persists its exact own_cost for billing.
                self._delegated_cost += run_budget_usd
                self._budget.add_cost(run_budget_usd)
            # Surface the failure to the parent's LLM as a tool message and
            # continue. Re-raising here would propagate out of asyncio.gather
            # and abort sibling delegations — wrong semantics for fan-out
            # where each child's success/failure should be independent.
            workflow.logger.error(f"Agent delegation to '{agent_name}' failed: {e}", exc_info=True)

            error_payload = {
                "status": "failed",
                "agent": agent_name,
                "error": str(e),
            }
            self.state.messages.append(
                Message(
                    role="tool",
                    content=json.dumps(error_payload),
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self._events.add_event(
                EventTypes.AGENT_DELEGATION_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_id": agent_id,
                    "target_agent_name": agent_name,
                    "error": str(e),
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()
