from abc import ABC, abstractmethod
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import HandlerResult, JournaledEvent, SubscriptionView


class StreamWaker(ABC):
    """Tells dispatchers a stream has new events. Called after the append committed."""

    @abstractmethod
    async def wake(self, stream_id: UUID) -> None: ...


class SubscriptionHandler(Protocol):
    async def handle(
        self, subscription: SubscriptionView, event: JournaledEvent, session: AsyncSession
    ) -> HandlerResult: ...
