"""Clients (agent-proxy) CRUD API endpoints."""

import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config.app import get_app_settings
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.schemas.client_dto import ClientCreate, ClientUpdate
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from ._access_control_grants import grant_resource_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"])


async def get_client_service(
    repository_factory: RepositoryFactoryDep,
) -> ClientService:
    repo = repository_factory.create_repository(ClientRepository)
    return ClientService(repo)


ClientServiceDep = Annotated[ClientService, Depends(get_client_service)]


class AssociationBody(BaseModel):
    id: str


class McpInstanceAssociationBody(BaseModel):
    id: str
    namespace_prefix: str | None = None


class SourceProjectBody(BaseModel):
    project_id: str | None = None


class ClientRef(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ClientResponse(BaseModel):
    id: UUID
    workspace_id: str
    created_by: str
    name: str
    description: str | None
    kind: str
    source_project_id: str | None
    skills: list[ClientRef] = []
    mcp_instances: list[ClientRef] = []
    mcp_endpoint_url: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("skills", "mcp_instances", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        return v if v is not None else []


def _mcp_endpoint_url(client_id: UUID) -> str:
    base = get_app_settings().API_BASE_URL.rstrip("/")
    return f"{base}/client-mcp/{client_id}"


def _to_response(client) -> ClientResponse:
    resp = ClientResponse.model_validate(client)
    resp.mcp_endpoint_url = _mcp_endpoint_url(client.id)
    return resp


@router.post("/", response_model=ClientResponse, status_code=201)
async def create_client(
    data: ClientCreate,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.create_client(data)
    await grant_resource_owner(
        resource_id=client.id,
        workspace_id=user_context.workspace_id,
        user_id=user_context.user_id,
    )
    return _to_response(client)


@router.get("/", response_model=list[ClientResponse])
async def list_clients(
    user_context: UserContextDep,
    service: ClientServiceDep,
    limit: int = 100,
    offset: int = 0,
):
    clients = await service.list(limit=limit, offset=offset)
    return [_to_response(c) for c in clients]


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return _to_response(client)


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID,
    data: ClientUpdate,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.update_client(client_id, data)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return _to_response(client)


@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    deleted = await service.delete(client_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Client not found")


@router.post("/{client_id}/skills", status_code=204)
async def add_skill_to_client(
    client_id: UUID,
    body: AssociationBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.add_skill(client_id, body.id)


@router.delete("/{client_id}/skills/{skill_id}", status_code=204)
async def remove_skill_from_client(
    client_id: UUID,
    skill_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.remove_skill(client_id, skill_id)


@router.post("/{client_id}/mcp-instances", status_code=204)
async def add_mcp_instance_to_client(
    client_id: UUID,
    body: McpInstanceAssociationBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.add_mcp_instance(client_id, body.id, body.namespace_prefix)


@router.delete("/{client_id}/mcp-instances/{mcp_instance_id}", status_code=204)
async def remove_mcp_instance_from_client(
    client_id: UUID,
    mcp_instance_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.remove_mcp_instance(client_id, mcp_instance_id)


@router.post("/{client_id}/pull-from-project", response_model=ClientResponse)
async def pull_from_project(
    client_id: UUID,
    body: SourceProjectBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.set_source_project(client_id, body.project_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return _to_response(client)
