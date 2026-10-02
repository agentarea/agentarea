"""Compacting the conversation when it approaches the context window."""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from ..context_strategy import ContextStrategy, allows_history_preservation

from ...models import CompactMessagesRequest, CompactMessagesResult
from ..constants import HEARTBEAT_TIMEOUT, LLM_CALL_TIMEOUT, Activities, EventTypes
from ..retry import model_call_retry_policy
from .budget import BudgetMixin
from .patches import COMPACTION_BOUNDS_PAYLOAD_PATCH


class CompactionMixin(BudgetMixin):
    """Compacting the conversation when it approaches the context window."""

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
        bounds_payload = workflow.patched(COMPACTION_BOUNDS_PAYLOAD_PATCH)
        if force and not bounds_payload:
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )
        strategy = ContextStrategy(self.state.context_strategy)
        result: CompactMessagesResult = await workflow.execute_activity(
            Activities.COMPACT_MESSAGES,
            args=[
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
            ],
            result_type=CompactMessagesResult,
            start_to_close_timeout=LLM_CALL_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=model_call_retry_policy(),
        )
        self._apply_conversation_window(result.conversation)
        if result.original_message_count == 0:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False

        if result.cost is None or result.usage is None:
            raise ApplicationError(
                "compaction result has no usage accounting",
                type="LLMAccountingUnavailable",
                non_retryable=True,
            )
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

        workflow.logger.info(
            f"Compacted {result.original_message_count} messages, "
            f"~{result.estimated_tokens_saved} tokens saved"
        )
        return True
