"""Per-revision outcome counts over runs that already happened."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.orm import TaskORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.decisions.engine import ArmStats
from agentarea_evals.models import RunFeedback, task_summary
from agentarea_evals.outcomes.classify import Outcome, classify


@dataclass(frozen=True)
class RevisionOutcome:
    revision_id: UUID
    successes: int
    failures: int
    pending: int
    excluded: int
    cost_total: Decimal
    mean_duration_ms: float | None

    @property
    def runs(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float | None:
        return self.successes / self.runs if self.runs else None

    def arm(self) -> ArmStats:
        return ArmStats(
            successes=self.successes, failures=self.failures, cost_total=float(self.cost_total)
        )


class OutcomeStats:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.workspace_id = user_context.workspace_id

    async def by_revision(
        self,
        agent_id: UUID,
        *,
        revision_ids: list[UUID] | None = None,
        experiment_id: UUID | None = None,
        since: datetime | None = None,
    ) -> list[RevisionOutcome]:
        """Outcomes per revision, evaluation trials excluded.

        With ``experiment_id`` only the runs that experiment assigned count.
        """
        query = (
            select(
                TaskORM.id,
                TaskORM.agent_revision_id,
                TaskORM.status,
                TaskORM.task_metadata,
                task_summary.c.cost_usd,
                task_summary.c.duration_ms,
            )
            .outerjoin(task_summary, task_summary.c.task_id == TaskORM.id)
            .where(
                TaskORM.workspace_id == self.workspace_id,
                TaskORM.agent_id == agent_id,
                TaskORM.agent_revision_id.is_not(None),
            )
        )
        if revision_ids is not None:
            query = query.where(TaskORM.agent_revision_id.in_(revision_ids))
        if experiment_id is not None:
            query = query.where(TaskORM.experiment_id == experiment_id)
        if since is not None:
            # created_at is written as naive local time (datetime.now).
            query = query.where(TaskORM.created_at >= since.astimezone().replace(tzinfo=None))
        rows = [
            row
            for row in (await self.session.execute(query)).all()
            if (row.task_metadata or {}).get("run_mode") != "evaluation"
        ]
        if not rows:
            return []

        ratings: dict[UUID, list[str]] = defaultdict(list)
        feedback = await self.session.execute(
            select(RunFeedback.task_id, RunFeedback.rating).where(
                RunFeedback.task_id.in_([row.id for row in rows])
            )
        )
        for task_id, rating in feedback.all():
            ratings[task_id].append(rating)

        counts: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        cost: dict[UUID, Decimal] = defaultdict(Decimal)
        durations: dict[UUID, list[float]] = defaultdict(list)
        for row in rows:
            outcome = classify(row.status, ratings.get(row.id, []))
            counts[row.agent_revision_id][outcome] += 1
            if outcome in (Outcome.SUCCESS, Outcome.FAILURE):
                cost[row.agent_revision_id] += Decimal(row.cost_usd or 0)
                if row.duration_ms is not None:
                    durations[row.agent_revision_id].append(float(row.duration_ms))

        return [
            RevisionOutcome(
                revision_id=revision_id,
                successes=bucket[Outcome.SUCCESS],
                failures=bucket[Outcome.FAILURE],
                pending=bucket[Outcome.PENDING],
                excluded=bucket[Outcome.EXCLUDED],
                cost_total=cost[revision_id],
                mean_duration_ms=(
                    sum(durations[revision_id]) / len(durations[revision_id])
                    if durations[revision_id]
                    else None
                ),
            )
            for revision_id, bucket in counts.items()
        ]
