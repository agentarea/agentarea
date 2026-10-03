"""Lay out, claim, grade and close a suite run.

Each trial is one case on one arm, executed as a real task in evaluation mode.
The workflow drives the loop; this service owns the bookkeeping.
"""

import functools
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_common.auth.context import UserContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.models import (
    ARM_BASELINE,
    ARM_CANDIDATE,
    RUN_COMPLETED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_STOPPED,
    TRIAL_DONE,
    TRIAL_ERROR,
    TRIAL_PENDING,
    TRIAL_RUNNING,
    TRIAL_SKIPPED,
    EvalCase,
    EvalRun,
    EvalTrial,
)
from agentarea_evals.runs.scoring import TrialVerdict, summarize
from agentarea_evals.suites.checks import TrialOutcome, run_checks
from agentarea_evals.suites.service import SuiteService

_SANDBOX_GROUP = "sandbox"


class EvalRunError(ValueError):
    pass


@functools.cache
def _sandbox_toolsets() -> frozenset[str]:
    from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

    return frozenset(
        namespace
        for namespace, meta in get_code_tools_metadata().items()
        if meta.get("group") == _SANDBOX_GROUP
    )


def _uses_sandbox(spec: dict[str, Any]) -> bool:
    return any(
        isinstance(tool, dict) and tool.get("name") in _sandbox_toolsets()
        for tool in spec.get("tools") or []
    )


