"""Compacting the conversation when it approaches the context window."""

import asyncio

from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ActivityCancellationType

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import serialize_money

    from ..context_manager import COMPACTION_SUMMARY_HEADER
    from ..context_strategy import ContextStrategy, allows_history_preservation
    from ..models import Message

from ...models import CompactMessagesRequest, CompactMessagesResult
from ..constants import (
    CONTEXT_MIN_COMPACTION_GAIN,
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    Activities,
    EventTypes,
)
from ..retry import model_call_retry_policy
from .budget import BudgetMixin
from .patches import (
    COMPACTION_BOUNDS_PAYLOAD_PATCH,
    COMPACTION_NEEDS_ROOM_PATCH,
    PAID_CALL_PERSISTED_BEFORE_LIMITS_PATCH,
    STOP_SETTLES_COMPACTION_PATCH,
)
from .stopping import StoppedModelCall


class CompactionMixin(BudgetMixin):
    """Compacting the conversation when it approaches the context window."""

    async def _run_compaction_activity(
        self, request: CompactMessagesRequest
    ) -> CompactMessagesResult:
        """Summarize; a stop of the run stops waiting at once and keeps the paid call.

        The run records what the summary call cost once it settles, after the stop.
        """
        if not workflow.patched(STOP_SETTLES_COMPACTION_PATCH):
            return await workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[request],
                result_type=CompactMessagesResult,
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=model_call_retry_policy(),
            )
        handle = asyncio.ensure_future(
            workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[request],
                result_type=CompactMessagesResult,
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=model_call_retry_policy(),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        )
        try:
            return await asyncio.shield(handle)
        except asyncio.CancelledError:
            handle.cancel()
            self._stopped_model_call = StoppedModelCall(
                self.state.current_iteration, handle, purpose="compaction"
            )
            raise

    def _note_prompt_tokens(self, prompt_tokens: int) -> None:
        """Keep the first measured prompt after a compaction: what the context cannot go below."""
        if self._awaiting_compaction_floor:
            self._compaction_floor_tokens = prompt_tokens
            self._awaiting_compaction_floor = False

    async def _compact_context_if_needed(self, *, force: bool = False) -> bool:
        """Summarize the logged conversation when context or a payload bound is reached.

        The conversation lives in the task's log, so the activity does the work:
        it writes the pending entries, keeps the most recent ones and activated
        skill content verbatim, summarizes the rest and returns the new window.

        ``force`` is reserved for the versioned payload-size guard.

        Returns True if compaction was performed.
        """
        if not self.context_manager:
            return False
        if not force and not self.context_manager.needs_compaction():
            return False
        if (
            not force
            and self._compaction_floor_tokens is not None
            and workflow.patched(COMPACTION_NEEDS_ROOM_PATCH)
        ):
            gain = self.context_manager.current_tokens - self._compaction_floor_tokens
            if gain < CONTEXT_MIN_COMPACTION_GAIN * self.context_manager.effective_limit:
                workflow.logger.warning(
                    f"Skipping compaction: the prompt grew {gain} tokens since the last one "
                    f"({self._compaction_floor_tokens} tokens right after it)"
                )
                return False
        bounds_payload = workflow.patched(COMPACTION_BOUNDS_PAYLOAD_PATCH)
        if force and not bounds_payload:
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )
        strategy = ContextStrategy(self.state.context_strategy)
        result = await self._run_compaction_activity(
            CompactMessagesRequest(
                conversation=self._conversation_window(),
                pending=self._conversation_payload(),
                history_chunk_index=self.state.history_chunk_counter
                if allows_history_preservation(strategy)
                else None,
                model_id=str(self.state.agent_config.get("model_id") or ""),
                workspace_id=self.state.workspace_id,
                user_context_data=self.state.user_context_data,
                resolved_model=self.state.resolved_model,
                effective_policy=self.state.effective_policy,
            )
        )
        from_log = self._task_log_on()
        if not from_log:
            if result.conversation is None:
                raise ApplicationError(
                    "compaction of a cursor window returned no window",
                    type="InvalidCompactionResult",
                    non_retryable=True,
                )
            self._apply_conversation_window(result.conversation)
        if result.original_message_count == 0:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False
        if from_log:
            # Recorded with the pending rows below, after everything it summarizes.
            self.state.messages.append(
                Message(
                    role="user",
                    kind="compaction",
                    content=f"{COMPACTION_SUMMARY_HEADER}\n{result.summary}",
                    meta={"skills": result.skills} if result.skills else None,
                )
            )

        if result.cost is None or result.usage is None:
            raise ApplicationError(
                "compaction result has no usage accounting",
                type="LLMAccountingUnavailable",
                non_retryable=True,
            )
        billed_first = workflow.patched(PAID_CALL_PERSISTED_BEFORE_LIMITS_PATCH)
        if billed_first:
            self._account_inference_usage(
                cost=result.cost,
                total_tokens=result.usage.total_tokens,
                source="Context compaction",
            )
        else:
            self._record_inference_usage(
                cost=result.cost,
                total_tokens=result.usage.total_tokens,
                source="Context compaction",
            )
        if result.history_chunk_stored:
            self.state.history_chunk_counter += 1
        self.state.last_prompt_tokens = result.context_tokens
        self.context_manager.update_usage(result.context_tokens)
        self.context_manager.mark_compacted()
        self._compaction_floor_tokens = None
        self._awaiting_compaction_floor = True

        # The summary is a paid model call. It is persisted as llm.call.completed,
        # the one event every spend consumer (usage metering, task summaries)
        # reads; purpose keeps it out of the transcript's assistant turn. Same
        # publish batch as context.compacted, so no new workflow command.
        self._events.add_event(
            EventTypes.LLM_CALL_COMPLETED,
            {
                "iteration": self.state.current_iteration,
                "purpose": "compaction",
                "model_id": self.state.agent_config.get("model_id"),
                "model_name": (self.state.resolved_model or {}).get("model_name"),
                "managed_by": (self.state.resolved_model or {}).get("managed_by"),
                "cost": serialize_money(result.cost),
                # CompactMessagesResult carries no pre-conversion provider cost.
                "provider_cost_usd": None,
                "total_cost": serialize_money(self._budget.cost),
                "usage": {
                    "cost": serialize_money(result.cost),
                    "usage": result.usage.model_dump(),
                },
                "content": "",
                "thinking": "",
                "tool_calls": [],
                "role": "assistant",
            },
        )
        self._events.add_event(
            EventTypes.CONTEXT_COMPACTED,
            {
                "iteration": self.state.current_iteration,
                "messages_compacted": result.original_message_count,
                "tokens_saved": result.estimated_tokens_saved,
                "compaction_number": self.context_manager.compaction_count,
                "context_tokens": result.context_tokens,
            },
        )
        await self._publish_events_immediately()
        if billed_first:
            self._enforce_inference_limits("Context compaction")

        workflow.logger.info(
            f"Compacted {result.original_message_count} messages, "
            f"~{result.estimated_tokens_saved} tokens saved"
        )
        return True
