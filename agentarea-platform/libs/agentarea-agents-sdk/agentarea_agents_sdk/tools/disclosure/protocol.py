"""ToolDisclosurePolicy protocol and supporting types.

GoF Strategy: a swappable algorithm family for managing how tools enter and
leave the LLM's per-call context. The workflow depends only on this protocol;
concrete policies are interchangeable, and decorators (truncation, threshold,
metrics) compose at runtime without workflow changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCandidate:
    """A tool that the policy may keep explicit or defer.

    Carries enough metadata for both the catalog block (name + description)
    and on-demand reveal (full schema).
    """

    name: str
    description: str
    schema: dict[str, Any]
    connection_id: str = ""
    source_type: str = "openapi"


@dataclass
class SearchableEntry:
    """Lightweight projection of a deferred candidate, for the catalog block."""

    name: str
    description: str
    connection_id: str = ""


@dataclass
class Partition:
    """Result of policy.partition: explicit schemas + deferred candidates."""

    explicit: list[dict[str, Any]] = field(default_factory=list)
    deferred: list[ToolCandidate] = field(default_factory=list)


@dataclass
class RevealRequest:
    """Input to policy.reveal."""

    tool_names: list[str] = field(default_factory=list)


@dataclass
class RevealResult:
    """Result of policy.reveal."""

    revealed: list[dict[str, Any]] = field(default_factory=list)
    matched_names: list[str] = field(default_factory=list)
    unknown_names: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class DisclosureContext:
    """Dependency-injected context for policy decisions."""

    model_name: str = ""
    context_window: int = 0
    iteration: int = 0


@runtime_checkable
class ToolDisclosurePolicy(Protocol):
    """Strategy: decides what enters context now, what's deferred, and how to reveal."""

    def partition(self, candidates: list[ToolCandidate], ctx: DisclosureContext) -> Partition:
        """Split candidates into explicit (full schemas) and deferred (catalog only)."""
        ...

    def render_catalog(self, deferred: list[ToolCandidate], ctx: DisclosureContext) -> str:
        """System-prompt block describing deferred tools. Empty string = no block."""
        ...

    def get_meta_tool_definitions(self, ctx: DisclosureContext) -> list[dict[str, Any]]:
        """Function-call meta-tools the LLM uses to interact with this policy."""
        ...

    def reveal(
        self,
        request: RevealRequest,
        pool: list[ToolCandidate],
        ctx: DisclosureContext,
    ) -> RevealResult:
        """Resolve a reveal request into full schemas to append to the LLM context."""
        ...
