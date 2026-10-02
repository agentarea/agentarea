"""State, lifecycle flags and event publishing shared by every part of the agent workflow."""

import json
from typing import Any

from temporalio import workflow
from temporalio.exceptions import is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from agentarea_agents_sdk.skills import SkillActivationTool
    from agentarea_agents_sdk.tools.disclosure import ToolDisclosurePolicy
    from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
    from agentarea_common.auth.tool_authorization import tool_matches_any
    from agentarea_common.money import ZERO, Money

    from ..context_manager import ContextWindowManager
    from ..helpers import BudgetTracker, EventManager
    from ..models import AgentExecutionState, PendingEscalation

from ...models import ConversationWindow, WorkflowEventsRequest
from ..constants import EVENT_PUBLISH_TIMEOUT, EVENT_PUBLISH_WINDOW, Activities
from ..retry import make_retry_policy
from .patches import CANCELLATION_PROPAGATES_PATCH

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
        self._wait_tool_enabled = False

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

    @staticmethod
    def _is_cancellation(error: BaseException) -> bool:
        """Whether an error means the run itself is being cancelled.

        Cancelling a run cancels whatever activity or child it awaits, and that
        surfaces as the awaited operation's error. Handlers that turn operation
        errors into messages for the model must re-raise it, or the run keeps
        going after the user cancelled it.
        """
        return is_cancelled_exception(error) and workflow.patched(CANCELLATION_PROPAGATES_PATCH)

    def _is_delegation_child(self) -> bool:
        """True iff this workflow was spawned via parent's delegation tool.

        Identified by ``workflow_metadata.source == "agent_delegation"`` set
        in ``_execute_agent_delegation``. Such children have no end-user
        owning their conversation, so they must not enter await_input.
        """
        return (self._workflow_metadata or {}).get("source") == "agent_delegation"

    def _conversation_payload(self) -> list[dict[str, Any]]:
        """The entries not yet in the conversation log, as chat messages."""
        payload: list[dict[str, Any]] = []
        for msg in self.state.messages:
            message: dict[str, Any] = {"role": msg.role, "content": msg.content}
            for key in ("tool_call_id", "name", "tool_calls"):
                value = getattr(msg, key)
                if value is not None:
                    message[key] = value
            payload.append(message)
        return payload

    def _conversation_window(self) -> ConversationWindow:
        return ConversationWindow(
            task_id=self.state.task_id,
            head_seqs=list(self.state.context_head_seqs),
            tail_start=self.state.context_tail_start,
            next_seq=self.state.conversation_next_seq,
        )

    def _mark_conversation_written(self) -> None:
        """Record that an activity wrote the pending entries to the log."""
        self.state.conversation_next_seq += len(self.state.messages)
        self.state.messages = []

    def _apply_conversation_window(self, window: ConversationWindow) -> None:
        """Adopt the window an activity left the log in; nothing is pending after it."""
        self.state.messages = []
        self.state.context_head_seqs = list(window.head_seqs)
        self.state.context_tail_start = window.tail_start
        self.state.conversation_next_seq = window.next_seq

    async def _publish_events_immediately(self) -> None:
        """Persist the pending events before the run moves on.
        The events are the task's durable record, so a store outage holds the run
        here, retrying, rather than failing it or dropping the events. The
        activity writes idempotently by event id, which makes a retry that
        follows a write it never heard back from harmless.
        """
        pending_events = self._events.get_pending_events()
        if not pending_events:
            return

        self._events.clear_pending_events()
        events_request = WorkflowEventsRequest(
            events_json=[json.dumps(event) for event in pending_events],
            workspace_id=self.state.workspace_id,
            user_id=self.state.user_id,
        )
        await workflow.execute_activity(
            Activities.PUBLISH_WORKFLOW_EVENTS,
            args=[events_request],
            start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
            schedule_to_close_timeout=EVENT_PUBLISH_WINDOW,
            retry_policy=make_retry_policy(0, maximum_interval=EVENT_PUBLISH_TIMEOUT),
        )
