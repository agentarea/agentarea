import pytest
from agentarea_evals.outcomes.classify import Outcome, classify


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


def test_an_unknown_status_is_refused():
    with pytest.raises(ValueError, match="mystery"):
        classify("mystery", ratings=[])
