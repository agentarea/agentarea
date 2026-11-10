"""One-shot steps that bring the authorization graph up to the rows a release holds.

Alembic migrates the schema; it cannot write tuples. A step here does what a
data migration would for the graph -- grant the owners of rows created before
they were graph resources, say -- and ``agentarea-api migrate`` runs every
step not yet recorded in ``graph_migrations``, in id order, right after the
schema migration. A step is recorded only once it has applied; one that fails
raises and runs again on the next ``migrate``. Every step is idempotent, so a
step interrupted between applying and being recorded is safe to repeat.

A step asks for the graph client only when it has something to write: on a
fresh install the migration job runs before the graph store is reachable, and
a step with no rows must not need it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import DateTime, String, column, func, select, table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .openfga_client import OpenFGAClient

logger = logging.getLogger(__name__)

GraphProvider = Callable[[], Awaitable[OpenFGAClient]]
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_ID_RE = re.compile(r"^\d{8}_\d{4}_[a-z0-9_]+$")

_APPLIED = table(
    "graph_migrations",
    column("id", String),
    column("applied_at", DateTime(timezone=True)),
)


@dataclass(frozen=True)
class GraphMigration:
    """``id`` is dated like an alembic file, ``YYYYMMDD_HHMM_<slug>``; it orders the steps."""

    id: str
    description: str
    apply: Callable[[AsyncSession, GraphProvider], Awaitable[None]]


def _check_registry(steps: Sequence[GraphMigration]) -> None:
    ids = [step.id for step in steps]
    for step_id in ids:
        if not _ID_RE.match(step_id):
            raise ValueError(f"graph migration id {step_id!r} is not YYYYMMDD_HHMM_<slug>")
    if len(set(ids)) != len(ids):
        raise ValueError(f"graph migration ids repeat: {ids}")
    if ids != sorted(ids):
        raise ValueError(f"graph migrations are not in id order: {ids}")


async def apply_pending_graph_migrations(
    sessions: SessionFactory, steps: Sequence[GraphMigration], graph: GraphProvider
) -> list[str]:
    """Apply every step not yet recorded, each in its own session; return the ids applied."""
    _check_registry(steps)
    async with sessions() as session:
        applied = set((await session.execute(select(_APPLIED.c.id))).scalars())
    ran: list[str] = []
    for step in steps:
        if step.id in applied:
            continue
        logger.info("Applying graph migration %s: %s", step.id, step.description)
        async with sessions() as session:
            await step.apply(session, graph)
            await session.execute(
                insert(_APPLIED)
                .values(id=step.id, applied_at=func.now())
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.commit()
        ran.append(step.id)
    return ran
