"""MetricsObserver — emits Prometheus-style counters per interceptor decision."""

from __future__ import annotations

import logging
from collections import defaultdict

from ...domain.enums import InterceptorAction, InterceptorCategory
from ...domain.models import InterceptorContext, InterceptorResult

logger = logging.getLogger(__name__)


class MetricsObserver:
    """Observer interceptor that tracks decision counts.

    Maintains in-memory counters. In production, these would be
    emitted to Prometheus or similar.
    """

    def __init__(self) -> None:
        self.counters: dict[str, int] = defaultdict(int)

    @property
    def name(self) -> str:
        return "metrics_observer"

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.OBSERVER

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        key = f"{context.phase.value}.{context.action_type}"
        self.counters[key] += 1
        self.counters[f"total.{context.phase.value}"] += 1

        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self.name,
            reason="metrics recorded",
        )
