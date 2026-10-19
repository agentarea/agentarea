"""Compaction from the log: the whole conversation before it, the previous summary folded in.

No turn is kept verbatim; the text of every skill loaded so far is carried over
on the compaction row, and the prompt asks for the sections a run continues from.
"""

from agentarea_execution.activities.agent.conversation import (
    compaction_input,
    compaction_prompt,
)
from agentarea_tasks.domain.models import ConversationEntry

_SKILL = "<skill_content>Always cite the ledger.</skill_content>"
_EARLIER_SKILL = "<skill_content>Answer in Russian.</skill_content>"


def test_compaction_summarizes_everything_since_the_last_one_and_carries_every_skill():
    window = [
        ConversationEntry(seq=0, role="system", content="Agent instructions"),
        ConversationEntry(
            seq=4,
            kind="compaction",
            role="user",
            content="[Previous conversation summary]\nearlier work",
            meta={"skills": [_EARLIER_SKILL]},
        ),
        ConversationEntry(seq=5, role="user", content="Now the totals"),
        ConversationEntry(
            seq=6,
            role="assistant",
            content="",
            tool_calls=[{"id": "s1", "type": "function", "function": {"name": "activate_skill"}}],
        ),
        ConversationEntry(
            seq=7, role="tool", content=_SKILL, tool_call_id="s1", name="activate_skill"
        ),
        ConversationEntry(seq=8, role="assistant", content="Total is 42"),
    ]

    to_summarize, skills, replaced = compaction_input(window)

    assert [message["content"] for message in to_summarize] == [
        "[Previous conversation summary]\nearlier work",
        "Now the totals",
        "",
        "[Skill activated. It stays active: its full instructions are kept verbatim "
        "right after the summary.]",
        "Total is 42",
    ]
    assert skills == [_EARLIER_SKILL, _SKILL]
    assert [entry.seq for entry in replaced] == [5, 6, 7, 8]


def test_the_summarizer_is_told_a_skill_is_active_and_a_repeat_is_not_carried_as_skill():
    skill = '<skill_content name="pirate-codeword">The codeword is ARR.</skill_content>'
    already = "Skill 'pirate-codeword' is already active in this session."
    window = [
        ConversationEntry(seq=0, role="system", content="Agent instructions"),
        ConversationEntry(seq=1, role="tool", content=skill, tool_call_id="a", name="activate_skill"),
        ConversationEntry(
            seq=2, role="tool", content=already, tool_call_id="b", name="activate_skill"
        ),
    ]

    to_summarize, skills, _ = compaction_input(window)

    assert skills == [skill]
    assert "ARR" not in to_summarize[0]["content"]
    assert "Skill 'pirate-codeword' activated. It stays active" in to_summarize[0]["content"]
    assert to_summarize[1]["content"] == already


def test_a_window_of_only_the_system_prompt_has_nothing_to_compact():
    _, skills, replaced = compaction_input(
        [ConversationEntry(seq=0, role="system", content="Agent instructions")]
    )

    assert skills == []
    assert replaced == []


def test_the_compaction_row_shows_the_model_the_summary_then_the_skills():
    row = ConversationEntry(
        seq=9,
        kind="compaction",
        role="user",
        content="[Previous conversation summary]\nall of it",
        meta={"skills": [_EARLIER_SKILL, _SKILL]},
    )

    assert row.as_message() == {
        "role": "user",
        "content": f"[Previous conversation summary]\nall of it\n\n{_EARLIER_SKILL}\n\n{_SKILL}",
    }


def test_the_prompt_asks_for_every_section_a_run_continues_from():
    prompt = compaction_prompt([{"role": "user", "content": "Build the report"}])

    for section in (
        "Original request and intent",
        "User messages: every message the user sent",
        "Key facts and data",
        "Errors and how they were handled",
        "Still open",
        "Work in progress",
        "Next step",
    ):
        assert section in prompt
    assert prompt.endswith("[user]: Build the report\n")
