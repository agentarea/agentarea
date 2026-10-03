import pytest
from agentarea_evals.outcomes.classify import KNOWN_STATUSES, Outcome, classify
from agentarea_tasks.domain.statuses import TASK_STATUSES


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", Outcome.SUCCESS),
        ("awaiting_follow_up", Outcome.SUCCESS),
        ("failed", Outcome.FAILURE),
        ("waiting_for_continuation", Outcome.FAILURE),
        ("cancelled", Outcome.EXCLUDED),
        ("running", Outcome.PENDING),
        ("waiting_for_approval", Outcome.PENDING),
        ("waiting_for_input", Outcome.PENDING),
        ("submitted", Outcome.PENDING),
    ],
)
def test_status_alone(status, expected):
    assert classify(status, ratings=[]) is expected


def test_a_bad_rating_fails_a_completed_run():
    assert classify("completed", ratings=["good", "bad"]) is Outcome.FAILURE


def test_a_good_rating_does_not_rescue_a_failed_run():
    assert classify("failed", ratings=["good"]) is Outcome.FAILURE


def test_a_rating_on_a_run_still_in_progress_does_not_settle_it():
    assert classify("running", ratings=["bad"]) is Outcome.PENDING


@pytest.mark.parametrize("status", sorted(TASK_STATUSES))
def test_every_stored_status_is_classified_on_purpose(status):
    assert status in KNOWN_STATUSES


def test_an_unknown_status_waits_instead_of_breaking_the_read(caplog):
    assert classify("mystery", ratings=[]) is Outcome.PENDING
    assert "mystery" in caplog.text
