from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import HandlerResult, ReactionTally, StreamEvent, SubscriptionView
from .processor import CodeRun


class SubscriptionHandler(Protocol):
    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult: ...


#: Writes a prepared reaction's result in the router's session and returns the verdict.
FinishReaction = Callable[[AsyncSession], Awaitable[HandlerResult]]


@runtime_checkable
class PreparedHandler(Protocol):
    """A handler whose slow part runs while the router holds no database session.

    The router calls ``prepare`` with no session or connection open, then calls
    what it returns in a new session, after checking the subscription again.
    """

    async def prepare(
        self, subscription: SubscriptionView, event: StreamEvent
    ) -> FinishReaction: ...


class ReactionLog(Protocol):
    """Where the router records each subscription's reaction to an event, before the ack.

    One reaction per (subscription, event): a redelivered event finds the
    reactions already recorded and the router runs only the rest. Never commits.
    """

    async def recorded(self, session: AsyncSession, event: StreamEvent) -> set[UUID]:
        """The subscriptions that already reacted to ``event``; a given-up reaction is not one."""
        ...

    async def forget_given_up(
        self, session: AsyncSession, subscription: SubscriptionView, event: StreamEvent
    ) -> None:
        """Drop the given-up reaction of ``subscription`` to ``event``, if any, before a rerun."""
        ...

    async def record(
        self,
        session: AsyncSession,
        subscription: SubscriptionView,
        event: StreamEvent,
        result: HandlerResult,
    ) -> None:
        """Record the reaction; one already there keeps its row and takes ``result``."""
        ...

    async def tally(self, session: AsyncSession, event: StreamEvent) -> ReactionTally:
        """Every reaction recorded to ``event`` so far, given-up ones as errors."""
        ...


class EventNotices(Protocol):
    """Tells the events pages open on a workspace that an event arrived or moved on.

    At most once and kept nowhere: a page that misses one reads the feed again.
    """

    async def recorded(self, event: StreamEvent) -> None: ...

    async def processing(self, event: StreamEvent) -> None: ...


class CodeRunner(Protocol):
    """Runs a processor's command in the sandbox, under the sandbox's own policy.

    Every run of one ``session`` shares a sandbox, so it stays warm. Raises
    ``ProcessorRuntimeUnavailableError`` when the sandbox cannot run it at all.
    """

    async def run(
        self,
        *,
        workspace_id: str,
        session: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CodeRun: ...
