"""Governance exceptions raised by the interceptor framework."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GovernanceDenied(Exception):
    """Raised when a gate interceptor denies an action."""

    reason: str
    interceptor_name: str
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"GovernanceDenied by {self.interceptor_name}: {self.reason}"


@dataclass
class SecurityBlocked(Exception):
    """Raised when a filter interceptor blocks content."""

    reason: str
    interceptor_name: str
    findings: list[Any] | None = None

    def __str__(self) -> str:
        return f"SecurityBlocked by {self.interceptor_name}: {self.reason}"


@dataclass
class EscalationRequired(Exception):
    """Raised when a gate interceptor requires human approval."""

    reason: str
    interceptor_name: str
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"EscalationRequired by {self.interceptor_name}: {self.reason}"
