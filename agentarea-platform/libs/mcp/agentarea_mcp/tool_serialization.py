"""Normalize MCP SDK Tool objects into the plain dict shape we persist.

Single source of truth so every discovery path (verification, the Temporal
discovery activity, connection validation) captures identical fields. Keeping
this in one place is why annotations don't silently get dropped again.
"""

from collections.abc import Mapping
from typing import Any

from agentarea_mcp.domain.metering import META_RESOURCE_REF


def serialize_mcp_tool(tool: Any) -> dict[str, Any]:
    """Convert an mcp.types.Tool into a JSON-serializable dict.

    Captures the server-provided ``annotations`` (readOnlyHint, destructiveHint,
    idempotentHint, openWorldHint, title) and ``title`` verbatim. Per the MCP
    spec these annotations are *untrusted hints* — clients must not rely on them
    for security decisions. We persist them purely as informational metadata so
    the UI can offer an initial safety labeling that a user can review.

    Only the MCP Apps ``ui`` metadata is retained from the tool's ``_meta``.
    The SDK exposes that field as ``meta``; older payloads may use the flat
    ``ui/resourceUri`` key, which is folded into ``ui.resourceUri``.

    None-valued hints are dropped so the stored blob only carries what
    the server actually set.
    """
    out: dict[str, Any] = {
        "name": tool.name,
        "description": getattr(tool, "description", None) or "",
        "inputSchema": getattr(tool, "input_schema", None) or {},
    }

    title = getattr(tool, "title", None)
    if title:
        out["title"] = title

    annotations = getattr(tool, "annotations", None)
    if annotations is not None:
        if hasattr(annotations, "model_dump"):
            ann = annotations.model_dump(exclude_none=True, by_alias=True)
        elif isinstance(annotations, dict):
            ann = {k: v for k, v in annotations.items() if v is not None}
        else:
            ann = {}
        if ann:
            out["annotations"] = ann

    metadata = getattr(tool, "meta", None)
    if isinstance(metadata, Mapping):
        meta: dict[str, Any] = {}
        ui = metadata.get("ui")
        normalized_ui = dict(ui) if isinstance(ui, Mapping) else {}
        if "resourceUri" not in normalized_ui and "ui/resourceUri" in metadata:
            normalized_ui["resourceUri"] = metadata["ui/resourceUri"]
        if normalized_ui:
            meta["ui"] = normalized_ui
        # What a call is metered as; read only for a platform-managed connection
        # (domain/metering), where the platform itself declared it.
        if isinstance(metadata.get(META_RESOURCE_REF), str):
            meta[META_RESOURCE_REF] = metadata[META_RESOURCE_REF]
        if meta:
            out["_meta"] = meta

    return out
