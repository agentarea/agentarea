"""API endpoints for MCP OAuth link management (provider config and access control).

This module manages the MCPOAuthLink records — the OAuth provider configuration
and access control settings for future Hydra-backed OAuth2 (mcp-ory-auth tier).

The actual MCP proxy endpoint is PAT-based (Bearer token).
See mcp_access_tokens.py for:
  - PAT management:  /v1/mcp-access-tokens
  - MCP proxy:       /mcp/{instance_id}
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.oauth_link_service import MCPOAuthLinkService
from agentarea_mcp.infrastructure.auth_repository import (
    MCPOAuthLinkRepository,
    MCPOAuthSessionRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-oauth-links", tags=["mcp-oauth-links"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class OAuthLinkCreateRequest(BaseModel):
    mcp_instance_id: UUID
    access_control: str = Field(
        default="workspace", description="Access control level: workspace | public"
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="OAuth provider config: provider, auth_url, token_url, client_id, scopes, …",
    )
    expires_in_days: int | None = Field(
        default=None, description="Optional link expiry in days"
    )


class OAuthLinkResponse(BaseModel):
    id: UUID
    mcp_instance_id: UUID
    token: str
    access_control: str
    is_active: bool
    expires_at: datetime | None
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime

    class Config:
        """Pydantic config."""
        from_attributes = True


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_oauth_link_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> MCPOAuthLinkService:
    link_repo = MCPOAuthLinkRepository(db_session, user_context)
    session_repo = MCPOAuthSessionRepository(db_session)
    return MCPOAuthLinkService(link_repo, session_repo)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=OAuthLinkResponse, status_code=201)
async def create_oauth_link(
    data: OAuthLinkCreateRequest,
    user_context: UserContextDep,
    service: MCPOAuthLinkService = Depends(get_oauth_link_service),
):
    """Store OAuth provider config for a container MCP instance."""
    try:
        link = await service.create_link(
            mcp_instance_id=data.mcp_instance_id,
            access_control=data.access_control,
            provider_config=data.provider_config,
            expires_in_days=data.expires_in_days,
        )
        return OAuthLinkResponse.model_validate(link)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create OAuth link: {exc}") from exc


@router.get("/instance/{instance_id}", response_model=list[OAuthLinkResponse])
async def list_oauth_links_for_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPOAuthLinkService = Depends(get_oauth_link_service),
):
    """List all OAuth links for a given MCP server instance."""
    links = await service.list_links(instance_id)
    return [OAuthLinkResponse.model_validate(lnk) for lnk in links]


@router.get("/{link_id}", response_model=OAuthLinkResponse)
async def get_oauth_link(
    link_id: UUID,
    user_context: UserContextDep,
    service: MCPOAuthLinkService = Depends(get_oauth_link_service),
):
    link = await service.get_link(link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="OAuth link not found")
    return OAuthLinkResponse.model_validate(link)


@router.delete("/{link_id}", status_code=204)
async def revoke_oauth_link(
    link_id: UUID,
    user_context: UserContextDep,
    service: MCPOAuthLinkService = Depends(get_oauth_link_service),
):
    """Immediately revoke an OAuth-protected link."""
    revoked = await service.revoke_link(link_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="OAuth link not found")
