"""Context tools: recalling past history and reading offloaded tool output."""

import json

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from ..context_strategy import (
        ContextStrategy,
        allows_history_preservation,
        allows_output_offloading,
    )
    from ..helpers import build_output_summary
    from ..models import Message, ToolCall

from ...models import (
    ReadOutputRequest,
    ReadOutputResult,
    RecallHistoryRequest,
    RecallHistoryResult,
    SearchHistoryRequest,
    SearchHistoryResult,
    StoreOutputRequest,
    StoreOutputResult,
)
from ..constants import ACTIVITY_TIMEOUT, TOOL_OUTPUT_OFFLOAD_CHARS, Activities
from ..retry import make_retry_policy
from .base import AgentWorkflowBase


class ContextToolsMixin(AgentWorkflowBase):
    """Context tools: recalling past history and reading offloaded tool output."""

    async def _execute_recall_history(self, tool_call: ToolCall) -> None:
        """Execute recall_history tool.

        If grep or tool_name are provided and history chunks exist in MinIO,
        searches MinIO first. Falls back to DB event log query.
        """
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        grep = tool_args.get("grep")
        tool_name_filter = tool_args.get("tool_name")

        # Try MinIO history search first if grep/tool_name provided and chunks exist
        strategy = ContextStrategy(self.state.context_strategy)
        if (
            (grep or tool_name_filter)
            and allows_history_preservation(strategy)
            and self.state.history_chunk_counter > 0
        ):
            try:
                search_result: SearchHistoryResult = await workflow.execute_activity(
                    Activities.SEARCH_HISTORY,
                    args=[
                        SearchHistoryRequest(
                            task_id=str(self.state.task_id),
                            workspace_id=str(self.state.workspace_id),
                            grep=grep,
                            tool_name=tool_name_filter,
                        )
                    ],
                    result_type=SearchHistoryResult,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=make_retry_policy(2),
                )
                if search_result.success and search_result.results:
                    self.state.messages.append(
                        Message(
                            role="tool",
                            content=f"[History search results]\n{search_result.results}",
                            tool_call_id=tool_call.id,
                            name="recall_history",
                        )
                    )
                    return
            except Exception as e:
                workflow.logger.warning(f"MinIO history search failed, falling back to DB: {e}")

        # Fall back to DB event log query
        request = RecallHistoryRequest(
            task_id=UUID(self.state.task_id),
            workspace_id=self.state.workspace_id,
            query=tool_args.get("query"),
            event_types=tool_args.get("event_types"),
            limit=tool_args.get("limit", 20),
            user_context_data=self.state.user_context_data,
        )

        try:
            result: RecallHistoryResult = await workflow.execute_activity(
                Activities.RECALL_HISTORY,
                args=[request],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(2),
            )

            # Format events for the agent
            if result.events:
                content_parts = [result.summary, ""]
                for event in result.events:
                    content_parts.append(
                        f"[{event.get('created_at', '')}] "
                        f"{event.get('event_type', '')}: "
                        f"{json.dumps(event.get('data', {}), default=str)[:500]}"
                    )
                content = "\n".join(content_parts)
            else:
                content = "No events found for this task."

            self.state.messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )
        except Exception as e:
            workflow.logger.error(f"Recall history failed: {e}")
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Failed to recall history: {e}",
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )

    async def _execute_read_tool_output(self, tool_call: ToolCall) -> None:
        """Execute read_tool_output tool to retrieve offloaded content from MinIO."""
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        output_id = tool_args.get("output_id", "")
        if not output_id:
            self.state.messages.append(
                Message(
                    role="tool",
                    content="Error: output_id is required.",
                    tool_call_id=tool_call.id,
                    name="read_tool_output",
                )
            )
            return

        try:
            read_result: ReadOutputResult = await workflow.execute_activity(
                Activities.READ_CONTEXT_OUTPUT,
                args=[
                    ReadOutputRequest(
                        task_id=str(self.state.task_id),
                        workspace_id=str(self.state.workspace_id),
                        output_id=output_id,
                        grep=tool_args.get("grep"),
                        head=tool_args.get("head"),
                        tail=tool_args.get("tail"),
                    )
                ],
                result_type=ReadOutputResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(2),
            )

            content = (
                read_result.content
                if read_result.success
                else f"Error reading output: {read_result.error}"
            )
        except Exception as e:
            workflow.logger.error(f"read_tool_output failed: {e}")
            content = f"Failed to read output '{output_id}': {e}"

        self.state.messages.append(
            Message(
                role="tool",
                content=content,
                tool_call_id=tool_call.id,
                name="read_tool_output",
            )
        )

    async def _maybe_offload_output(self, content: str, output_id: str) -> str:
        """Offload large tool output to MinIO if strategy allows. Returns summary or original."""
        strategy = ContextStrategy(self.state.context_strategy)
        if not allows_output_offloading(strategy):
            return content
        if len(content) <= TOOL_OUTPUT_OFFLOAD_CHARS:
            return content

        try:
            store_result: StoreOutputResult = await workflow.execute_activity(
                Activities.STORE_CONTEXT_OUTPUT,
                args=[
                    StoreOutputRequest(
                        task_id=str(self.state.task_id),
                        workspace_id=str(self.state.workspace_id),
                        output_id=output_id,
                        content=content,
                    )
                ],
                result_type=StoreOutputResult,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(2),
            )
            if store_result.success:
                return build_output_summary(content, output_id)
            # Fallback: keep full content if store failed
            workflow.logger.warning(f"Output offload failed for {output_id}: {store_result.error}")
            return content
        except Exception as e:
            # Fallback: MinIO failure doesn't break agent execution
            workflow.logger.warning(f"Output offload exception for {output_id}: {e}")
            return content
