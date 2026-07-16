"""OutboxPublisher — a drop-in for ``EventBroker`` that enqueues to the outbox.

Services that publish domain events mid-transaction swap ``event_broker`` for an
``OutboxPublisher`` built from the same session and user context. ``publish`` has
the same signature as ``EventBroker.publish`` so call sites change minimally.

Because it writes to the caller's session (no commit), the event row is part of
the service's unit of work: it commits with the aggregate or rolls back with it.
Delivery to the actual broker happens later, in the relay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession

from .base_events import DomainEvent, EventEnvelope
from .outbox_repository import OutboxRepository

if TYPE_CHECKING:
    from .event_models import BaseEvent

logger = logging.getLogger(__name__)

# Envelope ``data`` keys that carry the aggregate id, in priority order. The
# legacy DomainEvent flattens payload kwargs into ``data`` (so ``task_id`` etc.
# live there); typed BaseEvent also exposes ``aggregate_id`` directly.
_AGGREGATE_ID_KEYS = (
    "aggregate_id",
    "task_id",
    "server_id",
    "instance_id",
    "agent_id",
    "trigger_id",
)


class OutboxPublisher:
    """Publish domain events by enqueueing them to the transactional outbox."""

    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        self._repository = OutboxRepository(session, user_context)

    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        """Enqueue an event to the outbox on the current session.

        Failures propagate: an enqueue error must fail the enclosing operation
        (it is in the same transaction). This is intentional — the swallowing
        that this outbox replaces was the bug.
        """
        event_any = cast(Any, event)
        to_envelope = getattr(event_any, "to_envelope", None)
        if callable(to_envelope):
            envelope = cast(EventEnvelope, to_envelope())
        else:
            envelope = EventEnvelope.from_any(cast("EventEnvelope | DomainEvent", event))

        aggregate_id = self._derive_aggregate_id(envelope)
        aggregate_type = self._derive_aggregate_type(envelope)

        await self._repository.add(
            envelope,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
        )

    @staticmethod
    def _derive_aggregate_id(envelope: EventEnvelope) -> str:
        data = envelope.data or {}
        for key in _AGGREGATE_ID_KEYS:
            value = data.get(key)
            if value:
                return str(value)
        return str(envelope.event_id)

    @staticmethod
    def _derive_aggregate_type(envelope: EventEnvelope) -> str:
        data = envelope.data or {}
        explicit = data.get("aggregate_type")
        if explicit:
            return str(explicit)
        event_type = envelope.event_type or ""
        lowered = event_type.lower()
        if "task" in lowered:
            return "task"
        if "instance" in lowered:
            return "mcp_server_instance"
        if "mcp" in lowered or "server" in lowered:
            return "mcp_server"
        if "agent" in lowered:
            return "agent"
        if "trigger" in lowered:
            return "trigger"
        return "unknown"
