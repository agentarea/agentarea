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

router = APIRouter(tags=["workspace-config"])


@router.get("/export", response_class=PlainTextResponse, dependencies=[requires_workspace_admin()])
async def export_workspace_config(
    user_context: UserContextDep,
    service: WorkspaceExportService = Depends(get_workspace_export_service),
):
    """Export the current workspace in the canonical Bundle YAML format.

    The output is accepted by the bundle Analyze and Install flow and can
    include agents, MCPs, skills, cron automations, and supported webhook
    channels. MCP credentials and Telegram tokens are setup-field references,
    never exported values. Provider configurations are not represented by the
    Bundle schema; configure them separately in the destination workspace.

    The response is served as ``text/plain`` so generated API clients receive
    the YAML body as a string.
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

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to export workspace configuration")
        raise HTTPException(status_code=500, detail="Internal server error") from e
