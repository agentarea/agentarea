"""API endpoints for MCP Personal Access Tokens (PATs).

PAT lifecycle (management — JWT-protected):
  POST   /v1/mcp-access-tokens          → create PAT (returns raw token once)
  GET    /v1/mcp-access-tokens          → list PATs (no raw token)
  GET    /v1/mcp-access-tokens/{id}     → get PAT
  DELETE /v1/mcp-access-tokens/{id}     → revoke PAT
"""

import logging
from datetime import datetime
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.access_token_service import MCPAccessTokenService
from agentarea_mcp.infrastructure.auth_repository import MCPAccessTokenRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Management router — JWT-protected (included in protected_v1_router)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/mcp-access-tokens", tags=["mcp-access-tokens"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_token_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> MCPAccessTokenService:
    repo = MCPAccessTokenRepository(db_session, user_context)
    return MCPAccessTokenService(repo)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AccessTokenCreateRequest(BaseModel):
    name: str = Field(description="Human-friendly label for this token")
    expires_in_days: int | None = Field(
        default=None, description="Optional expiry in days (omit for non-expiring)"
    )


class AccessTokenResponse(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    is_active: bool
    expires_at: datetime | None
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime

    class Config:
        """Pydantic config."""
        from_attributes = True


class AccessTokenCreateResponse(AccessTokenResponse):
    """Extends AccessTokenResponse with the raw token — shown ONCE at creation."""

    token: str = Field(description="Raw token value — copy it now, it won't be shown again")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=AccessTokenCreateResponse, status_code=201)
async def create_access_token(
    data: AccessTokenCreateRequest,
    service: MCPAccessTokenService = Depends(get_token_service),
):
    """Create a new PAT. The raw ``token`` value is returned once — store it securely."""
    try:
        record, raw_token = await service.create_token(
            name=data.name,
            expires_in_days=data.expires_in_days,
        )
        resp = AccessTokenCreateResponse.model_validate(record)
        resp.token = raw_token
        return resp
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create token: {exc}") from exc


@router.get("/", response_model=list[AccessTokenResponse])
async def list_access_tokens(
    user_context: UserContextDep,
    service: MCPAccessTokenService = Depends(get_token_service),
):
    """List all PATs for the current workspace."""
    tokens = await service.list_tokens()
    return [AccessTokenResponse.model_validate(t) for t in tokens]


@router.get("/{token_id}", response_model=AccessTokenResponse)
async def get_access_token(
    token_id: UUID,
    user_context: UserContextDep,
    service: MCPAccessTokenService = Depends(get_token_service),
):
    token = await service.get_token(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Access token not found")
    return AccessTokenResponse.model_validate(token)


@router.delete("/{token_id}", status_code=204)
async def revoke_access_token(
    token_id: UUID,
    user_context: UserContextDep,
    service: MCPAccessTokenService = Depends(get_token_service),
):
    """Immediately revoke a PAT."""
    revoked = await service.revoke_token(token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Access token not found")
