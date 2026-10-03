from datetime import timedelta

import pytest
from agentarea_evals.decisions.engine import ArmStats, ExperimentPolicy, decide, prob_regression

POLICY = ExperimentPolicy(auto_promote=True)
DAY = timedelta(days=1)


def arm(successes, failures, cost=0.0):
    return ArmStats(successes=successes, failures=failures, cost_total=cost * (successes + failures))


def test_prob_regression_is_deterministic():
    a, b = arm(90, 10), arm(18, 2)
    assert prob_regression(a, b, margin=0.03) == prob_regression(a, b, margin=0.03)


def test_a_clear_regression_stops_the_experiment():
    decision = decide(
        POLICY, exposure=10, control=arm(95, 5), candidate=arm(12, 8),
        candidate_runs_at_step=20, elapsed=DAY, offline_passed=True,
    )
    assert decision.action == "stop"
    assert decision.reason == "regression"


def test_one_failure_in_a_small_sample_is_not_a_regression():
    decision = decide(
        POLICY, exposure=10, control=arm(100, 0), candidate=arm(19, 1),
        candidate_runs_at_step=20, elapsed=DAY, offline_passed=True,
    )
    assert decision.action != "stop"


def test_too_few_runs_never_stop():
    decision = decide(
        POLICY, exposure=10, control=arm(5, 0), candidate=arm(0, 5),
        candidate_runs_at_step=5, elapsed=DAY, offline_passed=True,
    )
    assert decision.action == "continue"


def test_a_much_costlier_candidate_stops():
    decision = decide(
        POLICY, exposure=10, control=arm(30, 0, cost=0.10), candidate=arm(20, 0, cost=0.20),
        candidate_runs_at_step=20, elapsed=DAY, offline_passed=True,
    )
    assert decision.action == "stop"
    assert decision.reason == "cost"


def test_a_clean_step_ramps_to_the_next_exposure():
    decision = decide(
        POLICY, exposure=10, control=arm(180, 20), candidate=arm(19, 1),
        candidate_runs_at_step=20, elapsed=DAY, offline_passed=True,
    )
    assert decision.action == "ramp"
    assert decision.exposure == 25


def test_no_ramp_before_the_step_has_enough_runs():
    decision = decide(
        POLICY, exposure=10, control=arm(180, 20), candidate=arm(9, 1),
        candidate_runs_at_step=10, elapsed=DAY, offline_passed=True,
    )
    assert decision.action == "continue"


def test_a_non_inferior_candidate_at_full_exposure_is_promoted():
    decision = decide(
        POLICY, exposure=50, control=arm(190, 10), candidate=arm(196, 4),
        candidate_runs_at_step=200, elapsed=DAY * 14, offline_passed=True,
    )
    assert decision.action == "promote"


def test_without_auto_promote_it_is_only_recommended():
    decision = decide(
        ExperimentPolicy(auto_promote=False), exposure=50, control=arm(190, 10),
        candidate=arm(196, 4), candidate_runs_at_step=200, elapsed=DAY * 14,
        offline_passed=True,
    )
    assert decision.action == "recommend_promote"


def test_auto_promote_waits_for_an_offline_pass():
    decision = decide(
        POLICY, exposure=50, control=arm(190, 10), candidate=arm(196, 4),
        candidate_runs_at_step=200, elapsed=DAY * 14, offline_passed=False,
    )
    assert decision.action == "recommend_promote"
    assert "offline" in decision.reason


def test_running_out_of_time_ends_inconclusive():
    decision = decide(
        POLICY, exposure=50, control=arm(20, 2), candidate=arm(20, 3),
        candidate_runs_at_step=23, elapsed=DAY * 43, offline_passed=True,
    )
    assert decision.action == "stop"
    assert decision.reason == "inconclusive"


def test_policy_roundtrips_and_validates_steps():
    assert ExperimentPolicy.from_dict(POLICY.to_dict()) == POLICY
    with pytest.raises(ValueError, match="steps"):
        ExperimentPolicy(auto_promote=True, steps=(25, 10))
    with pytest.raises(ValueError, match="50"):
        ExperimentPolicy(auto_promote=True, steps=(10, 60))
