"""Compacting the conversation when it approaches the context window."""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from ..context_manager import find_compaction_boundary, validate_tool_pairs
    from ..context_strategy import ContextStrategy, allows_history_preservation
    from ..helpers import MessageBuilder
    from ..models import Message

from ...models import (
    CompactMessagesRequest,
    CompactMessagesResult,
    StoreHistoryRequest,
    StoreHistoryResult,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    Activities,
    EventTypes,
)
from ..retry import make_retry_policy
from .budget import BudgetMixin


class CompactionMixin(BudgetMixin):
    """Compacting the conversation when it approaches the context window."""

    async def _compact_context_if_needed(self) -> bool:
        """Check context usage and compact if threshold exceeded.

        Uses the head-and-tail strategy:
        1. Keep system prompt (head)
        2. Summarize middle messages via LLM
        3. Keep recent messages (tail)
        4. Validate tool pairs aren't broken

        Returns True if compaction was performed.
        """
        if not self.context_manager or not self.context_manager.needs_compaction():
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )

        # Convert messages to dict for boundary finding
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

        # Find safe compaction boundary
        boundary = find_compaction_boundary(messages_dict, keep_recent=4)
        if boundary <= 1:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False

        # Messages to compact: everything between system prompt and boundary
        messages_to_compact = messages_dict[1:boundary]
        if not messages_to_compact:
            return False

        # Preserve full history in MinIO before compaction (best-effort)
        strategy = ContextStrategy(self.state.context_strategy)
        if allows_history_preservation(strategy):
            try:
                chunk_index = self.state.history_chunk_counter
                store_hist_result: StoreHistoryResult = await workflow.execute_activity(
                    Activities.STORE_HISTORY_CHUNK,
                    args=[
                        StoreHistoryRequest(
                            task_id=str(self.state.task_id),
                            workspace_id=str(self.state.workspace_id),
                            chunk_index=chunk_index,
                            messages=messages_to_compact,
                        )
                    ],
                    result_type=StoreHistoryResult,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=make_retry_policy(2),
                )
                if store_hist_result.success:
                    self.state.history_chunk_counter += 1
                    workflow.logger.info(f"Stored history chunk {chunk_index} before compaction")
                else:
                    workflow.logger.warning(
                        f"History chunk store failed: {store_hist_result.error}"
                    )
            except Exception as e:
                workflow.logger.warning(f"History preservation failed (non-blocking): {e}")

        # Call compaction activity
        try:
            compact_request = CompactMessagesRequest(
                messages_to_compact=messages_to_compact,
                model_id=str(self.state.agent_config.get("model_id") or ""),
                workspace_id=self.state.workspace_id,
                user_context_data=self.state.user_context_data,
                resolved_model=self.state.resolved_model,
                effective_policy=self.state.effective_policy,
            )

            result: CompactMessagesResult = await workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[compact_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=make_retry_policy(2),
            )
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

            # Rebuild message list: system prompt + summary + kept recent messages
            system_msg = self.state.messages[0]
            recent_messages = list(self.state.messages[boundary:])

            summary_msg = Message(
                role="user",
                content=f"[Previous conversation summary]\n{result.summary}",
            )

            self.state.messages = [system_msg, summary_msg, *recent_messages]

            # Validate tool pairs in new message list
            new_messages_dict = [
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
            if not validate_tool_pairs(new_messages_dict):
                workflow.logger.error("Tool pair validation failed after compaction!")
                # Repair: drop orphaned tool results
                tool_use_ids: set[str] = set()
                for msg in self.state.messages:
                    if msg.role == "assistant" and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict) and tc.get("id"):
                                tool_use_ids.add(tc["id"])
                self.state.messages = [
                    msg
                    for msg in self.state.messages
                    if not (msg.role == "tool" and msg.tool_call_id not in tool_use_ids)
                ]

            self.context_manager.mark_compacted()

            # Publish compaction event
            self._events.add_event(
                EventTypes.CONTEXT_COMPACTED,
                {
                    "iteration": self.state.current_iteration,
                    "messages_compacted": result.original_message_count,
                    "tokens_saved": result.estimated_tokens_saved,
                    "compaction_number": self.context_manager.compaction_count,
                    "messages_remaining": len(self.state.messages),
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(
                f"Compacted {result.original_message_count} messages, "
                f"~{result.estimated_tokens_saved} tokens saved, "
                f"{len(self.state.messages)} messages remaining"
            )
            return True

        except Exception as e:
            workflow.logger.error(f"Context compaction failed: {e}")
            raise
