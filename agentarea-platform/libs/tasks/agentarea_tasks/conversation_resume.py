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


def _answered_tail(entries: Sequence[ConversationEntry]) -> list[ConversationEntry]:
    """The entries a chat model accepts in order.

    A tool result is valid only as the answer to a call of the assistant turn
    right before it, and every call of that turn needs its answer before the
    next message. A turn whose calls are not all answered is dropped with its
    partial answers, and so is a tool result no call asked for.
    """
    valid: list[ConversationEntry] = []
    open_calls: set[str] = set()
    turn_start = 0
    for entry in entries:
        if entry.role == "tool":
            if entry.tool_call_id in open_calls:
                valid.append(entry)
                open_calls.discard(entry.tool_call_id)
            continue
        if open_calls:
            del valid[turn_start:]
            open_calls = set()
        if entry.role == "assistant" and entry.tool_calls:
            call_ids = [call.get("id") for call in entry.tool_calls]
            if not all(isinstance(call_id, str) and call_id for call_id in call_ids):
                continue
            open_calls = {call_id for call_id in call_ids if isinstance(call_id, str)}
            turn_start = len(valid)
        valid.append(entry)
    if open_calls:
        del valid[turn_start:]
    return valid


def reconstruct_conversation(
    entries: Sequence[ConversationEntry],
    *,
    query: str,
    response: str | None,
) -> ReconstructedConversation:
    """Derive a resume snapshot from a task's conversation log.

    The log gets the final response as an assistant entry when its last entry
    is not already that answer; an empty log (a task older than the log) first
    gets the original request. The window is the system prompt and the latest
    summary as head, then everything after the summary (or the whole log).
    """
    ordered = sorted(entries, key=lambda entry: entry.seq)
    next_seq = ordered[-1].seq + 1 if ordered else 0
    appended: list[ConversationEntry] = []
    if not ordered:
        appended.append(ConversationEntry(seq=next_seq, role="user", content=query))
        next_seq += 1
    last = (ordered + appended)[-1]
    if response and not (last.role == "assistant" and not last.tool_calls):
        appended.append(ConversationEntry(seq=next_seq, role="assistant", content=response))
        next_seq += 1
    log = ordered + appended

    system = log[0] if log[0].role == "system" else None
    summary = next((entry for entry in reversed(log) if entry.kind == "summary"), None)
    head = [entry for entry in (system, summary) if entry is not None]
    tail_start = summary.seq + 1 if summary else 0
    head_seqs = {entry.seq for entry in head}
    tail = [entry for entry in log if entry.seq >= tail_start and entry.seq not in head_seqs]
    valid_tail = _answered_tail(tail)
    if len(valid_tail) == len(tail):
        window_head = [entry.seq for entry in head]
    else:
        # Listing the kept entries in the head leaves the dropped ones out of
        # the window while keeping every valid entry in its place.
        window_head = [entry.seq for entry in (*head, *valid_tail)]
        tail_start = next_seq

    assistant_turns = [entry for entry in log if entry.role == "assistant"]
    return ReconstructedConversation(
        snapshot=ConversationResumeSnapshot(
            head_seqs=window_head,
            tail_start=tail_start,
            next_seq=next_seq,
            current_iteration=max(len(assistant_turns), 1),
            tool_calls_used=sum(len(entry.tool_calls or []) for entry in assistant_turns),
        ),
        appended=appended,
        system_prompt_missing=system is None,
    )
