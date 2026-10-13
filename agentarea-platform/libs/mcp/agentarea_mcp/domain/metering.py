"""What a call of an MCP connection's tool costs, as its catalog entry declares it.

A catalog MCP server declares, in its metadata, the payers it allows
(``agentarea:payers``) and a cost per tool (``agentarea:cost``:
``{"default": <declaration>, "tools": {<tool>: <declaration>}}``, see
``agentarea_common.tool_cost``). A connection with no catalog server behind it
declares nothing: its calls cost an unknown amount, and on the platform's key it is
refused.
"""

from typing import Any

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.tool_cost import (
    ToolConnection,
    ToolCostError,
    manual_connector,
    tool_connection,
)

META_PAYERS = "agentarea:payers"
META_COST = "agentarea:cost"


def mcp_tool_connection(
    instance: Any, server_spec: dict[str, Any] | None, tool_name: str
) -> ToolConnection:
    """The connection a call of ``tool_name`` on ``instance`` runs on.

    ``server_spec`` is the catalog server JSON the instance was made from, or None.
    A malformed declaration raises ``ToolCostError``.
    """
    metadata = (server_spec or {}).get("metadata") or {}
    cost = metadata.get(META_COST)
    if cost is not None and not isinstance(cost, dict):
        raise ToolCostError(f"{META_COST} must be an object of default and tools")
    tools = (cost or {}).get("tools") or {}
    if not isinstance(tools, dict):
        raise ToolCostError(f"{META_COST}.tools must map tool names to declarations")
    own = tools.get(tool_name)
    name = (server_spec or {}).get("name")
    return tool_connection(
        connection_id=str(instance.id),
        connector=str(name) if name else manual_connector(instance.id),
        tool=tool_name,
        platform_managed=getattr(instance, "managed_by", None) == MANAGED_BY_PLATFORM,
        payers=metadata.get(META_PAYERS),
        cost=own if own is not None else (cost or {}).get("default"),
    )
