"""Where traffic goes next, decided from per-arm outcomes.

A canary, not an uplift experiment: at the volumes an agent sees, live traffic
can rule out a large regression but cannot prove a small improvement. The
candidate advances while there is no evidence it regresses by more than
``regression_margin`` and is promoted once it is confidently not worse by that
much. Probabilities come from Beta(1, 1) posteriors on each arm's failure rate.
"""

import hashlib
import random
from dataclasses import asdict, dataclass
from datetime import timedelta
from itertools import pairwise
from typing import Any, Literal

from agentarea_evals.decisions.bayes import prob_b_greater

Action = Literal["continue", "ramp", "stop", "promote", "recommend_promote"]

_DRAWS = 20_000


@dataclass(frozen=True)
class ExperimentPolicy:
    auto_promote: bool
    steps: tuple[int, ...] = (10, 25, 50)
    min_runs_per_step: int = 20
    min_runs_per_arm: int = 30
    min_guard_runs: int = 10
    regression_margin: float = 0.03
    stop_p_regression: float = 0.95
    ramp_max_p_regression: float = 0.5
    promote_max_p_regression: float = 0.05
    max_cost_ratio: float = 1.5
    max_duration_days: int = 42
    require_offline_pass: bool = True

    def __post_init__(self) -> None:
        """Refuse steps that are not strictly increasing shares up to 50%."""
        steps = tuple(self.steps)
        object.__setattr__(self, "steps", steps)
        if not steps or any(b <= a for a, b in pairwise(steps)):
            raise ValueError(f"steps must be strictly increasing, got {steps}")
        if steps[0] < 1 or steps[-1] > 50:
            raise ValueError(f"steps must lie between 1 and 50 percent, got {steps}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = list(self.steps)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentPolicy":
        values = dict(data)
        if "steps" in values:
            values["steps"] = tuple(values["steps"])
        return cls(**values)


@dataclass(frozen=True)
class ArmStats:
    successes: int
    failures: int
    cost_total: float = 0.0

    @property
    def runs(self) -> int:
        return self.successes + self.failures

    @property
    def mean_cost(self) -> float:
        return self.cost_total / self.runs if self.runs else 0.0


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    exposure: int | None = None
    p_regression: float | None = None
    p_better: float | None = None


def prob_regression(control: ArmStats, candidate: ArmStats, *, margin: float) -> float:
    """P(candidate failure rate > control failure rate + ``margin``).

    Monte Carlo with a seed derived from the counts, so the same evidence
    always yields the same decision.
    """
    seed = hashlib.sha256(
        f"{control.successes}:{control.failures}:{candidate.successes}:{candidate.failures}:{margin}".encode()
    ).digest()
    rng = random.Random(seed)  # noqa: S311 - a reproducible statistic, not a secret
    hits = 0
    for _ in range(_DRAWS):
        control_rate = rng.betavariate(control.failures + 1, control.successes + 1)
        candidate_rate = rng.betavariate(candidate.failures + 1, candidate.successes + 1)
        if candidate_rate > control_rate + margin:
            hits += 1
    return hits / _DRAWS


def decide(
    policy: ExperimentPolicy,
    *,
    exposure: int,
    control: ArmStats,
    candidate: ArmStats,
    candidate_runs_at_step: int,
    elapsed: timedelta,
    offline_passed: bool | None,
) -> Decision:
    p_regression = prob_regression(control, candidate, margin=policy.regression_margin)
    # P(candidate fails less often than control).
    p_better = prob_b_greater(
        candidate.failures + 1, candidate.successes + 1, control.failures + 1, control.successes + 1
    )

    def verdict(action: Action, reason: str, exposure: int | None = None) -> Decision:
        return Decision(action, reason, exposure, p_regression, p_better)

    guarded = control.runs >= policy.min_guard_runs and candidate.runs >= policy.min_guard_runs
    if guarded and p_regression >= policy.stop_p_regression:
        return verdict("stop", "regression")
    if (
        guarded
        and control.mean_cost > 0
        and candidate.mean_cost / control.mean_cost >= policy.max_cost_ratio
    ):
        return verdict("stop", "cost")
    if elapsed >= timedelta(days=policy.max_duration_days):
        return verdict("stop", "inconclusive")

    if exposure < policy.steps[-1]:
        if (
            candidate_runs_at_step >= policy.min_runs_per_step
            and p_regression <= policy.ramp_max_p_regression
        ):
            following = next(step for step in policy.steps if step > exposure)
            return verdict("ramp", "no evidence of regression at this step", following)
        return verdict("continue", "collecting runs at this step")

    settled = control.runs >= policy.min_runs_per_arm and candidate.runs >= policy.min_runs_per_arm
    if settled and p_regression <= policy.promote_max_p_regression:
        if not policy.auto_promote:
            return verdict("recommend_promote", "not worse; promotion is left to a person")
        if policy.require_offline_pass and not offline_passed:
            return verdict(
                "recommend_promote", "not worse live, but no passing offline evaluation yet"
            )
        return verdict("promote", "not worse than the serving revision")
    return verdict("continue", "collecting runs at full exposure")
