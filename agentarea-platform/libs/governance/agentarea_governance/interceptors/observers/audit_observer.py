"""AuditObserver — emits governance events for audit trail."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.events import GovernanceViolation
from ...domain.models import InterceptorContext, InterceptorResult

logger = logging.getLogger(__name__)


class EventSink(Protocol):
    """Minimal protocol for event emission — compatible with EventBroker."""

    async def publish(self, event: Any) -> None: ...


class AuditObserver:
    """Observer interceptor that emits governance events to an event sink.

    Logs all interceptor executions for audit trail purposes.
    """

    def __init__(self, event_sink: EventSink | None = None) -> None:
        self._event_sink = event_sink

    @property
    def name(self) -> str:
        return "audit_observer"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.OBSERVER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        logger.debug(
            "Governance audit: phase=%s action_type=%s agent=%s",
            context.phase.value,
            context.action_type,
            context.agent_id,
        )

        if self._event_sink:
            event = GovernanceViolation(
                agent_id=context.agent_id,
                workspace_id=context.workspace_id,
                phase=context.phase,
                interceptor_name=self.name,
                action=InterceptorAction.ALLOW,
                reason="audit log",
                action_type=context.action_type,
                action_name=context.action_name,
            )
            try:
                await self._event_sink.publish(event)
            except Exception:
                logger.warning("Failed to publish audit event")

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="audit recorded",
        )
