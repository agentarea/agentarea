"""Request and response shapes for revisions, experiments, suites, runs and feedback."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from agentarea_agents.schemas.import_export import ToolConfig
from agentarea_agents.serving.models import AgentExperiment, AgentRevision
from pydantic import BaseModel, Field

from agentarea_evals.decisions.engine import ArmStats, Decision, ExperimentPolicy
from agentarea_evals.models import EvalCase, EvalRun, EvalSuite, EvalTrial, RunFeedback
from agentarea_evals.outcomes.stats import RevisionOutcome


class RevisionResponse(BaseModel):
    id: UUID
    agent_id: UUID
    number: int
    status: str
    origin: str
    message: str | None
    rationale: str | None
    evidence: list[dict[str, Any]]
    spec: dict[str, Any]
    config_hash: str
    parent_revision_id: UUID | None
    created_by: str
    created_at: datetime
    current: bool
    stale: bool

    @classmethod
    def build(cls, revision: AgentRevision, *, current_id: UUID | None) -> "RevisionResponse":
        return cls(
            id=revision.id,
            agent_id=revision.agent_id,
            number=revision.number,
            status=revision.status,
            origin=revision.origin,
            message=revision.message,
            rationale=revision.rationale,
            evidence=list(revision.evidence or []),
            spec=dict(revision.spec),
            config_hash=revision.config_hash,
            parent_revision_id=revision.parent_revision_id,
            created_by=revision.created_by,
            created_at=revision.created_at,
            current=revision.id == current_id,
            stale=revision.status == "candidate" and revision.parent_revision_id != current_id,
        )


class RevisionCreate(BaseModel):
    """A candidate: only the fields named here change; what serves does not."""

    instruction: str | None = None
    model_id: str | None = None
    tools: list[ToolConfig] | None = None
    skill_ids: list[UUID] | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    message: str | None = Field(default=None, max_length=500)
    rationale: str | None = Field(default=None, max_length=4000)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    def patch(self) -> dict[str, Any]:
        fields = ("instruction", "model_id", "tools", "skill_ids", "planning", "a2ui_enabled")
        patch = {name: getattr(self, name) for name in fields if name in self.model_fields_set}
        if self.tools is not None and "tools" in patch:
            patch["tools"] = [tool.model_dump(exclude_none=True) for tool in self.tools]
        return patch


class FieldChange(BaseModel):
    field: str
    before: Any
    after: Any


class RevisionOutcomeResponse(BaseModel):
    revision_id: UUID
    number: int | None
    successes: int
    failures: int
    pending: int
    excluded: int
    runs: int
    success_rate: float | None
    cost_total: Decimal
    mean_cost: Decimal | None
    mean_duration_ms: float | None

    @classmethod
    def build(cls, outcome: RevisionOutcome, number: int | None) -> "RevisionOutcomeResponse":
        return cls(
            revision_id=outcome.revision_id,
            number=number,
            successes=outcome.successes,
            failures=outcome.failures,
            pending=outcome.pending,
            excluded=outcome.excluded,
            runs=outcome.runs,
            success_rate=outcome.success_rate,
            cost_total=outcome.cost_total,
            mean_cost=(outcome.cost_total / outcome.runs) if outcome.runs else None,
            mean_duration_ms=outcome.mean_duration_ms,
        )


class ExperimentCreate(BaseModel):
    candidate_revision_id: UUID
    # Required on purpose: whether live evidence may switch traffic on its own
    # is the starter's decision, never a default.
    auto_promote: bool
    steps: list[int] | None = None
    max_duration_days: int | None = Field(default=None, ge=1, le=90)
    regression_margin: float | None = Field(default=None, gt=0, lt=0.5)

    def policy(self) -> ExperimentPolicy:
        overrides: dict[str, Any] = {}
        if self.steps is not None:
            overrides["steps"] = tuple(self.steps)
        if self.max_duration_days is not None:
            overrides["max_duration_days"] = self.max_duration_days
        if self.regression_margin is not None:
            overrides["regression_margin"] = self.regression_margin
        return ExperimentPolicy(auto_promote=self.auto_promote, **overrides)


class ArmResponse(BaseModel):
    successes: int
    failures: int
    runs: int
    failure_rate: float | None
    mean_cost: float | None

    @classmethod
    def build(cls, arm: ArmStats) -> "ArmResponse":
        return cls(
            successes=arm.successes,
            failures=arm.failures,
            runs=arm.runs,
            failure_rate=(arm.failures / arm.runs) if arm.runs else None,
            mean_cost=arm.mean_cost if arm.runs else None,
        )


class DecisionResponse(BaseModel):
    action: str
    reason: str
    exposure: int | None
    p_regression: float | None
    p_better: float | None

    @classmethod
    def build(cls, decision: Decision) -> "DecisionResponse":
        return cls(
            action=decision.action,
            reason=decision.reason,
            exposure=decision.exposure,
            p_regression=decision.p_regression,
            p_better=decision.p_better,
        )


class ExperimentResponse(BaseModel):
    id: UUID
    agent_id: UUID
    control_revision_id: UUID
    candidate_revision_id: UUID
    status: str
    weights: dict[str, int]
    policy: dict[str, Any]
    decisions: list[dict[str, Any]]
    started_at: datetime
    ended_at: datetime | None
    stop_reason: str | None
    last_evaluated_at: datetime | None
    control: ArmResponse
    candidate: ArmResponse
    offline_passed: bool

    @classmethod
    def build(
        cls,
        experiment: AgentExperiment,
        *,
        control: ArmStats,
        candidate: ArmStats,
        offline_passed: bool,
    ) -> "ExperimentResponse":
        return cls(
            id=experiment.id,
            agent_id=experiment.agent_id,
            control_revision_id=experiment.control_revision_id,
            candidate_revision_id=experiment.candidate_revision_id,
            status=experiment.status,
            weights=dict(experiment.weights),
            policy=dict(experiment.policy),
            decisions=list(experiment.decisions or []),
            started_at=experiment.started_at,
            ended_at=experiment.ended_at,
            stop_reason=experiment.stop_reason,
            last_evaluated_at=experiment.last_evaluated_at,
            control=ArmResponse.build(control),
            candidate=ArmResponse.build(candidate),
            offline_passed=offline_passed,
        )


class SuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class SuiteResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    case_count: int
    created_at: datetime

    @classmethod
    def build(cls, suite: EvalSuite, case_count: int) -> "SuiteResponse":
        return cls(
            id=suite.id,
            name=suite.name,
            description=suite.description,
            case_count=case_count,
            created_at=suite.created_at,
        )


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    stubs: dict[str, Any] = Field(default_factory=dict)


class CaseFromTask(BaseModel):
    task_id: UUID
    name: str | None = Field(default=None, max_length=200)


class CaseResponse(BaseModel):
    id: UUID
    suite_id: UUID
    name: str
    input: str
    parameters: dict[str, Any]
    checks: list[dict[str, Any]]
    stubs: dict[str, Any]
    source_task_id: UUID | None
    created_at: datetime

    @classmethod
    def build(cls, case: EvalCase) -> "CaseResponse":
        return cls(
            id=case.id,
            suite_id=case.suite_id,
            name=case.name,
            input=case.input,
            parameters=dict(case.parameters or {}),
            checks=list(case.checks or []),
            stubs=dict(case.stubs or {}),
            source_task_id=case.source_task_id,
            created_at=case.created_at,
        )


class EvalRunCreate(BaseModel):
    suite_id: UUID
    baseline_revision_id: UUID | None = None
    candidate_revision_id: UUID | None = None
    trials: int = Field(default=3, ge=1, le=20)
    concurrency: int = Field(default=3, ge=1, le=10)
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    allow_sandbox: bool = False


class EvalRunResponse(BaseModel):
    id: UUID
    suite_id: UUID
    agent_id: UUID
    baseline_revision_id: UUID
    candidate_revision_id: UUID | None
    trials: int
    concurrency: int
    budget_usd: Decimal
    cost_usd: Decimal
    status: str
    stop_reason: str | None
    summary: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def build(cls, run: EvalRun) -> "EvalRunResponse":
        return cls(
            id=run.id,
            suite_id=run.suite_id,
            agent_id=run.agent_id,
            baseline_revision_id=run.baseline_revision_id,
            candidate_revision_id=run.candidate_revision_id,
            trials=run.trials,
            concurrency=run.concurrency,
            budget_usd=run.budget_usd,
            cost_usd=run.cost_usd,
            status=run.status,
            stop_reason=run.stop_reason,
            summary=dict(run.summary or {}),
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )


class EvalTrialResponse(BaseModel):
    id: UUID
    case_id: UUID
    arm: str
    attempt: int
    task_id: UUID | None
    status: str
    passed: bool | None
    check_results: list[dict[str, Any]]
    cost_usd: Decimal
    error: str | None

    @classmethod
    def build(cls, trial: EvalTrial) -> "EvalTrialResponse":
        return cls(
            id=trial.id,
            case_id=trial.case_id,
            arm=trial.arm,
            attempt=trial.attempt,
            task_id=trial.task_id,
            status=trial.status,
            passed=trial.passed,
            check_results=list(trial.check_results or []),
            cost_usd=trial.cost_usd,
            error=trial.error,
        )


class EvalRunDetail(EvalRunResponse):
    trials_detail: list[EvalTrialResponse]
    cases: list[CaseResponse]


class FeedbackCreate(BaseModel):
    rating: Literal["good", "bad"]
    comment: str | None = Field(default=None, max_length=2000)
    event_id: str | None = Field(default=None, max_length=255)


class FeedbackResponse(BaseModel):
    id: UUID
    task_id: UUID
    rating: str
    comment: str | None
    event_id: str | None
    created_by: str
    created_at: datetime

    @classmethod
    def build(cls, feedback: RunFeedback) -> "FeedbackResponse":
        return cls(
            id=feedback.id,
            task_id=feedback.task_id,
            rating=feedback.rating,
            comment=feedback.comment,
            event_id=feedback.event_id,
            created_by=feedback.created_by,
            created_at=feedback.created_at,
        )
