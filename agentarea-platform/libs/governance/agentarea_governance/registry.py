"""Dynamic interceptor registry with phase-based registration."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .domain.enums import Phase
from .domain.models import InterceptorContext, InterceptorResult
from .domain.protocols import ExecutionInterceptor

logger = logging.getLogger(__name__)

Callback = Callable[[InterceptorResult, InterceptorContext], Any]


@dataclass
class InterceptorRegistration:
    """An interceptor bound to a phase with priority and callbacks."""

    interceptor: ExecutionInterceptor
    phase: Phase
    priority: int
    on_deny: Callback | None = None
    on_warn: Callback | None = None
    on_escalate: Callback | None = None


class InterceptorRegistry:
    """Registry for dynamic interceptor registration with phase and priority."""

    def __init__(self) -> None:
        self._registrations: dict[Phase, list[InterceptorRegistration]] = defaultdict(list)

    def register(
        self,
        interceptor: ExecutionInterceptor,
        phase: Phase,
        priority: int = 500,
        on_deny: Callback | None = None,
        on_warn: Callback | None = None,
        on_escalate: Callback | None = None,
    ) -> None:
        existing_priorities = [r.priority for r in self._registrations[phase]]
        if priority in existing_priorities:
            logger.warning(
                "Priority collision: %s at priority %d on phase %s",
                interceptor.name,
                priority,
                phase.value,
            )

        registration = InterceptorRegistration(
            interceptor=interceptor,
            phase=phase,
            priority=priority,
            on_deny=on_deny,
            on_warn=on_warn,
            on_escalate=on_escalate,
        )
        self._registrations[phase].append(registration)
        self._registrations[phase].sort(key=lambda r: r.priority)

    def unregister(self, name: str, phase: Phase) -> None:
        self._registrations[phase] = [
            r for r in self._registrations[phase] if r.interceptor.name != name
        ]

    def get_interceptors(self, phase: Phase) -> list[ExecutionInterceptor]:
        return [r.interceptor for r in self._registrations[phase]]

    def get_registrations(self, phase: Phase) -> list[InterceptorRegistration]:
        return list(self._registrations[phase])

    def has_interceptors(self, phase: Phase) -> bool:
        return len(self._registrations[phase]) > 0
