from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import HandlerResult, StreamEvent, SubscriptionView


class SubscriptionHandler(Protocol):
    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult: ...


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
