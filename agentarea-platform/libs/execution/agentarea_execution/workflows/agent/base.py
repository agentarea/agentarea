"""State, lifecycle flags and event publishing shared by every part of the agent workflow."""

import json
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from agentarea_agents_sdk.skills import SkillActivationTool
    from agentarea_agents_sdk.tools.disclosure import ToolDisclosurePolicy
    from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
    from agentarea_common.auth.tool_authorization import tool_matches_any
    from agentarea_common.money import ZERO, Money

    from ..context_manager import ContextWindowManager
    from ..helpers import SEEN_URLS_LIMIT, BudgetTracker, EventManager, external_urls
    from ..models import AgentExecutionState, Message, PendingEscalation

from ...models import (
    ConversationWindow,
    LogRow,
    RecordRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    EVENT_PUBLISH_TIMEOUT,
    EVENT_PUBLISH_WINDOW,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import bookkeeping_retry_policy, make_retry_policy
from .patches import CANCELLATION_PROPAGATES_PATCH, TASK_LOG_RECORD_PATCH

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
        # The model-call failure _call_llm already reported as llm.call.failed.
        self._reported_llm_failure: BaseException | None = None
        self._waiting_for_continuation = False
        self._continuation_failure_reason: str | None = None
        self._continuation_message: str | None = None
        self._continuation_count = 0
        self._delegated_cost: Money = ZERO
        self._monthly_cap_message: str | None = None
        # The agent's month-to-date spend at the last cap check, and this run's
        # own spend at that moment; None while the run's agent has no cap.
        self._agent_spend_baseline: Money | None = None
        self._agent_spend_mark: Money = ZERO
        self._agent_cap_counts_service = False
        self._agent_cap_currency: str | None = None
        # A resumed run whose log predates the logged system prompt writes one first.
        self._resume_system_prompt_missing = False
        # Old histories retain their recorded command sequence.
        self._interaction_contract_enabled = True
        self._wait_tool_enabled = False
        # Tool and model calls still running when the run was stopped, settled after it.
        self._stopped_tool_calls: list[Any] = []
        self._stopped_model_call: Any = None
        # Tool call ids of the model's latest turn, which may already be in the log.
        self._turn_call_ids: set[str] = set()
        # On the task log: the latest recorded model turn's tool calls and the ids
        # a recorded result answers, since the recorded rows leave state.messages.
        self._recorded_turn_calls: list[Any] = []
        self._recorded_turn_answered: set[str] = set()

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

    def _last_turn_tool_calls(self) -> tuple[list[Any], set[str]]:
        """The last model turn's tool calls, and the ids a result already answers.

        On the task log that turn and its results may be recorded already.
        """
        last_assistant = next(
            (
                index
                for index in range(len(self.state.messages) - 1, -1, -1)
                if self.state.messages[index].role == "assistant"
            ),
            None,
        )
        if last_assistant is not None:
            calls = list(self.state.messages[last_assistant].tool_calls or [])
            answered: set[str] = set()
            after = self.state.messages[last_assistant + 1 :]
        elif self._task_log_on():
            calls = list(self._recorded_turn_calls)
            answered = set(self._recorded_turn_answered)
            after = self.state.messages
        else:
            return [], set()
        answered |= {m.tool_call_id for m in after if m.role == "tool" and m.tool_call_id}
        return calls, answered

    def _answer_unanswered_tool_calls(self, content: str) -> None:
        """Give every tool call of the last model turn a result.

        A turn that stops before its tool calls ran would otherwise leave the
        conversation with calls no result answers, and providers reject that on
        the next model call.
        """
        calls, answered = self._last_turn_tool_calls()
        for tool_call in calls:
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if call_id and call_id not in answered:
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=content,
                        tool_call_id=call_id,
                        name=(tool_call.get("function") or {}).get("name"),
                    )
                )

    def _task_log_on(self) -> bool:
        """Whether this run writes its task log through the record activity."""
        return workflow.patched(TASK_LOG_RECORD_PATCH)

    def _call_in_history(self, call_id: str) -> bool:
        """Whether a tool call of this id is in the conversation, written or pending."""
        return call_id in self._turn_call_ids or any(
            call.get("id") == call_id
            for message in self.state.messages
            for call in (message.tool_calls or [])
            if isinstance(call, dict)
        )

    def _log_event(self, event_type: str, meta: dict[str, Any]) -> None:
        """Add an event row to the task log, recorded with the next pending rows."""
        self.state.messages.append(
            Message(role="event", content="", kind="event", name=event_type, meta=meta)
        )

    def _has_stopped_work(self) -> bool:
        """Whether a stop interrupted a call whose outcome the run has yet to record."""
        return bool(self._stopped_tool_calls) or self._stopped_model_call is not None

    def _add_execution_finished_event(self, execution_cancelled: bool) -> None:
        self._events.add_event(
            EventTypes.EXECUTION_FINISHED,
            {
                "status": self.state.status,
                "execution_status": "cancelled" if execution_cancelled else "completed",
                "success": self.state.success,
                "final_response": self.state.final_response,
                "failure_reason": self.state.failure_reason,
                "blocked": self.state.status == ExecutionStatus.BLOCKED,
                "blocked_reason": self.state.blocked_reason,
            },
        )

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
            for key in ("tool_call_id", "name", "tool_calls", "attachments", "meta"):
                value = getattr(msg, key)
                if value is not None:
                    message[key] = value
            if msg.kind != "message":
                message["kind"] = msg.kind
            payload.append(message)
        return payload

    def _conversation_window(self) -> ConversationWindow:
        if self._task_log_on():
            return ConversationWindow(
                task_id=self.state.task_id, next_seq=self.state.conversation_next_seq
            )
        return ConversationWindow(
            task_id=self.state.task_id,
            head_seqs=list(self.state.context_head_seqs),
            tail_start=self.state.context_tail_start,
            next_seq=self.state.conversation_next_seq,
        )

    def _remember_external_urls(self) -> None:
        """Keep the links the pending entries brought in from outside the model.

        The pending entries are the workflow's only copy of the conversation
        until they reach the log; the web fetch gate needs their links after.
        """
        known = set(self.state.seen_urls)
        for url in external_urls(self.state.messages):
            if url not in known:
                known.add(url)
                self.state.seen_urls.append(url)
        del self.state.seen_urls[:-SEEN_URLS_LIMIT]

    def _mark_conversation_written(self) -> None:
        """Record that an activity wrote the pending entries to the log.

        A run on the task log writes them only through ``_record``.
        """
        if self._task_log_on():
            return
        self._remember_external_urls()
        self.state.conversation_next_seq += len(self.state.messages)
        self.state.messages = []

    def _apply_conversation_window(self, window: ConversationWindow) -> None:
        """Adopt the window an activity left the log in; nothing is pending after it."""
        if window.head_seqs is None or window.tail_start is None:
            raise ApplicationError(
                "a cursor window carries no head or tail",
                type="InvalidCompactionResult",
                non_retryable=True,
            )
        self._remember_external_urls()
        self.state.messages = []
        self.state.context_head_seqs = list(window.head_seqs)
        self.state.context_tail_start = window.tail_start
        self.state.conversation_next_seq = window.next_seq

    async def _record(self, status: UpdateTaskStatusRequest | None = None) -> None:
        """Write the pending log rows and the task's status, then publish the pending events.

        One record activity does all of it, in one transaction for the rows and
        the status; a store outage holds the run here, retrying. Every row and
        event carries an id the workflow assigned, so a retry writes nothing twice.
        """
        # A run refused before its event manager exists still records its status.
        events = self.event_manager
        pending_events = events.get_pending_events() if events else []
        messages = list(self.state.messages)
        if not pending_events and not messages and status is None:
            return
        if events:
            events.clear_pending_events()
        first_seq = self.state.conversation_next_seq
        rows = [
            LogRow(
                seq=first_seq + offset,
                event_id=str(workflow.uuid4()),
                kind=message.kind,
                role=message.role,
                content=message.content,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
                name=message.name,
                attachments=message.attachments,
                meta=message.meta,
                iteration=self.state.current_iteration,
            )
            for offset, message in enumerate(messages)
        ]
        await workflow.execute_activity(
            Activities.RECORD,
            args=[
                RecordRequest(
                    task_id=self.state.task_id,
                    workspace_id=self.state.workspace_id,
                    user_id=self.state.user_id,
                    execution_id=self.state.execution_id,
                    rows=rows,
                    events_json=[json.dumps(event) for event in pending_events],
                    status=status,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=EVENT_PUBLISH_WINDOW,
            retry_policy=make_retry_policy(0, maximum_interval=EVENT_PUBLISH_TIMEOUT),
        )
        for message in messages:
            if message.role == "assistant":
                self._recorded_turn_calls = list(message.tool_calls or [])
                self._recorded_turn_answered = set()
            elif message.role == "tool" and message.tool_call_id:
                self._recorded_turn_answered.add(message.tool_call_id)
        # A signal handled during the call may have added rows after these.
        self._remember_external_urls()
        del self.state.messages[: len(messages)]
        self.state.conversation_next_seq = first_seq + len(messages)

    async def _persist_task_status(self, request: UpdateTaskStatusRequest) -> None:
        """Store the task's status: with the pending log rows on the task log, else alone."""
        if self._task_log_on():
            await self._record(
                status=request.model_copy(update={"conversation": None, "conversation_pending": []})
            )
            return
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=bookkeeping_retry_policy(),
        )

    async def _publish_events_immediately(self) -> None:
        """Persist the pending events before the run moves on.
        The events are the task's durable record, so a store outage holds the run
        here, retrying, rather than failing it or dropping the events. The
        activity writes idempotently by event id, which makes a retry that
        follows a write it never heard back from harmless. On the task log the
        pending rows are recorded with them.
        """
        if self._task_log_on():
            await self._record()
            return
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
