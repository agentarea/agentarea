"""Domain models for the interceptor framework.

Infrastructure-agnostic — zero imports from Temporal, FastAPI, or any runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .enums import InterceptorAction, Phase


@dataclass
class InterceptorContext:
    """Everything an interceptor needs to make a decision."""

    agent_id: UUID
    workspace_id: str
    user_id: str
    phase: Phase
    action_type: str
    action_name: str
    action_params: dict[str, Any] = field(default_factory=dict)
    content: str | None = None
    execution_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionFinding:
    """A single finding from a DetectionEngine."""

    category: str
    matched_text: str
    span: tuple[int, int]
    confidence: float
    engine_name: str


@dataclass(frozen=True)
class InterceptorResult:
    """Unified return type for all interceptor categories."""

    action: InterceptorAction
    interceptor_name: str
    reason: str
    modified_content: str | None = None
    findings: list[DetectionFinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
