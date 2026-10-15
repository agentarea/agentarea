"""A task's model conversation in its log: reading the window, compaction input, pending entries."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_agents_sdk.skills import SkillContextGuard
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.repository import TaskConversationRepository
from agentarea_tasks.infrastructure.task_log import TaskLog

from ...models import ConversationWindow

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer


def pending_entries(first_seq: int, messages: list[dict[str, Any]]) -> list[ConversationEntry]:
    """Messages the workflow has not written yet, at the positions it assigned them."""
    return [
        ConversationEntry(
            seq=first_seq + offset,
            kind=message.get("kind") or "message",
            role=message["role"],
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls"),
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name"),
            attachments=message.get("attachments"),
            meta=message.get("meta"),
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


async def read_window(
    container: "ActivityServiceContainer",
    user_context: UserContext,
    window: ConversationWindow,
    pending: list[dict[str, Any]],
) -> list[ConversationEntry]:
    """The window the model sees: the log up to ``window.next_seq``, then the pending messages.

    Nothing is written: the run records the pending messages itself. Reading
    up to that bound keeps a retried call on exactly the context of its first
    attempt.
    """
    from ..dependencies import ActivityContext

    async with ActivityContext(container, user_context) as ctx:
        session = container._database.async_session_factory()
        ctx._sessions.append(session)
        logged = await TaskLog(session, user_context, container.log_body_store()).window(
            UUID(window.task_id), window.next_seq
        )
    unwritten = [
        entry for entry in pending_entries(window.next_seq, pending) if entry.kind != "event"
    ]
    return [*logged, *unwritten]


async def sync_window(
    container: "ActivityServiceContainer",
    user_context: UserContext,
    window: ConversationWindow,
    pending: list[dict[str, Any]],
) -> tuple[list[ConversationEntry], list[ConversationEntry], int]:
    """Commit the pending entries, then read a cursor window (runs recorded before the log rule).

    Returns the head entries, the tail entries and the sequence number after the
    last written entry. Reading up to that bound, not to the end of the log,
    keeps a retried call on exactly the context of its first attempt.
    """
    from ..dependencies import ActivityContext

    if window.head_seqs is None or window.tail_start is None:
        raise ValueError(f"task {window.task_id} conversation window has no cursors")
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


def compaction_input(
    window: list[ConversationEntry],
) -> tuple[list[dict[str, Any]], list[str], list[ConversationEntry]]:
    """What a compaction of ``window`` summarizes and what it carries over verbatim.

    Returns the messages to summarize (the latest compaction's summary, then
    every message after it), the text of the skills loaded so far (those the
    latest compaction carried, then those loaded since) and the entries the
    compaction replaces. The system prompt is neither.
    """
    previous = next((entry for entry in window if entry.kind == "compaction"), None)
    skills: list[str] = list(((previous.meta or {}).get("skills") or []) if previous else [])
    replaced = [entry for entry in window if entry.kind == "message" and entry.role != "system"]
    to_summarize: list[dict[str, Any]] = (
        [{"role": "user", "content": previous.content}] if previous is not None else []
    )
    for entry in replaced:
        message = entry.as_message()
        if SkillContextGuard.is_protected(message):
            if entry.content not in skills:
                skills.append(entry.content)
            continue
        to_summarize.append(message)
    return to_summarize, skills, replaced


def compaction_prompt(messages: list[dict[str, Any]]) -> str:
    """The request to summarize ``messages`` into the sections a run continues from."""
    conversation_text = ""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if msg.get("tool_calls"):
            tool_names = [
                tc.get("function", {}).get("name", "?")
                for tc in msg["tool_calls"]
                if isinstance(tc, dict)
            ]
            content += f" [Called tools: {', '.join(tool_names)}]"
        if msg.get("name"):
            role = f"tool({msg['name']})"
        conversation_text += f"[{role}]: {content}\n"
    return (
        "Summarize the conversation below. The summary replaces it: the work continues "
        "from the summary alone, so keep everything that work needs. Write these "
        "sections, in this order, each under its own heading:\n"
        "1. Original request and intent: what was asked for, and why.\n"
        "2. User messages: every message the user sent, in order, quoted or closely "
        "paraphrased.\n"
        "3. Key facts and data: what the tools returned that the work depends on "
        "(names, ids, numbers, paths, URLs, decisions).\n"
        "4. Errors and how they were handled.\n"
        "5. Still open: questions, requirements or problems not yet resolved.\n"
        "6. Work in progress: what was being done when the conversation was cut, and "
        "how far it got.\n"
        "7. Next step: the next action to take.\n\n"
        "Be concise but complete; use bullet points for facts.\n\n"
        f"Conversation to summarize:\n{conversation_text}"
    )
