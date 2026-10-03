from uuid import uuid4

from agentarea_evals.runs.scoring import TrialVerdict, summarize


def test_pass_k_needs_every_trial_and_finds_regressions():
    a, b = uuid4(), uuid4()
    trials = [
        TrialVerdict(a, "baseline", True), TrialVerdict(a, "baseline", True),
        TrialVerdict(a, "candidate", True), TrialVerdict(a, "candidate", False),
        TrialVerdict(b, "baseline", False), TrialVerdict(b, "baseline", True),
        TrialVerdict(b, "candidate", True), TrialVerdict(b, "candidate", True),
    ]

    summary = summarize(trials, has_candidate=True)

    assert summary["regressions"] == [str(a)]
    assert summary["improvements"] == [str(b)]
    assert summary["baseline"] == {"cases_passed": 1, "trials_passed": 3, "trials": 4}
    assert summary["candidate"] == {"cases_passed": 1, "trials_passed": 3, "trials": 4}
    assert summary["passed"] is False


def test_a_candidate_with_no_regressions_passes():
    a = uuid4()
    trials = [TrialVerdict(a, "baseline", False), TrialVerdict(a, "candidate", True)]

    assert summarize(trials, has_candidate=True)["passed"] is True


def test_a_single_arm_run_passes_when_every_case_passes():
    a, b = uuid4(), uuid4()
    trials = [TrialVerdict(a, "baseline", True), TrialVerdict(b, "baseline", False)]

    summary = summarize(trials, has_candidate=False)

    assert summary["passed"] is False
    assert summary["failing_cases"] == [str(b)]


def test_unfinished_trials_count_as_not_passed():
    a = uuid4()
    trials = [TrialVerdict(a, "baseline", None)]

    assert summarize(trials, has_candidate=False)["passed"] is False


def test_a_run_where_trials_errored_is_inconclusive_not_passed():
    a = uuid4()
    trials = [
        TrialVerdict(a, "baseline", False, errored=True),
        TrialVerdict(a, "candidate", False, errored=True),
    ]

    summary = summarize(trials, has_candidate=True)

    assert summary["regressions"] == []
    assert summary["errored_trials"] == 2
    assert summary["passed"] is False


def test_a_candidate_that_passes_nothing_does_not_pass():
    a = uuid4()
    trials = [TrialVerdict(a, "baseline", False), TrialVerdict(a, "candidate", False)]

    assert summarize(trials, has_candidate=True)["passed"] is False
