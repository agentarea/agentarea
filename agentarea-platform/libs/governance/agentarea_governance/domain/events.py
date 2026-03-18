"""Governance domain events emitted by the interceptor framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from .enums import InterceptorAction, Phase


@dataclass(frozen=True)
class GovernanceViolation:
    """Emitted when an interceptor denies, warns, or escalates."""

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: UUID | None = None
    workspace_id: str = ""
    phase: Phase | None = None
    interceptor_name: str = ""
    action: InterceptorAction = InterceptorAction.DENY
    reason: str = ""
    action_type: str = ""
    action_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def event_type(self) -> str:
        return f"governance.{self.action.value}"


@dataclass(frozen=True)
class SecurityFinding:
    """Emitted when a filter interceptor detects sensitive content."""

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: UUID | None = None
    workspace_id: str = ""
    phase: Phase | None = None
    interceptor_name: str = ""
    finding_category: str = ""
    confidence: float = 0.0
    engine_name: str = ""
    action_type: str = ""
    action_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def event_type(self) -> str:
        return f"security.finding.{self.finding_category}"
