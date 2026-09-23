"""API endpoints for workspace configuration export."""

import logging

from agentarea_agents.application.workspace_export_service import (
    WorkspaceExportService,
)
from agentarea_api.api.deps.services import get_workspace_export_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import requires_workspace_admin
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace-config"])


@router.get("/export", response_class=PlainTextResponse, dependencies=[requires_workspace_admin()])
async def export_workspace_config(
    user_context: UserContextDep,
    service: WorkspaceExportService = Depends(get_workspace_export_service),
):
    """Export current workspace configuration as YAML.

    This endpoint exports all workspace-scoped resources:
    - Agents (excluding system default agent)
    - MCP server instances
    - Provider configurations

    **Important Notes:**
    - Secrets (API keys, passwords) are replaced with placeholders
    - Built-in/catalog resources (carrying registry_item_id) are excluded
    - Only resources in the current workspace are exported
    - References to specs are included (server_spec_id, provider_spec_id)

    There is no matching import endpoint. Recreating a workspace goes through
    the platform toolsets (``agentarea/agents``, ``agentarea/mcp_servers``,
    ``agentarea/providers``, ``agentarea/skills``, ...) or bundle install,
    both of which handle secrets as first-class inputs instead of smuggling
    placeholders through a YAML file.

    **Returns:**
    YAML file content describing the workspace
    """
    try:
        yaml_content = await service.export_workspace()
        # The media type stays the one the route declares (text/plain). Serving
        # it as application/x-yaml made generated clients read the body as a
        # binary blob -- their own types promise a string -- so the webapp wrote
        # a file containing "{}". The .yaml filename comes from the disposition.
        return PlainTextResponse(
            content=yaml_content,
            headers={"Content-Disposition": "attachment; filename=workspace_config.yaml"},
        )

    except Exception as e:
        logger.exception("Failed to export workspace configuration")
        raise HTTPException(status_code=500, detail="Internal server error") from e
