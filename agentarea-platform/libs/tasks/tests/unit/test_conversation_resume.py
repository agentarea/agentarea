from agentarea_execution.models import ConversationResumeSnapshot
from agentarea_tasks.conversation_resume import reconstruct_conversation
from agentarea_tasks.domain.models import ConversationEntry


def _window(entries: list[ConversationEntry], snapshot: ConversationResumeSnapshot) -> list[dict]:
    """The messages a resumed run's first model call sees, read the way the log reads them."""
    by_seq = {entry.seq: entry for entry in entries}
    head = [by_seq[seq] for seq in snapshot.head_seqs]
    tail = [
        by_seq[seq]
        for seq in sorted(by_seq)
        if snapshot.tail_start <= seq < snapshot.next_seq and seq not in snapshot.head_seqs
    ]
    return [entry.as_message() for entry in (*head, *tail)]


def _assert_valid_chat(messages: list[dict]) -> None:
    """No tool result without the call right before it, no call left unanswered."""
    open_calls: set[str] = set()
    for message in messages:
        if message["role"] == "tool":
            assert message["tool_call_id"] in open_calls, message
            open_calls.discard(message["tool_call_id"])
            continue
        assert not open_calls, f"unanswered calls {open_calls} before {message}"
        open_calls = {call["id"] for call in message.get("tool_calls") or []}
    assert not open_calls


def _call(call_id: str, name: str = "shell") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


def test_legacy_log_drops_broken_tool_turns_and_restores_the_final_answer():
    entries = [
        ConversationEntry(seq=0, role="system", content="Agent instructions"),
        ConversationEntry(seq=1, role="user", content="Original request"),
        ConversationEntry(seq=2, role="tool", content="orphan result", tool_call_id="orphan"),
        ConversationEntry(seq=3, role="assistant", content="", tool_calls=[_call("ok")]),
        ConversationEntry(seq=4, role="tool", content="listed", tool_call_id="ok"),
        ConversationEntry(seq=5, role="assistant", content="", tool_calls=[_call("a"), _call("b")]),
        ConversationEntry(seq=6, role="tool", content="half answered", tool_call_id="a"),
    ]

    rebuilt = reconstruct_conversation(
        entries, query="Original request", response="The original task is complete."
    )

    assert [(entry.seq, entry.role) for entry in rebuilt.appended] == [(7, "assistant")]
    assert rebuilt.system_prompt_missing is False
    assert rebuilt.snapshot.next_seq == 8
    assert rebuilt.snapshot.current_iteration == 3
    assert rebuilt.snapshot.tool_calls_used == 3
    window = _window([*entries, *rebuilt.appended], rebuilt.snapshot)
    _assert_valid_chat(window)
    assert window == [
        {"role": "system", "content": "Agent instructions"},
        {"role": "user", "content": "Original request"},
        {"role": "assistant", "content": "", "tool_calls": [_call("ok")]},
        {"role": "tool", "content": "listed", "tool_call_id": "ok"},
        {"role": "assistant", "content": "The original task is complete."},
    ]


def test_log_ending_in_the_answer_resumes_after_the_latest_summary():
    entries = [
        ConversationEntry(seq=0, role="system", content="Agent instructions"),
        ConversationEntry(seq=1, role="user", content="Compacted away"),
        ConversationEntry(seq=2, kind="summary", role="user", content="Summary so far"),
        ConversationEntry(seq=3, role="user", content="Next question"),
        ConversationEntry(seq=4, role="assistant", content="Answer"),
    ]

    rebuilt = reconstruct_conversation(entries, query="Compacted away", response="Answer")

    assert rebuilt.appended == []
    assert rebuilt.snapshot.head_seqs == [0, 2]
    assert rebuilt.snapshot.tail_start == 3
    assert rebuilt.snapshot.next_seq == 5
    assert [message["content"] for message in _window(entries, rebuilt.snapshot)] == [
        "Agent instructions",
        "Summary so far",
        "Next question",
        "Answer",
    ]


def test_task_older_than_the_log_gets_its_request_and_answer_logged():
    rebuilt = reconstruct_conversation([], query="List the files", response="Here they are")

    assert [(entry.seq, entry.role, entry.content) for entry in rebuilt.appended] == [
        (0, "user", "List the files"),
        (1, "assistant", "Here they are"),
    ]
    assert rebuilt.system_prompt_missing is True
    assert rebuilt.snapshot.head_seqs == []
    assert rebuilt.snapshot.tail_start == 0
    assert rebuilt.snapshot.next_seq == 2
    assert rebuilt.snapshot.current_iteration == 1