class EvalRunService:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
        self.revisions = RevisionService(session, user_context)
        self.suites = SuiteService(session, user_context)

    async def create_run(
        self,
        suite_id: UUID,
        agent: Agent,
        *,
        baseline_revision_id: UUID | None,
        candidate_revision_id: UUID | None,
        trials: int,
        concurrency: int,
        budget_usd: Decimal,
        allow_sandbox: bool,
    ) -> EvalRun:
        """Lay out every trial of a run. Nothing executes until the workflow claims them.

        ``allow_sandbox`` is the starter's explicit consent that sandbox tools run
        for real, inside each trial's own sandbox, with the deployment's network
        egress; a revision with sandbox tools is refused without it.
        """
        if budget_usd <= 0:
            raise EvalRunError("a run needs a positive budget")
        if not 1 <= trials <= 20:
            raise EvalRunError("trials must be between 1 and 20")
        if not 1 <= concurrency <= 10:
            raise EvalRunError("concurrency must be between 1 and 10")
        if await self.suites.get_suite(suite_id) is None:
            raise EvalRunError(f"suite {suite_id} not found")
        cases = await self.suites.list_cases(suite_id)
        if not cases:
            raise EvalRunError("the suite has no cases")

        if baseline_revision_id is None:
            baseline = await self.revisions.ensure_current(agent, origin="detected")
        else:
            found = await self.revisions.get(agent.id, baseline_revision_id)
            if found is None:
                raise EvalRunError(f"revision {baseline_revision_id} not found for this agent")
            baseline = found
        arms = {ARM_BASELINE: baseline}
        if candidate_revision_id is not None:
            candidate = await self.revisions.get(agent.id, candidate_revision_id)
            if candidate is None:
                raise EvalRunError(f"revision {candidate_revision_id} not found for this agent")
            if candidate.id == baseline.id:
                raise EvalRunError("the candidate is the baseline")
            arms[ARM_CANDIDATE] = candidate
        if not allow_sandbox and any(_uses_sandbox(r.spec) for r in arms.values()):
            raise EvalRunError(
                "this agent uses sandbox tools; allow the sandbox to run them for real "
                "inside each trial's own sandbox"
            )

        run = EvalRun(
            suite_id=suite_id,
            agent_id=agent.id,
            baseline_revision_id=baseline.id,
            candidate_revision_id=candidate_revision_id,
            trials=trials,
            concurrency=concurrency,
            budget_usd=budget_usd,
            cost_usd=Decimal(0),
            status=RUN_QUEUED,
            summary={"sandbox_allowed": allow_sandbox},
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(run)
        await self.session.flush()
        self.session.add_all(
            EvalTrial(
                run_id=run.id,
                case_id=case.id,
                arm=arm,
                attempt=attempt,
                status=TRIAL_PENDING,
                check_results=[],
                cost_usd=Decimal(0),
                workspace_id=self.user_context.workspace_id,
                created_by=self.user_context.user_id,
            )
            for case in cases
            for arm in arms
            for attempt in range(1, trials + 1)
        )
        await self.session.commit()
        return run

    async def get_run(self, run_id: UUID) -> EvalRun | None:
        result = await self.session.execute(
            select(EvalRun).where(
                EvalRun.id == run_id, EvalRun.workspace_id == self.user_context.workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def list_runs(self, agent_id: UUID) -> list[EvalRun]:
        result = await self.session.execute(
            select(EvalRun)
            .where(
                EvalRun.agent_id == agent_id,
                EvalRun.workspace_id == self.user_context.workspace_id,
            )
            .order_by(EvalRun.created_at.desc())
        )
        return list(result.scalars().all())

    async def trials(self, run_id: UUID) -> list[EvalTrial]:
        result = await self.session.execute(
            select(EvalTrial)
            .where(
                EvalTrial.run_id == run_id,
                EvalTrial.workspace_id == self.user_context.workspace_id,
            )
            .order_by(EvalTrial.case_id, EvalTrial.arm, EvalTrial.attempt)
        )
        return list(result.scalars().all())

    async def claim(self, run_id: UUID, *, limit: int) -> list[EvalTrial]:
        """Mark up to ``limit`` pending trials running; none once the run ended."""
        run = await self._require_run(run_id)
        if run.status not in (RUN_QUEUED, RUN_RUNNING) or limit <= 0:
            return []
        if run.status == RUN_QUEUED:
            run.status = RUN_RUNNING
            run.started_at = datetime.now(UTC)
        pending = (
            (
                await self.session.execute(
                    select(EvalTrial)
                    .where(EvalTrial.run_id == run_id, EvalTrial.status == TRIAL_PENDING)
                    .order_by(EvalTrial.attempt, EvalTrial.case_id, EvalTrial.arm)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for trial in pending:
            trial.status = TRIAL_RUNNING
        await self.session.commit()
        return list(pending)

    async def trial_spec(self, trial_id: UUID) -> dict[str, Any]:
        """What the workflow needs to start a trial's task."""
        trial = await self._require_trial(trial_id)
        run = await self._require_run(trial.run_id)
        case = await self._require_case(trial.case_id)
        revision_id = (
            run.candidate_revision_id if trial.arm == ARM_CANDIDATE else run.baseline_revision_id
        )
        return {
            "agent_id": str(run.agent_id),
            "revision_id": str(revision_id),
            "input": case.input,
            "parameters": dict(case.parameters or {}),
            "metadata": {
                "run_mode": "evaluation",
                "evaluation": {
                    "run_id": str(run.id),
                    "trial_id": str(trial.id),
                    "stubs": dict(case.stubs or {}),
                    "sandbox_allowed": bool((run.summary or {}).get("sandbox_allowed")),
                },
            },
        }

    async def attach_task(self, trial_id: UUID, task_id: UUID) -> None:
        trial = await self._require_trial(trial_id)
        trial.task_id = task_id
        await self.session.commit()

    async def record_outcome(self, trial_id: UUID, outcome: TrialOutcome) -> EvalTrial:
        trial = await self._require_trial(trial_id)
        case = await self._require_case(trial.case_id)
        passed, results = run_checks(list(case.checks or []), outcome)
        trial.passed = passed
        trial.check_results = results
        trial.cost_usd = Decimal(str(outcome.cost_usd))
        trial.status = TRIAL_DONE
        await self._charge(trial)
        await self.session.commit()
        return trial

    async def record_error(self, trial_id: UUID, error: str, *, cost_usd: float = 0.0) -> EvalTrial:
        trial = await self._require_trial(trial_id)
        trial.status = TRIAL_ERROR
        trial.passed = False
        trial.error = error
        trial.cost_usd = Decimal(str(cost_usd))
        await self._charge(trial)
        await self.session.commit()
        return trial

    async def stop(self, run_id: UUID, *, reason: str) -> EvalRun:
        run = await self._require_run(run_id)
        if run.status in (RUN_QUEUED, RUN_RUNNING):
            await self._end(run, RUN_STOPPED, reason)
            await self.session.commit()
        return run

    async def finalize(self, run_id: UUID) -> EvalRun:
        """Score the run. A stopped run keeps its status; its finished trials still count."""
        run = await self._require_run(run_id)
        verdicts = [
            TrialVerdict(t.case_id, t.arm, t.passed)
            for t in await self.trials(run_id)
            if t.status != TRIAL_SKIPPED
        ]
        summary = summarize(verdicts, has_candidate=run.candidate_revision_id is not None)
        summary["sandbox_allowed"] = bool((run.summary or {}).get("sandbox_allowed"))
        run.summary = summary
        if run.status in (RUN_QUEUED, RUN_RUNNING):
            run.status = RUN_COMPLETED
            run.completed_at = datetime.now(UTC)
        await self.session.commit()
        return run

    async def offline_passed(self, candidate_revision_id: UUID) -> bool:
        """Whether the latest completed run of this candidate found no regression."""
        result = await self.session.execute(
            select(EvalRun)
            .where(
                EvalRun.candidate_revision_id == candidate_revision_id,
                EvalRun.status == RUN_COMPLETED,
                EvalRun.workspace_id == self.user_context.workspace_id,
            )
            .order_by(EvalRun.completed_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return bool(latest and (latest.summary or {}).get("passed") is True)

    async def _charge(self, trial: EvalTrial) -> None:
        run = await self._require_run(trial.run_id)
        run.cost_usd = (run.cost_usd or Decimal(0)) + trial.cost_usd
        if run.cost_usd >= run.budget_usd and run.status in (RUN_QUEUED, RUN_RUNNING):
            await self._end(run, RUN_STOPPED, "budget")

    async def _end(self, run: EvalRun, status: str, reason: str) -> None:
        run.status = status
        run.stop_reason = reason
        run.completed_at = datetime.now(UTC)
        await self.session.execute(
            update(EvalTrial)
            .where(EvalTrial.run_id == run.id, EvalTrial.status == TRIAL_PENDING)
            .values(status=TRIAL_SKIPPED)
        )

    async def _require_run(self, run_id: UUID) -> EvalRun:
        run = await self.get_run(run_id)
        if run is None:
            raise EvalRunError(f"run {run_id} not found")
        return run

    async def _require_trial(self, trial_id: UUID) -> EvalTrial:
        result = await self.session.execute(
            select(EvalTrial).where(
                EvalTrial.id == trial_id,
                EvalTrial.workspace_id == self.user_context.workspace_id,
            )
        )
        trial = result.scalar_one_or_none()
        if trial is None:
            raise EvalRunError(f"trial {trial_id} not found")
        return trial

    async def _require_case(self, case_id: UUID) -> EvalCase:
        case = await self.suites.get_case(case_id)
        if case is None:
            raise EvalRunError(f"case {case_id} not found")
        return case
