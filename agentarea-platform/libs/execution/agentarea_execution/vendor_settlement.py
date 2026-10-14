"""Reading what a call finally cost from its vendor (wiki ADR-0038 §2.3, §2.7).

A connector whose cost is ``settled`` declares where the vendor says it later: one
GET with the connection's own credential, to a URL filled from what the call
returned. The settlement worker asks this for a waiting line; the answer is None
while the vendor is not done.
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.tool_cost import (
    MeteredCost,
    ToolConnection,
    ToolCostError,
    settle_url,
    settled_cost,
)
from agentarea_common.utils.url_safety import safe_async_client
from agentarea_mcp.domain.metering import mcp_tool_connection
from agentarea_tasks.cost_settlement import VendorSettle
from agentarea_tasks.infrastructure.orm import CostEntryORM

from .activities.dependencies import ActivityContext, ActivityServiceContainer

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20.0


async def _connection(
    ctx: ActivityContext, line: CostEntryORM
) -> tuple[ToolConnection, dict[str, str]]:
    """The line's connection, as its connector declares it, and its credential headers."""
    connection_id = UUID(str(line.subject_id))
    tool = str(line.subject_name or "")
    instances = await ctx.get_mcp_server_instance_service()
    instance = await instances.get(connection_id)
    if instance is not None:
        server = await instances.mcp_server_repository.get_server_by_id(instance.server_spec_id)
        connection = mcp_tool_connection(instance, getattr(server, "json_spec", None), tool)
        return connection, await instances.credential_headers(instance)
    from agentarea_openapi.application.metering import openapi_tool_connection

    connections = await ctx.get_openapi_connection_service()
    found = await connections.get_connection(connection_id)
    if found is None:
        raise ToolCostError(f"connection {connection_id} of line {line.id} no longer exists")
    connector = await connections.catalog_connector(found)
    return openapi_tool_connection(found, connector, tool), await connections.resolve_headers(found)


def make_vendor_settle(container: ActivityServiceContainer) -> VendorSettle:
    async def vendor_settle(line: CostEntryORM) -> MeteredCost | None:
        user_context = UserContext(user_id=line.created_by, workspace_id=line.workspace_id)
        async with ActivityContext(container, user_context) as ctx:
            connection, headers = await _connection(ctx, line)
        params: Any = (line.evidence or {}).get("settle_params") or {}
        url = settle_url(connection.cost_model, {str(k): str(v) for k, v in params.items()})
        async with safe_async_client(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            # The vendor keeps no record the call can be settled by (Apify answers an
            # MCP passthrough with no run at all): it billed nothing to read.
            logger.warning("Line %s settles at zero: the vendor has no %s", line.id, url)
            model = connection.cost_model
            return MeteredCost(
                Decimal(1), model.unit, Decimal(0), str(model.currency), model.source
            )
        response.raise_for_status()
        return settled_cost(connection.cost_model, response.json())

    return vendor_settle
