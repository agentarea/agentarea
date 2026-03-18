"""Protocols for the interceptor framework.

These are the contracts that all interceptor and detection engine
implementations must satisfy.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .enums import InterceptorCategory
from .models import DetectionFinding, InterceptorContext, InterceptorResult


@runtime_checkable
class ExecutionInterceptor(Protocol):
    """Single protocol for all interceptor types — gates, filters, observers."""

    @property
    def name(self) -> str: ...

    @property
    def category(self) -> InterceptorCategory: ...

    async def execute(self, context: InterceptorContext) -> InterceptorResult: ...


@runtime_checkable
class DetectionEngine(Protocol):
    """Swappable detection strategy for filter interceptors.

    Defines HOW to detect. Swap regex for Presidio, LLM judge, external API.
    """

    async def detect(
        self, content: str, config: dict[str, Any]
    ) -> list[DetectionFinding]: ...
