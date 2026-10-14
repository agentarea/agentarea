"""What a call of an OpenAPI connection's operation costs, as its spec declares it.

The curated spec carries ``x-agentarea-payers`` at its root and ``x-agentarea-cost``
at its root (the default) or on an operation; see ``agentarea_common.tool_cost``. A
cost a member set on the connection wins over both.
"""

from typing import Any

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.tool_cost import ToolConnection, tool_connection

from .spec_parser import parse_openapi_operations


def openapi_tool_connection(connection: Any, connector: str, operation_name: str) -> ToolConnection:
    """The connection a call of ``operation_name`` runs on; a malformed declaration raises."""
    spec = connection.spec_content or {}
    configured = {p["name"] for p in connection.custom_query_params or []}
    cost = next(
        (
            op["cost"]
            for op in parse_openapi_operations(spec, configured)
            if op["name"] == operation_name
        ),
        None,
    )
    return tool_connection(
        connection_id=str(connection.id),
        connector=connector,
        tool=operation_name,
        platform_managed=connection.managed_by == MANAGED_BY_PLATFORM,
        payers=spec.get("x-agentarea-payers"),
        cost=cost,
        override=getattr(connection, "cost", None),
    )
