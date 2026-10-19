"""Which ``error`` a status update writes on the task row."""

from agentarea_tasks.infrastructure.task_log import TaskOutcome


def test_an_outcome_with_an_error_writes_it():
    assert TaskOutcome(status="failed", error="boom").error_fields() == {"error": "boom"}


def test_running_or_completing_again_clears_an_earlier_runs_error():
    assert TaskOutcome(status="running").error_fields() == {"error": None}
    assert TaskOutcome(status="completed").error_fields() == {"error": None}


def test_a_stopped_runs_later_update_without_an_error_keeps_the_one_it_set():
    for status in ("failed", "cancelled", "blocked", "waiting_for_input"):
        assert TaskOutcome(status=status).error_fields() == {}
