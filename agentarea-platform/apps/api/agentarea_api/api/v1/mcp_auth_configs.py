"""API endpoints for MCP authentication configurations."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import BaseSecretManagerDep, DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-auth-configs", tags=["mcp-auth-configs"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class MCPAuthConfigCreateRequest(BaseModel):
    name: str = Field(..., description="Human-readable name for this auth config")
    description: str | None = None
    auth_type: str = Field(..., description="One of: api_key, bearer, oauth2")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive config (header_name, token_url, client_id, scopes, …)",
    )
    credentials: dict[str, Any] = Field(
        default_factory=dict,
        description="Sensitive credentials encrypted at rest (header_value, token, client_secret, …)",
    )


class MCPAuthConfigUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class MCPAuthConfigResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    auth_type: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic config."""
        from_attributes = True


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_mcp_auth_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
) -> MCPAuthService:
    repo = MCPAuthConfigRepository(db_session, user_context)
    return MCPAuthService(repo, secret_manager)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=MCPAuthConfigResponse, status_code=201)
async def create_mcp_auth_config(
    data: MCPAuthConfigCreateRequest,
    user_context: UserContextDep,
    service: MCPAuthService = Depends(get_mcp_auth_service),
):
    """Create a new MCP authentication configuration."""
    try:
        MCPAuthService.validate_credentials(data.auth_type, data.credentials)
        config = await service.create(
            name=data.name,
            auth_type=data.auth_type,
            config=data.config,
            credentials=data.credentials,
            description=data.description,
        )
        return MCPAuthConfigResponse.model_validate(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create auth config: {exc}") from exc


@router.get("/", response_model=list[MCPAuthConfigResponse])
async def list_mcp_auth_configs(
    user_context: UserContextDep,
    service: MCPAuthService = Depends(get_mcp_auth_service),
):
    """List all MCP auth configs in the workspace."""
    configs = await service.list()
    return [MCPAuthConfigResponse.model_validate(c) for c in configs]


@router.get("/{config_id}", response_model=MCPAuthConfigResponse)
async def get_mcp_auth_config(
    config_id: UUID,
    user_context: UserContextDep,
    service: MCPAuthService = Depends(get_mcp_auth_service),
):
    config = await service.get(config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="MCP auth config not found")
    return MCPAuthConfigResponse.model_validate(config)


@router.put("/{config_id}", response_model=MCPAuthConfigResponse)
async def update_mcp_auth_config(
    config_id: UUID,
    data: MCPAuthConfigUpdateRequest,
    user_context: UserContextDep,
    service: MCPAuthService = Depends(get_mcp_auth_service),
):
    try:
        updated = await service.update(
            config_id=config_id,
            name=data.name,
            config=data.config,
            credentials=data.credentials,
            description=data.description,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="MCP auth config not found")
        return MCPAuthConfigResponse.model_validate(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update auth config: {exc}") from exc


@router.delete("/{config_id}", status_code=204)
async def delete_mcp_auth_config(
    config_id: UUID,
    user_context: UserContextDep,
    service: MCPAuthService = Depends(get_mcp_auth_service),
):
    try:
        deleted = await service.delete(config_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="MCP auth config not found")
    except ValueError as exc:
        # Linked instances prevent deletion → 409 Conflict
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete auth config: {exc}") from exc
