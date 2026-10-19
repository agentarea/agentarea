"""Rebuild where a completed task's conversation stands when its run left no snapshot.

Runs that complete store a ``conversation_resume`` snapshot in the task metadata.
Tasks completed before that existed only have their conversation log, and the
oldest ones not even that; this derives a snapshot from what is there.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from agentarea_execution.models import ConversationResumeSnapshot

from .domain.models import ConversationEntry


@dataclass(frozen=True)
class ReconstructedConversation:
    """The snapshot to resume from and the entries the log still lacks.

    ``appended`` are written to the log before the resumed run starts.
    ``system_prompt_missing`` asks that run to write its system prompt first.
    """

    snapshot: ConversationResumeSnapshot
    appended: list[ConversationEntry]
    system_prompt_missing: bool


def reconstruct_conversation(
    entries: Sequence[ConversationEntry],
    *,
    query: str,
    response: str | None,
) -> ReconstructedConversation:
    """Derive a resume snapshot from a task's conversation log.

    The log gets the final response as an assistant entry when its last entry
    is not already that answer; an empty log (a task older than the log) first
    gets the original request. The resumed run reads its window from the log.
    """
    ordered = sorted(entries, key=lambda entry: entry.seq)
    next_seq = ordered[-1].seq + 1 if ordered else 0
    appended: list[ConversationEntry] = []
    if not any(entry.kind != "event" for entry in ordered):
        appended.append(ConversationEntry(seq=next_seq, role="user", content=query))
        next_seq += 1
    last = next(entry for entry in reversed(ordered + appended) if entry.kind != "event")
    if response and not (last.role == "assistant" and not last.tool_calls):
        appended.append(ConversationEntry(seq=next_seq, role="assistant", content=response))
        next_seq += 1
    log = ordered + appended

    system = next((entry for entry in log if entry.role == "system"), None)
    assistant_turns = [entry for entry in log if entry.role == "assistant"]
    return ReconstructedConversation(
        snapshot=ConversationResumeSnapshot(
            next_seq=next_seq,
            current_iteration=max(len(assistant_turns), 1),
            tool_calls_used=sum(len(entry.tool_calls or []) for entry in assistant_turns),
        ),
        appended=appended,
        system_prompt_missing=system is None,
    )
