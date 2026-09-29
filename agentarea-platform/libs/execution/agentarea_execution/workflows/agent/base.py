"""State, lifecycle flags and event publishing shared by every part of the agent workflow."""

import json
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from agentarea_agents_sdk.skills import SkillActivationTool
    from agentarea_agents_sdk.tools.disclosure import ToolDisclosurePolicy
    from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
    from agentarea_common.auth.tool_authorization import tool_matches_any
    from agentarea_common.money import ZERO, Money

    from ..context_manager import ContextWindowManager
    from ..helpers import BudgetTracker, EventManager
    from ..models import AgentExecutionState, PendingEscalation

from ...models import WorkflowEventsRequest
from ..constants import EVENT_PUBLISH_TIMEOUT, Activities
from ..retry import make_retry_policy

JsonDict = dict[str, Any]

AgentToolRegistry = dict[str, JsonDict]


class AgentWorkflowBase:
    """State, lifecycle flags and event publishing shared by every part of the agent workflow."""

    def __init__(self) -> None:
        self.state = AgentExecutionState()
        self.event_manager: EventManager | None = None
        self.budget_tracker: BudgetTracker | None = None
        self.context_manager: ContextWindowManager | None = None
        self._paused = False
        self._pause_reason = ""
        self._awaiting_input = False
        # Metadata passed in at workflow start (set in _initialize_workflow).
        # Used to detect e.g. agent_delegation children that must terminate
        # immediately on completion rather than entering await_input.
        self._workflow_metadata: dict[str, Any] = {}
        # Maps sanitized agent tool names to their config (type=agent entries)
        self._agent_tool_registry: AgentToolRegistry = {}
        # A2UI action queue — frontend signals land here, workflow loop drains them
        self._a2ui_action_queue: list[dict[str, Any]] = []
        self._skill_tool: SkillActivationTool | None = None
        self._tool_catalog: ToolCatalog | None = None
        # OpenAPI disclosure: NamedLookupPolicy when pool is non-empty, else None.
        # Stateless wrt the policy itself — pool lives in state.searchable_tool_pool.
        self._disclosure_policy: ToolDisclosurePolicy | None = None
        self._pending_escalations: dict[str, PendingEscalation] = {}
        self._pending_input_requests: dict[str, dict[str, Any]] = {}
        # Generic message queue — queued user messages drained before each LLM call
        self._message_queue: list[dict[str, Any]] = []
        # Track if completion event has been published (to avoid double-publish at termination)
        self._completion_event_published = False
        self._waiting_for_continuation = False
        self._continuation_failure_reason: str | None = None
        self._continuation_message: str | None = None
        self._continuation_count = 0
        self._delegated_cost: Money = ZERO
        self._monthly_cap_message: str | None = None
        # Old histories retain their recorded command sequence.
        self._interaction_contract_enabled = True

    @property
    def _questions_available(self) -> bool:
        if not self._interaction_contract_enabled:
            return True
        denied = ((self.state.effective_policy or {}).get("tools") or {}).get("denied") or []
        return self.state.interaction_capabilities.allow_questions and not tool_matches_any(
            "request_user_input", denied
        )

    @property
    def _a2ui_available(self) -> bool:
        return bool(self.state.agent_config.get("a2ui_enabled", False)) and (
            not self._interaction_contract_enabled or self.state.interaction_capabilities.allow_a2ui
        )

    @property
    def _events(self) -> EventManager:
        if self.event_manager is None:
            raise RuntimeError("Workflow event manager is not initialized")
        return self.event_manager

    def _is_delegation_child(self) -> bool:
        """True iff this workflow was spawned via parent's delegation tool.

        Identified by ``workflow_metadata.source == "agent_delegation"`` set
        in ``_execute_agent_delegation``. Such children have no end-user
        owning their conversation, so they must not enter await_input.
        """
        return (self._workflow_metadata or {}).get("source") == "agent_delegation"

    async def _publish_events_immediately(self) -> None:
        """Publish events immediately as they occur - fire and forget using Pydantic models."""
        pending_events = self._events.get_pending_events()

        # Only proceed if we have events to publish
        if not pending_events:
            return

        # Clear pending events immediately since we're not waiting for confirmation
        self._events.clear_pending_events()

        events_json = [json.dumps(event) for event in pending_events]

        # Fire and forget - publish async without waiting for result
        workflow.logger.debug(f"Publishing {len(events_json)} events immediately")

        # Create Pydantic request model for event publishing
        events_request = WorkflowEventsRequest(
            events_json=events_json,
            workspace_id=self.state.workspace_id,
            user_id=self.state.user_id,
        )

        # Start the activity but don't await it (fire and forget)
        await workflow.execute_activity(
            Activities.PUBLISH_WORKFLOW_EVENTS,
            args=[events_request],
            start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
            retry_policy=make_retry_policy(1),  # Single attempt only
        )
