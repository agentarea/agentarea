"""Normalize MCP SDK Tool objects into the plain dict shape we persist.

Single source of truth so every discovery path (verification, the Temporal
discovery activity, connection validation) captures identical fields. Keeping
this in one place is why annotations don't silently get dropped again.
"""

from typing import Any


def serialize_mcp_tool(tool: Any) -> dict[str, Any]:
    """Convert an mcp.types.Tool into a JSON-serializable dict.

    Captures the server-provided ``annotations`` (readOnlyHint, destructiveHint,
    idempotentHint, openWorldHint, title) and ``title`` verbatim. Per the MCP
    spec these annotations are *untrusted hints* — clients must not rely on them
    for security decisions. We persist them purely as informational metadata so
    the UI can offer an initial safety labeling that a user can review.

    None-valued hints are dropped so the stored blob only carries what the
    server actually set.
    """
    out: dict[str, Any] = {
        "name": tool.name,
        "description": getattr(tool, "description", None) or "",
        "inputSchema": getattr(tool, "inputSchema", None) or {},
    }

    title = getattr(tool, "title", None)
    if title:
        out["title"] = title

    annotations = getattr(tool, "annotations", None)
    if annotations is not None:
        if hasattr(annotations, "model_dump"):
            ann = annotations.model_dump(exclude_none=True)
        elif isinstance(annotations, dict):
            ann = {k: v for k, v in annotations.items() if v is not None}
        else:
            ann = {}
        if ann:
            out["annotations"] = ann

    return out
