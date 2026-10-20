"""Which follow-up joins a waiting task: one of the same trigger, in a session that continues."""

import pytest
from agentarea_tasks.task_service import continued_session


def test_a_continued_session_of_a_trigger_routes():
    parameters = {"trigger_id": "trg-1", "session": {"key": "src:42", "continue": True}}
    assert continued_session(parameters) == ("src:42", "trg-1")


@pytest.mark.parametrize(
    "parameters",
    [
        None,
        {},
        {"trigger_id": "trg-1"},
        {"trigger_id": "trg-1", "session": {"key": "src:42", "continue": False}},
        {"trigger_id": "trg-1", "session": {"key": "src:42"}},
        {"trigger_id": "trg-1", "session": {"key": "", "continue": True}},
        {"session": {"key": "src:42", "continue": True}},
        {"trigger_id": "trg-1", "session": "src:42"},
    ],
)
def test_anything_else_starts_its_own_task(parameters):
    assert continued_session(parameters) == (None, None)
