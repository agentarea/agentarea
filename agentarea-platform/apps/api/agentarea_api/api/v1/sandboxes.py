"""Workspace-scoped live sandbox inventory."""

import logging
from datetime import datetime

import httpx
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


class SandboxResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu: str
    memory: str


class SandboxSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    workspace_id: str = Field(exclude=True)
    task_id: str
    package_install: str
    state: str
    created_at: datetime
    expires_at: datetime | None
    resources: SandboxResources
    isolation: str


class SandboxListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SandboxSummary]
    total: int


@router.get("", response_model=SandboxListResponse)
async def list_sandboxes(user_context: UserContextDep) -> SandboxListResponse:
    """Return live provider state for the authenticated workspace only."""
    settings = get_settings().mcp
    inspection_secret = settings.SANDBOX_INSPECTION_AUTH_SECRET
    if inspection_secret is None or not inspection_secret.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox inventory is not configured",
        )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.MCP_MANAGER_URL.rstrip('/')}/sandbox/sessions",
                params={"workspace_id": str(user_context.workspace_id)},
                headers={
                    "Authorization": f"Bearer {inspection_secret.get_secret_value()}",
                },
            )
    except httpx.RequestError as exc:
        logger.warning("Sandbox inventory manager request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox inventory is temporarily unavailable",
        ) from exc

    if response.status_code >= 400:
        logger.warning(
            "Sandbox inventory manager returned %s: %s",
            response.status_code,
            response.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox inventory is temporarily unavailable",
        )

    try:
        result = SandboxListResponse.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        logger.error("Sandbox inventory manager returned an invalid response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Sandbox inventory response is invalid",
        ) from exc

    # Defense in depth: the manager receives a workspace filter, but the API
    # rejects any mismatched item rather than leaking it if a provider regresses.
    expected_workspace_id = str(user_context.workspace_id)
    if any(item.workspace_id != expected_workspace_id for item in result.items):
        logger.error("Sandbox inventory contained an item from another workspace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Sandbox inventory response is invalid",
        )
    return result
