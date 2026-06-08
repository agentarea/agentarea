"""API endpoints for workspace configuration import/export."""

import logging

from agentarea_agents.application.import_export_service import (
    WorkspaceImportExportService,
)
from agentarea_agents.schemas.import_export import ImportOptions, ImportResult
from agentarea_api.api.deps.services import get_workspace_import_export_service
from agentarea_common.auth.dependencies import UserContextDep
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace-config"])


class ImportRequest(BaseModel):
    """Request body for importing workspace configuration."""

    yaml_content: str = Field(..., description="YAML configuration content")
    skip_missing_dependencies: bool = Field(
        default=False, description="Skip resources with missing dependencies"
    )
    override_existing: bool = Field(
        default=False, description="Override existing resources with same name"
    )


@router.post("/import", response_model=ImportResult)
async def import_workspace_config(
    request: ImportRequest,
    user_context: UserContextDep,
    service: WorkspaceImportExportService = Depends(get_workspace_import_export_service),
):
    """Import workspace configuration from YAML.

    This endpoint creates agents, MCP instances, and provider configs
    in the current workspace based on the provided YAML configuration.

    **Important Notes:**
    - All resources are created in the current workspace
    - Secrets (API keys, passwords) must be provided as they cannot be exported
    - References to MCP servers and provider specs must exist in the system
    - Import is atomic - if any resource fails, all changes are rolled back

    **Example YAML:**
    ```yaml
    agents:
      - name: "My Assistant"
        description: "Helpful assistant"
        instruction: "You are a helpful AI assistant"
        tools:
          - type: code
            name: agentarea/calculator
          - type: mcp
            name: my-filesystem
            settings:
              allowed_tools: [read_file, write_file]
        planning: false

    mcp_instances:
      - name: "My Filesystem"
        description: "Local file access"
        server_spec_id: "a1b2c3d4-..."
        env_vars:
          FILESYSTEM_ROOT: "/workspace"

    provider_configs:
      - name: "My OpenAI"
        provider_spec_id: "932f3839-..."
        api_key_placeholder: "sk-..."
    ```
    """
    try:
        options = ImportOptions(
            skip_missing_dependencies=request.skip_missing_dependencies,
            override_existing=request.override_existing,
        )

        result = await service.import_workspace(
            yaml_content=request.yaml_content,
            options=options,
        )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Import failed",
                    "errors": result.errors,
                    "warnings": result.warnings,
                },
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to import workspace configuration")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/import/file", response_model=ImportResult)
async def import_workspace_config_file(
    user_context: UserContextDep,
    file: UploadFile = File(..., description="YAML configuration file"),
    skip_missing_dependencies: bool = Query(
        default=False, description="Skip resources with missing dependencies"
    ),
    override_existing: bool = Query(
        default=False, description="Override existing resources with same name"
    ),
    service: WorkspaceImportExportService = Depends(get_workspace_import_export_service),
):
    """Import workspace configuration from uploaded YAML file.

    Same as /import but accepts a file upload instead of raw YAML content.
    """
    try:
        # Read file content
        yaml_content = await file.read()
        yaml_str = yaml_content.decode("utf-8")

        options = ImportOptions(
            skip_missing_dependencies=skip_missing_dependencies,
            override_existing=override_existing,
        )

        result = await service.import_workspace(
            yaml_content=yaml_str,
            options=options,
        )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Import failed",
                    "errors": result.errors,
                    "warnings": result.warnings,
                },
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to import workspace configuration from file")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/export", response_class=PlainTextResponse)
async def export_workspace_config(
    user_context: UserContextDep,
    service: WorkspaceImportExportService = Depends(get_workspace_import_export_service),
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

    **Returns:**
    YAML file content that can be saved and later imported
    """
    try:
        yaml_content = await service.export_workspace()
        return PlainTextResponse(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={"Content-Disposition": "attachment; filename=workspace_config.yaml"},
        )

    except Exception as e:
        logger.exception("Failed to export workspace configuration")
        raise HTTPException(status_code=500, detail="Internal server error") from e
