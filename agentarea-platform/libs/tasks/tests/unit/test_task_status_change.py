"""Which status writes are new transitions, the ones the run metrics count."""

from agentarea_tasks.infrastructure.task_log import TaskOutcome, changes_status


def test_moving_to_another_status_is_a_transition():
    assert changes_status("running", TaskOutcome(status="completed"))
    assert changes_status("completed", TaskOutcome(status="running"))
    assert changes_status("pending", TaskOutcome(status="running"))


def test_a_retried_write_of_the_status_the_task_has_is_not():
    assert not changes_status("completed", TaskOutcome(status="completed"))
    assert not changes_status("failed", TaskOutcome(status="failed", error="model 404"))


def test_a_write_without_an_outcome_is_not():
    assert not changes_status("running", None)
