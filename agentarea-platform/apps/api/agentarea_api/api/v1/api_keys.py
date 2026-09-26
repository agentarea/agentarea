"""API endpoints for MCP API Keys.

API Key lifecycle (management — JWT-protected):
  POST   /v1/api-keys          → create API key (returns raw token once)
  GET    /v1/api-keys          → list API keys (no raw token)
  GET    /v1/api-keys/{id}     → get API key
  DELETE /v1/api-keys/{id}     → revoke API key
"""

import logging
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.authorization import assert_workspace_admin
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import (
    enforced_in_handler,
    requires_workspace_admin,
    unrestricted,
)
from agentarea_common.utils.types import UtcDatetime
from agentarea_mcp.application.access_token_service import APIKeyService
from agentarea_mcp.infrastructure.auth_repository import APIKeyRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Management router — JWT-protected (included in workspace_v1_router)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_api_key_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> APIKeyService:
    repo = APIKeyRepository(db_session, user_context)
    return APIKeyService(repo)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class APIKeyCreateRequest(BaseModel):
    name: str = Field(description="Human-friendly label for this API key")
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Optional expiry in days (omit for non-expiring)",
    )


class APIKeyResponse(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    is_active: bool
    expires_at: UtcDatetime | None
    access_count: int
    last_accessed_at: UtcDatetime | None
    created_at: UtcDatetime

    class Config:
        """Pydantic config."""

        from_attributes = True


class APIKeyCreateResponse(APIKeyResponse):
    """Extends APIKeyResponse with the raw token — shown ONCE at creation."""

    token: str = Field(description="Raw token value — copy it now, it won't be shown again")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=APIKeyCreateResponse,
    status_code=201,
    dependencies=[
        unrestricted(
            "mints a token that authenticates as its creator; grants no authority "
            "the caller does not already have"
        )
    ],
)
async def create_api_key(
    data: APIKeyCreateRequest,
    service: APIKeyService = Depends(get_api_key_service),
):
    """Create a new API key. The raw ``token`` value is returned once — store it securely."""
    try:
        record, raw_token = await service.create_token(
            name=data.name,
            expires_in_days=data.expires_in_days,
        )
        base = APIKeyResponse.model_validate(record)
        return APIKeyCreateResponse(**base.model_dump(), token=raw_token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create token: {exc}") from exc


@router.get("/", response_model=list[APIKeyResponse], dependencies=[requires_workspace_admin()])
async def list_api_keys(
    user_context: UserContextDep,
    service: APIKeyService = Depends(get_api_key_service),
):
    """List all API keys for the current workspace."""
    tokens = await service.list_tokens()
    return [APIKeyResponse.model_validate(t) for t in tokens]


@router.get("/{token_id}", response_model=APIKeyResponse, dependencies=[requires_workspace_admin()])
async def get_api_key(
    token_id: UUID,
    user_context: UserContextDep,
    service: APIKeyService = Depends(get_api_key_service),
):
    """Get a single API key by ID."""
    token = await service.get_token(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return APIKeyResponse.model_validate(token)


@router.delete(
    "/{token_id}",
    status_code=204,
    dependencies=[
        enforced_in_handler(
            "the key's creator, or a workspace admin; needs the record loaded first"
        )
    ],
)
async def revoke_api_key(
    token_id: UUID,
    user_context: UserContextDep,
    service: APIKeyService = Depends(get_api_key_service),
):
    """Immediately revoke an API key.

    The key's creator, or a workspace admin. The repository is scoped to the
    workspace, not to the caller, so without this a member could cut off a
    colleague's integrations.
    """
    record = await service.get_token(token_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if str(record.created_by) != user_context.user_id:
        await assert_workspace_admin(user_context)

    revoked = await service.revoke_token(token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
