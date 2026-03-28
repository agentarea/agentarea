"""API endpoints for Compound MCPs."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.compound_service import CompoundMCPService
from agentarea_mcp.infrastructure.auth_repository import CompoundMCPRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compound-mcps", tags=["compound-mcps"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CompoundMCPCreateRequest(BaseModel):
    name: str
    description: str | None = None
    routing_mode: str = Field(default="parallel", description="parallel | fallback | conditional")


class CompoundMCPUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    routing_mode: str | None = None


class CompoundMCPMemberRequest(BaseModel):
    mcp_instance_id: UUID
    order: int = 0
    config: dict[str, Any] = Field(default_factory=dict)


class CompoundMCPMemberResponse(BaseModel):
    mcp_instance_id: UUID
    order: int
    config: dict[str, Any]
    namespace: str

    class Config:
        """Pydantic config."""

        from_attributes = True


class CompoundMCPResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    routing_mode: str
    endpoint_url: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic config."""

        from_attributes = True


def _with_endpoint_url(compound: Any) -> dict[str, Any]:
    """Add computed endpoint_url to a compound MCP."""
    data = CompoundMCPResponse.model_validate(compound).model_dump()
    slug = compound.name.lower().replace(" ", "-").replace("_", "-")
    data["endpoint_url"] = f"/mcp/compound-{slug}"
    return data


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_compound_mcp_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> CompoundMCPService:
    repo = CompoundMCPRepository(db_session, user_context)
    return CompoundMCPService(repo)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=CompoundMCPResponse, status_code=201)
async def create_compound_mcp(
    data: CompoundMCPCreateRequest,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    try:
        compound = await service.create(
            name=data.name,
            routing_mode=data.routing_mode,
            description=data.description,
        )
        return _with_endpoint_url(compound)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/", response_model=list[CompoundMCPResponse])
async def list_compound_mcps(
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    compounds = await service.list()
    return [_with_endpoint_url(c) for c in compounds]


@router.get("/{compound_id}", response_model=CompoundMCPResponse)
async def get_compound_mcp(
    compound_id: UUID,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    compound = await service.get(compound_id)
    if compound is None:
        raise HTTPException(status_code=404, detail="Compound MCP not found")
    return CompoundMCPResponse.model_validate(compound)


@router.put("/{compound_id}", response_model=CompoundMCPResponse)
async def update_compound_mcp(
    compound_id: UUID,
    data: CompoundMCPUpdateRequest,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    try:
        updated = await service.update(
            compound_id=compound_id,
            name=data.name,
            routing_mode=data.routing_mode,
            description=data.description,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Compound MCP not found")
        return CompoundMCPResponse.model_validate(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{compound_id}", status_code=204)
async def delete_compound_mcp(
    compound_id: UUID,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    deleted = await service.delete(compound_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Compound MCP not found")


@router.get("/{compound_id}/members", response_model=list[CompoundMCPMemberResponse])
async def list_compound_mcp_members(
    compound_id: UUID,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    members = await service.get_members(compound_id)
    return [
        CompoundMCPMemberResponse(
            mcp_instance_id=m.mcp_instance_id,
            order=m.order,
            config=m.config,
            namespace=service.get_tool_namespace(m),
        )
        for m in members
    ]


@router.post("/{compound_id}/members", response_model=CompoundMCPMemberResponse, status_code=201)
async def add_compound_mcp_member(
    compound_id: UUID,
    data: CompoundMCPMemberRequest,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    compound = await service.get(compound_id)
    if compound is None:
        raise HTTPException(status_code=404, detail="Compound MCP not found")
    try:
        member = await service.add_member(
            compound_id=compound_id,
            mcp_instance_id=data.mcp_instance_id,
            order=data.order,
            config=data.config,
        )
        return CompoundMCPMemberResponse(
            mcp_instance_id=member.mcp_instance_id,
            order=member.order,
            config=member.config,
            namespace=service.get_tool_namespace(member),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{compound_id}/members/{instance_id}", status_code=204)
async def remove_compound_mcp_member(
    compound_id: UUID,
    instance_id: UUID,
    user_context: UserContextDep,
    service: CompoundMCPService = Depends(get_compound_mcp_service),
):
    removed = await service.remove_member(compound_id, instance_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
