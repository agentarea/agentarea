"""A task's model conversation in its log: writing pending entries, reading the window."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.repository import TaskConversationRepository

from ...models import ConversationWindow

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer


def pending_entries(first_seq: int, messages: list[dict[str, Any]]) -> list[ConversationEntry]:
    """Messages the workflow has not written yet, at the positions it assigned them."""
    return [
        ConversationEntry(
            seq=first_seq + offset,
            role=message["role"],
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls"),
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name"),
        )
        for offset, message in enumerate(messages)
    ]


async def write_entries(
    container: "ActivityServiceContainer",
    user_context: UserContext,
    task_id: str,
    entries: list[ConversationEntry],
) -> None:
    """Commit entries to the task's conversation log."""
    from ..dependencies import ActivityContext

    async with ActivityContext(container, user_context) as ctx:
        session = container._database.async_session_factory()
        ctx._sessions.append(session)
        await TaskConversationRepository(session, user_context).write(UUID(task_id), entries)


async def sync_window(
    container: "ActivityServiceContainer",
    user_context: UserContext,
    window: ConversationWindow,
    pending: list[dict[str, Any]],
) -> tuple[list[ConversationEntry], list[ConversationEntry], int]:
    """Commit the pending entries, then read the window the model sees.

    Returns the head entries, the tail entries and the sequence number after the
    last written entry. Reading up to that bound, not to the end of the log,
    keeps a retried call on exactly the context of its first attempt.
    """
    from ..dependencies import ActivityContext

    end_seq = window.next_seq + len(pending)
    async with ActivityContext(container, user_context) as ctx:
        session = container._database.async_session_factory()
        ctx._sessions.append(session)
        repository = TaskConversationRepository(session, user_context)
        await repository.write(UUID(window.task_id), pending_entries(window.next_seq, pending))
        head, tail = await repository.read(
            UUID(window.task_id),
            head_seqs=window.head_seqs,
            tail_start=window.tail_start,
            end_seq=end_seq,
        )
    return head, tail, end_seq
