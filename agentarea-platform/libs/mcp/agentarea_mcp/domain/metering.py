"""Metering vocabulary a platform-funded MCP connection speaks in ``_meta``.

The tool-gateway declares, per tool, the resource its calls are metered as, and
reports, per call, what the call used — never a price. Only a platform-managed
connection's declarations are believed: they are the platform's own server, while
any tenant's server could put the same keys on its tools.
"""

from typing import Any

from agentarea_common.constants import MANAGED_BY_PLATFORM

META_RESOURCE_REF = "agentarea.ai/resource_ref"
META_USAGE = "agentarea.ai/usage"


def platform_funded_resource(instance: Any, tool_name: str) -> str | None:
    """The resource a call of ``tool_name`` on ``instance`` is metered as.

    None for a connection that is not platform-managed: its calls cost the platform
    nothing. An empty string for a platform-managed tool that declares none, which a
    caller must refuse — it would run on the platform's credentials for nobody.
    """
    if instance is None or getattr(instance, "managed_by", None) != MANAGED_BY_PLATFORM:
        return None
    for tool in instance.get_available_tools() or []:
        if isinstance(tool, dict) and tool.get("name") == tool_name:
            meta = tool.get("_meta") or {}
            return str(meta.get(META_RESOURCE_REF) or "")
    return ""


def reported_quantity(meta: dict[str, Any] | None, resource_ref: str) -> int | None:
    """How much of ``resource_ref`` a call reported using, or None if it did not say."""
    usage = (meta or {}).get(META_USAGE)
    if not isinstance(usage, dict) or usage.get("resource_ref") != resource_ref:
        return None
    quantity = usage.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return None
    return quantity
