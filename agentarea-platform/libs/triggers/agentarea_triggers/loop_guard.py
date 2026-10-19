"""A trigger never reacts to an event its own task caused (ADR-0040 §4, "Loops are bounded").

An event of the platform stream names its task (``subject``). The walk goes
up from it: the task, the event that started that task (its ``causation_id``),
that event's task when it is a platform event, and so on. Finding a task this
trigger started means the event comes back to the trigger. The walk is
bounded by the causation depth limit, which also bounds the chain itself.
``infrastructure.causation_repository`` reads the chain from the database.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agentarea_streams.domain import StreamEvent
from agentarea_streams.domain.platform import PLATFORM_SOURCE_TYPE
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ChainTask:
    origin_type: str | None
    origin_id: str | None
    causation_id: str | None


@dataclass(frozen=True)
class ChainEvent:
    source_type: str | None
    subject: str | None


class CausationChain(Protocol):
    async def task(self, task_id: UUID) -> ChainTask | None: ...

    async def event(self, event_id: UUID) -> ChainEvent | None: ...


CausationChainFactory = Callable[[AsyncSession, str], CausationChain]


def _uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _task_of(source_type: str | None, subject: str | None) -> UUID | None:
    return _uuid(subject) if source_type == PLATFORM_SOURCE_TYPE else None


async def own_task_in_chain(
    chain: CausationChain, *, trigger_id: UUID, event: StreamEvent, max_hops: int
) -> UUID | None:
    """The task of ``trigger_id`` the event descends from, or None."""
    task_id = _task_of(event.source_type, event.subject)
    for _ in range(max_hops):
        if task_id is None:
            return None
        task = await chain.task(task_id)
        if task is None:
            return None
        if task.origin_type == "trigger" and task.origin_id == str(trigger_id):
            return task_id
        cause_id = _uuid(task.causation_id)
        cause = await chain.event(cause_id) if cause_id is not None else None
        task_id = _task_of(cause.source_type, cause.subject) if cause is not None else None
    return None
