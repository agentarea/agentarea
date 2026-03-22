"""Governance exceptions raised by the interceptor framework."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GovernanceDeniedError(Exception):
    """Raised when a gate interceptor denies an action."""

    reason: str
    interceptor_name: str
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"GovernanceDeniedError by {self.interceptor_name}: {self.reason}"


# Backward-compatible alias
GovernanceDenied = GovernanceDeniedError


@dataclass
class SecurityBlockedError(Exception):
    """Raised when a filter interceptor blocks content."""

    reason: str
    interceptor_name: str
    findings: list[Any] | None = None

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"SecurityBlockedError by {self.interceptor_name}: {self.reason}"


# Backward-compatible alias
SecurityBlocked = SecurityBlockedError


@dataclass
class EscalationRequiredError(Exception):
    """Raised when a gate interceptor requires human approval."""

    reason: str
    interceptor_name: str
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"EscalationRequiredError by {self.interceptor_name}: {self.reason}"


# Backward-compatible alias
EscalationRequired = EscalationRequiredError
