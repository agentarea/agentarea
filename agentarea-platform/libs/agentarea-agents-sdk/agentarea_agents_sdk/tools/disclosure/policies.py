"""Concrete ToolDisclosurePolicy implementations.

ExplicitPolicy preserves the legacy "ship every schema every call" behavior.
NamedLookupPolicy ships only a name+description catalog plus a `load_tools`
meta-tool; the LLM picks names from the catalog and we resolve them on demand.
"""

from __future__ import annotations

from typing import Any

from .protocol import (
    DisclosureContext,
    Partition,
    RevealRequest,
    RevealResult,
    ToolCandidate,
)

LOAD_TOOLS_NAME = "load_tools"


class ExplicitPolicy:
    """All schemas in context every call. Identity policy — no behavior change."""

    def partition(self, candidates: list[ToolCandidate], ctx: DisclosureContext) -> Partition:
        return Partition(explicit=[c.schema for c in candidates], deferred=[])

    def render_catalog(self, deferred: list[ToolCandidate], ctx: DisclosureContext) -> str:
        return ""

    def get_meta_tool_definitions(self, ctx: DisclosureContext) -> list[dict[str, Any]]:
        return []

    def reveal(
        self,
        request: RevealRequest,
        pool: list[ToolCandidate],
        ctx: DisclosureContext,
    ) -> RevealResult:
        return RevealResult()


class NamedLookupPolicy:
    """Catalog of name+description in the system prompt; reveal by exact name.

    Token-saving choice: we never put per-operation `inputSchema` blocks in
    `available_tools` until the LLM explicitly asks for them via `load_tools`.
    """

    def partition(self, candidates: list[ToolCandidate], ctx: DisclosureContext) -> Partition:
        return Partition(explicit=[], deferred=list(candidates))

    def render_catalog(self, deferred: list[ToolCandidate], ctx: DisclosureContext) -> str:
        if not deferred:
            return ""

        groups: dict[str, list[ToolCandidate]] = {}
        for c in deferred:
            groups.setdefault(c.connection_id or "default", []).append(c)

        lines = [
            "",
            "## Available OpenAPI Operations",
            (
                f'Call {LOAD_TOOLS_NAME}(["name1","name2"]) with the exact '
                "operation names you need before invoking them."
            ),
        ]
        for connection_id in sorted(groups.keys()):
            lines.append("")
            lines.append(f"[{connection_id}]")
            for cand in sorted(groups[connection_id], key=lambda c: c.name):
                stripped = (cand.description or "").strip()
                first_line = stripped.splitlines()[0] if stripped else ""
                lines.append(f"- {cand.name}: {first_line}" if first_line else f"- {cand.name}")
        return "\n".join(lines)

    def get_meta_tool_definitions(self, ctx: DisclosureContext) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": LOAD_TOOLS_NAME,
                    "description": (
                        "Load full schemas for operations listed in 'Available OpenAPI "
                        "Operations'. Pass the exact operation names you need; after this "
                        "call those operations become callable as regular tools."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tool_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Exact operation names from the catalog.",
                            }
                        },
                        "required": ["tool_names"],
                    },
                },
            }
        ]

    def reveal(
        self,
        request: RevealRequest,
        pool: list[ToolCandidate],
        ctx: DisclosureContext,
    ) -> RevealResult:
        index = {c.name: c for c in pool}
        revealed: list[dict[str, Any]] = []
        matched: list[str] = []
        unknown: list[str] = []
        for name in request.tool_names:
            cand = index.get(name)
            if cand is None:
                unknown.append(name)
            else:
                revealed.append(cand.schema)
                matched.append(name)

        if unknown:
            valid_preview = sorted(index.keys())[:20]
            message = (
                f"Loaded {len(matched)} of {len(request.tool_names)} requested operations. "
                f"Unknown names: {unknown}. "
                f"Valid examples: {valid_preview}"
                + (" (more available)" if len(index) > 20 else "")
            )
        else:
            message = f"Loaded {len(matched)} operations: {matched}"
        return RevealResult(
            revealed=revealed,
            matched_names=matched,
            unknown_names=unknown,
            message=message,
        )
