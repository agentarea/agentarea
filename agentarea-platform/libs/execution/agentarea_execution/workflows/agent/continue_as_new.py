"""Carrying the run's state across continue-as-new."""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry
    from agentarea_agents_sdk.tools.disclosure import NamedLookupPolicy
    from agentarea_common.money import serialize_money

    from ...interaction import resolve_interaction_capabilities
    from ..context_manager import ContextWindowManager
    from ..helpers import BudgetTracker, EventManager, MessageBuilder
    from ..models import ContinueAsNewState, Message

from ...models import AgentExecutionRequest
from ..constants import EventTypes
from .compaction import CompactionMixin


class ContinueAsNewMixin(CompactionMixin):
    """Carrying the run's state across continue-as-new."""

    async def _restore_from_continued_state(self, continued_state: dict) -> None:
        """Restore workflow state from a continue-as-new restart."""
        workflow.logger.info("Restoring workflow from continue-as-new state")

        state = ContinueAsNewState(**continued_state)

        self.state.execution_id = state.execution_id
        self.state.agent_id = state.agent_id
        self.state.task_id = state.task_id
        self.state.user_id = state.user_id
        self.state.workspace_id = state.workspace_id
        self.state.goal = state.goal
        self.state.agent_config = state.agent_config
        self.state.available_tools = state.available_tools
        self.state.current_iteration = state.current_iteration
        self.state.tool_calls_used = state.tool_calls_used
        self.state.budget_usd = state.budget_usd
        self.state.tokens_used = state.tokens_used
        self.state.context_window = state.context_window
        self.state.user_context_data = state.user_context_data
        self.state.activated_skills = state.activated_skills
        self.state.context_strategy = state.context_strategy
        self.state.history_chunk_counter = state.history_chunk_counter
        self.state.activated_tool_sources = state.activated_tool_sources
        self.state.searchable_tool_pool = state.searchable_tool_pool
        self.state.revealed_openapi_tools = state.revealed_openapi_tools
        self.state.mcp_tool_routes = state.mcp_tool_routes
        # Re-instantiate disclosure policy stateless from pool presence so
        # post-replay tool dispatch can route load_tools and rebuild the
        # catalog block on subsequent iterations.
        if self.state.searchable_tool_pool:
            self._disclosure_policy = NamedLookupPolicy()
            # Reconcile previously revealed names against the restored pool.
            # If a connection's `available_tools` shrunk between runs, drop the
            # stale schema from `available_tools`, drop the name from the
            # revealed list, and warn — otherwise the LLM would see a tool it
            # can no longer execute.
            pool_names = {c["name"] for c in self.state.searchable_tool_pool}
            stale = [name for name in self.state.revealed_openapi_tools if name not in pool_names]
            if stale:
                workflow.logger.warning(
                    "Dropping %d stale revealed OpenAPI tool(s) on continue-as-new: %s",
                    len(stale),
                    stale,
                )
                stale_set = set(stale)
                self.state.revealed_openapi_tools = [
                    n for n in self.state.revealed_openapi_tools if n not in stale_set
                ]
                self.state.available_tools = [
                    t
                    for t in self.state.available_tools
                    if (t.get("function", {}) or {}).get("name") not in stale_set
                ]
        self.state.service_budget_usd = state.service_budget_usd
        self.state.service_cost_used = state.service_cost_used
        self.state.wallet_id = state.wallet_id
        self.state.resolved_model = state.resolved_model
        self.state.effective_policy = state.effective_policy
        self._message_queue = list(state.message_queue)
        self._pending_escalations = dict(state.pending_escalations)
        self._pending_input_requests = dict(state.pending_input_requests)
        self._a2ui_action_queue = list(state.a2ui_action_queue)
        self._awaiting_input = state.awaiting_input
        self._paused = state.paused
        self._pause_reason = state.pause_reason
        self._workflow_metadata = dict(state.workflow_metadata)
        if state.interaction_contract_enabled is not None:
            self._interaction_contract_enabled = state.interaction_contract_enabled
        self.state.interaction_capabilities = (
            state.interaction_capabilities
            or resolve_interaction_capabilities(
                state.goal.context,
                state.workflow_metadata,
                bool(state.agent_config.get("a2ui_enabled", False)),
            )
        )
        self.state.a2ui_surfaces = state.a2ui_surfaces
        self._completion_event_published = state.completion_event_published
        self._waiting_for_continuation = state.waiting_for_continuation
        self._continuation_failure_reason = state.continuation_failure_reason
        self._continuation_message = state.continuation_message
        self._continuation_count = state.continuation_count
        self._delegated_cost = state.delegated_cost
        self.state.status = state.status
        self.state.success = state.success
        self.state.final_response = state.final_response
        self.state.failure_reason = state.failure_reason
        self.state.error_message = state.error_message
        self.state.blocked_reason = state.blocked_reason
        self.state.validation_state = state.validation_state
        self.state.validation_repair_attempts = state.validation_repair_attempts
        self.state.validation_terminal = state.validation_terminal

        # Restore messages from compacted dicts
        self.state.messages = [Message(**msg) for msg in state.messages]

        # Restore agent tool registry for delegation routing
        self._agent_tool_registry = state.agent_tool_registry

        # Restore skill activation tool from agent_config
        skills = self.state.agent_config.get("skills", [])
        if skills:
            skill_entries = [
                SkillEntry(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    content=s.get("content", ""),
                    files=s.get("files", []),
                )
                for s in skills
            ]
            registry = SkillCatalogBuilder.build_registry(skill_entries)
            self._skill_tool = SkillActivationTool(registry)
            # Mark already-activated skills from state
            for name in self.state.activated_skills:
                if name in self._skill_tool._skills_registry:
                    self._skill_tool._activated.add(name)

        # Initialize helpers with restored cost
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
            workspace_id=self.state.workspace_id,
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)
        self.budget_tracker.add_cost(state.total_cost)
        if self.state.context_window is None:
            raise ApplicationError(
                "continued execution state has no ModelSpec context_window",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        self.context_manager = ContextWindowManager(self.state.context_window)

        workflow.logger.info(
            f"Restored from run {state.continued_from_run_id}, "
            f"iteration {state.current_iteration}, "
            f"cost ${state.total_cost:.4f}, "
            f"{len(self.state.messages)} messages, "
            f"{len(self._agent_tool_registry)} agent tools"
        )

    async def _continue_as_new(self) -> None:
        """Compact messages and continue workflow with fresh event history."""
        workflow.logger.info(
            f"Continue-as-new triggered at iteration {self.state.current_iteration}, "
            f"event history suggests reset"
        )

        # Compact messages before carrying state forward
        await self._compact_context_if_needed()

        # Serialize messages to dicts
        messages_dict = [
            MessageBuilder.normalize_message_dict(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                    "tool_calls": msg.tool_calls,
                }
            )
            for msg in self.state.messages
        ]

        if self.state.goal is None:
            raise ApplicationError(
                "workflow goal is missing from execution state",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )

        continued_state = ContinueAsNewState(
            execution_id=self.state.execution_id,
            agent_id=self.state.agent_id,
            task_id=self.state.task_id,
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            goal=self.state.goal,
            messages=messages_dict,
            agent_config=self.state.agent_config,
            available_tools=self.state.available_tools,
            current_iteration=self.state.current_iteration,
            tool_calls_used=self.state.tool_calls_used,
            total_cost=self._budget.cost,
            delegated_cost=self._delegated_cost,
            tokens_used=self.state.tokens_used,
            budget_usd=self.state.budget_usd,
            context_window=self.state.context_window,
            user_context_data=self.state.user_context_data,
            continued_from_run_id=workflow.info().run_id,
            agent_tool_registry=self._agent_tool_registry,
            activated_skills=self.state.activated_skills,
            context_strategy=self.state.context_strategy,
            history_chunk_counter=self.state.history_chunk_counter,
            activated_tool_sources=self.state.activated_tool_sources,
            searchable_tool_pool=self.state.searchable_tool_pool,
            revealed_openapi_tools=self.state.revealed_openapi_tools,
            mcp_tool_routes=self.state.mcp_tool_routes,
            service_budget_usd=self.state.service_budget_usd,
            service_cost_used=self.state.service_cost_used,
            wallet_id=self.state.wallet_id,
            resolved_model=self.state.resolved_model,
            effective_policy=self.state.effective_policy,
            message_queue=self._message_queue,
            pending_escalations=self._pending_escalations,
            pending_input_requests=self._pending_input_requests,
            a2ui_action_queue=self._a2ui_action_queue,
            interaction_contract_enabled=self._interaction_contract_enabled,
            interaction_capabilities=self.state.interaction_capabilities,
            a2ui_surfaces=self.state.a2ui_surfaces,
            awaiting_input=self._awaiting_input,
            paused=self._paused,
            pause_reason=self._pause_reason,
            workflow_metadata=self._workflow_metadata,
            completion_event_published=self._completion_event_published,
            waiting_for_continuation=self._waiting_for_continuation,
            continuation_failure_reason=self._continuation_failure_reason,
            continuation_message=self._continuation_message,
            continuation_count=self._continuation_count,
            status=self.state.status,
            success=self.state.success,
            final_response=self.state.final_response,
            failure_reason=self.state.failure_reason,
            error_message=self.state.error_message,
            blocked_reason=self.state.blocked_reason,
            validation_state=self.state.validation_state,
            validation_repair_attempts=self.state.validation_repair_attempts,
            validation_terminal=self.state.validation_terminal,
        )

        # Publish event before continuing (persisted in DB via tier 2)
        self._events.add_event(
            EventTypes.WORKFLOW_CONTINUED_AS_NEW,
            {
                "iteration": self.state.current_iteration,
                "total_cost": serialize_money(self._budget.cost),
                "messages_carried": len(self.state.messages),
                "continued_from_run_id": workflow.info().run_id,
                "reason": "Temporal event history size limit approaching",
            },
        )
        await self._publish_events_immediately()

        # Build new request with continued state
        new_request = AgentExecutionRequest(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            task_query=self.state.goal.description,
            budget_usd=self.state.budget_usd,
            effective_policy=self.state.effective_policy,
            continued_state=continued_state.model_dump(),
        )

        workflow.continue_as_new(args=[new_request])
