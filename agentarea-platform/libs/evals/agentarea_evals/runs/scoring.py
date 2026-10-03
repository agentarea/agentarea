"""Verdicts of a suite run: pass^k per case, regressions between arms."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentarea_evals.models import ARM_BASELINE, ARM_CANDIDATE


@dataclass(frozen=True)
class TrialVerdict:
    case_id: UUID
    arm: str
    passed: bool | None
    # The trial did not produce a verdict: it could not start, timed out or waited on a person.
    errored: bool = False


def summarize(trials: list[TrialVerdict], *, has_candidate: bool) -> dict[str, Any]:
    """A case passes on an arm only when every trial of it passed (pass^k).

    With a candidate, the run passes when no case regresses (passing on the
    baseline and not on the candidate), no trial errored and the candidate
    passes at least one case: a run that measured nothing is not evidence.
    Without a candidate, every case must pass.
    """
    by_case: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for trial in trials:
        by_case[str(trial.case_id)][trial.arm].append(trial.passed is True)

    def arm_summary(arm: str) -> dict[str, int]:
        return {
            "cases_passed": sum(1 for arms in by_case.values() if arms.get(arm) and all(arms[arm])),
            "trials_passed": sum(sum(arms.get(arm, [])) for arms in by_case.values()),
            "trials": sum(len(arms.get(arm, [])) for arms in by_case.values()),
        }

    def passes(case: str, arm: str) -> bool:
        results = by_case[case].get(arm, [])
        return bool(results) and all(results)

    errored = sum(1 for trial in trials if trial.errored)
    summary: dict[str, Any] = {
        "cases": len(by_case),
        "baseline": arm_summary(ARM_BASELINE),
        "errored_trials": errored,
    }
    if has_candidate:
        regressions = sorted(
            c for c in by_case if passes(c, ARM_BASELINE) and not passes(c, ARM_CANDIDATE)
        )
        improvements = sorted(
            c for c in by_case if passes(c, ARM_CANDIDATE) and not passes(c, ARM_BASELINE)
        )
        summary.update(
            candidate=arm_summary(ARM_CANDIDATE),
            regressions=regressions,
            improvements=improvements,
        )
        summary["passed"] = (
            not regressions and not errored and summary["candidate"]["cases_passed"] > 0
        )
    else:
        failing = sorted(c for c in by_case if not passes(c, ARM_BASELINE))
        summary.update(failing_cases=failing, passed=not failing and bool(by_case))
    return summary
