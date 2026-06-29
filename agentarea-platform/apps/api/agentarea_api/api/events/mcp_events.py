"""MCP event handler on the broker-neutral event bus (ADR-0018).

Lifecycle is owned by the substrate (Go MCP manager + Docker); Python's
`verify()` + `container_monitor.py` sweep handle tool discovery and orphan
cleanup. This consumer remains for observability logging of status-change
events emitted by the Go MCP manager, now delivered as ``IntegrationEvent``s
over Redis Streams instead of FastStream pub/sub.
"""

import logging

from agentarea_common.events.ports import IntegrationEvent

logger = logging.getLogger(__name__)

# CloudEvents `type` for the MCP status-change event. The Go MCP manager XADDs
# to the stream derived from this (``events:<type>``); both sides must agree.
MCP_STATUS_CHANGED_TYPE = "agentarea.mcp.v1.MCPServerInstanceStatusChanged"


async def handle_mcp_status_changed(event: IntegrationEvent) -> None:
    """Log MCP server instance status changes from the Go MCP manager.

    Status persistence and tool discovery are handled by Temporal workflows;
    this handler is observability only.
    """
    data = event.data or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        logger.warning("MCPServerInstanceStatusChanged event missing instance_id")
        return

    logger.info(
        "MCP instance %s status: %s (container=%s, url=%s)",
        instance_id,
        data.get("status"),
        data.get("container_id"),
        data.get("url"),
    )
