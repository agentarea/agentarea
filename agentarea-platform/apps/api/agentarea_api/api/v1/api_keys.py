"""API endpoints for MCP API Keys.

API Key lifecycle (management — JWT-protected):
  POST   /v1/api-keys          → create API key (returns raw token once)
  GET    /v1/api-keys          → list API keys (no raw token)
  GET    /v1/api-keys/{id}     → get API key
  DELETE /v1/api-keys/{id}     → revoke API key

Creating and revoking keys needs a signed-in user: a key that could mint keys
would outlive its own revocation through the keys it minted.
"""

import logging
from uuid import UUID

from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_api.api.deps.services import AuditServiceDep, DatabaseSessionDep
from agentarea_common.auth.authorization import assert_workspace_admin, is_workspace_admin
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import (
    enforced_in_handler,
    requires_user_session,
    unrestricted,
)
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.utils.types import UtcDatetime
from agentarea_mcp.application.access_token_service import APIKeyService
from agentarea_mcp.infrastructure.auth_repository import APIKeyRepository
from fastapi import APIRouter, Depends, HTTPException, Query
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
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-friendly label for this API key",
    )
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Optional expiry in days (omit for non-expiring)",
    )
    agent_id: UUID | None = Field(
        default=None,
        description=(
            "Bind the key to one agent of this workspace: it then reaches only that "
            "agent over A2A, nothing else. The key to hand to a caller outside the workspace."
        ),
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
    agent_id: UUID | None = Field(
        default=None, description="The one agent the key reaches over A2A; None for a workspace key"
    )

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
        requires_user_session("create API keys"),
        unrestricted(
            "mints a token that authenticates as its creator; grants no authority "
            "the caller does not already have"
        ),
    ],
)
async def create_api_key(
    data: APIKeyCreateRequest,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    audit: AuditServiceDep,
    service: APIKeyService = Depends(get_api_key_service),
):
    """Create a new API key. The raw ``token`` value is returned once — store it securely."""
    if data.agent_id is not None:
        agents = RepositoryFactory(db_session, user_context).create_repository(AgentRepository)
        if await agents.get_by_id(data.agent_id) is None:
            raise HTTPException(status_code=404, detail="Agent not found")
    try:
        record, raw_token = await service.create_token(
            name=data.name,
            expires_in_days=data.expires_in_days,
            agent_id=data.agent_id,
        )
        base = APIKeyResponse.model_validate(record)
    except Exception as exc:
        # The exception can carry the INSERT and its parameters, token hash
        # included: it goes to the log, never into the response.
        logger.exception("Failed to create API key")
        raise HTTPException(status_code=500, detail="Failed to create API key") from exc
    await audit.record(
        "api_key.create",
        "api_key",
        record.id,
        event_metadata={
            "resource_name": record.name,
            "token_prefix": record.token_prefix,
            "agent_id": str(record.agent_id) if record.agent_id else None,
            "expires_at": base.expires_at.isoformat() if base.expires_at else None,
        },
    )
    return APIKeyCreateResponse(**base.model_dump(), token=raw_token)


@router.get(
    "/",
    response_model=list[APIKeyResponse],
    dependencies=[
        enforced_in_handler(
            "a workspace admin lists every key, a member only the keys they created"
        )
    ],
)
async def list_api_keys(
    user_context: UserContextDep,
    agent_id: UUID | None = Query(default=None, description="Only the keys bound to this agent"),
    service: APIKeyService = Depends(get_api_key_service),
):
    """List the API keys the caller may see: all of the workspace's for an admin, else their own."""
    if await is_workspace_admin(user_context):
        tokens = await service.list_tokens(agent_id=agent_id)
    else:
        tokens = await service.list_tokens(created_by=user_context.user_id, agent_id=agent_id)
    return [APIKeyResponse.model_validate(t) for t in tokens]


@router.get(
    "/{token_id}",
    response_model=APIKeyResponse,
    dependencies=[
        enforced_in_handler(
            "the key's creator, or a workspace admin; needs the record loaded first"
        )
    ],
)
async def get_api_key(
    token_id: UUID,
    user_context: UserContextDep,
    service: APIKeyService = Depends(get_api_key_service),
):
    """Get a single API key by ID.

    Someone else's key answers 404 to a member, as a missing one does, so the
    ids of colleagues' keys cannot be confirmed.
    """
    token = await service.get_token(token_id)
    if token is None or (
        str(token.created_by) != user_context.user_id and not await is_workspace_admin(user_context)
    ):
        raise HTTPException(status_code=404, detail="API key not found")
    return APIKeyResponse.model_validate(token)


@router.delete(
    "/{token_id}",
    status_code=204,
    dependencies=[
        requires_user_session("revoke API keys"),
        enforced_in_handler(
            "the key's creator, or a workspace admin; needs the record loaded first"
        ),
    ],
)
async def revoke_api_key(
    token_id: UUID,
    user_context: UserContextDep,
    audit: AuditServiceDep,
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

    name, token_prefix = record.name, record.token_prefix
    revoked = await service.revoke_token(token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    await audit.record(
        "api_key.revoke",
        "api_key",
        token_id,
        event_metadata={"resource_name": name, "token_prefix": token_prefix},
    )
