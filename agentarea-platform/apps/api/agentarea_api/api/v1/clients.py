"""Clients (agent-proxy) CRUD API endpoints."""

import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.mcp_server import UnknownToolsetError
from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
from agentarea_agents_sdk.tools.tool_definition import ToolEffect
from agentarea_api.platform_mcp import attachable_toolset, client_platform_server
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.auth.route_authz import (
    enforced_in_handler,
    requires,
    unrestricted,
)
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.pagination import MAX_OFFSET
from agentarea_common.config.app import get_app_settings
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.schemas.client_dto import ClientCreate, ClientUpdate
from fastapi import APIRouter, Depends, HTTPException, Query
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
    """Attach an instance, or replace how an attached one is served."""

    id: str
    namespace_prefix: str | None = None
    # The instance's tools the client serves; omitted or null serves all of them.
    allowed_tools: list[str] | None = None


class PlatformToolsetAssociationBody(BaseModel):
    """Attach a platform toolset, or replace the methods an attached one leaves out."""

    # Namespace (``agentarea/runs``) or name (``runs``), as listed by
    # GET /clients/platform-toolsets.
    name: str
    disabled_methods: list[str] | None = None


class ClientRef(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ClientMcpInstanceRef(ClientRef):
    namespace_prefix: str | None = None
    allowed_tools: list[str] | None = None


class ClientPlatformToolsetRef(BaseModel):
    name: str
    disabled_methods: list[str] | None = None


class ClientResponse(BaseModel):
    id: UUID
    workspace_id: str
    created_by: str
    name: str
    description: str | None
    kind: str
    skills: list[ClientRef] = []
    mcp_instances: list[ClientMcpInstanceRef] = []
    platform_toolsets: list[ClientPlatformToolsetRef] = []
    mcp_endpoint_url: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("skills", "mcp_instances", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        return v if v is not None else []


class PlatformToolsetMethod(BaseModel):
    name: str
    display_name: str
    description: str
    effect: ToolEffect | None = None


class PlatformToolsetResponse(BaseModel):
    """A platform toolset a client can carry."""

    name: str
    display_name: str
    description: str
    methods: list[PlatformToolsetMethod]


def client_mcp_endpoint_url(client_id: UUID) -> str:
    """URL a harness connects to. Shared with the clients toolset — one shape."""
    base = get_app_settings().API_BASE_URL.rstrip("/")
    return f"{base}/mcp/clients/{client_id}"


async def client_responses(service: ClientService, clients: list[Client]) -> list[ClientResponse]:
    """Responses for *clients*, with how each serves its instances and toolsets.

    Shared with the clients toolset, so both surfaces describe a client alike.
    """
    ids = [client.id for client in clients]
    links = await service.instance_links(ids)
    toolsets = await service.platform_toolsets(ids)
    responses = []
    for client in clients:
        response = ClientResponse.model_validate(client)
        response.mcp_endpoint_url = client_mcp_endpoint_url(client.id)
        client_links = links.get(str(client.id), {})
        for instance in response.mcp_instances:
            if link := client_links.get(str(instance.id)):
                instance.namespace_prefix = link.namespace_prefix
                instance.allowed_tools = link.allowed_tools
        response.platform_toolsets = [
            ClientPlatformToolsetRef(name=t.toolset, disabled_methods=t.disabled_methods)
            for t in toolsets.get(str(client.id), [])
        ]
        responses.append(response)
    return responses


async def _to_response(service: ClientService, client: Client) -> ClientResponse:
    return (await client_responses(service, [client]))[0]


def platform_toolset_catalog() -> list[PlatformToolsetResponse]:
    """The platform toolsets a client can carry, with their methods."""
    metadata = get_code_tools_metadata()
    catalog = []
    for toolset in client_platform_server().toolsets.values():
        meta = metadata.get(toolset.namespace, {})
        described = {m["name"]: m for m in meta.get("available_methods", [])}
        catalog.append(
            PlatformToolsetResponse(
                name=toolset.namespace,
                display_name=meta.get("display_name") or toolset.name,
                description=meta.get("description", ""),
                methods=[
                    PlatformToolsetMethod(
                        name=method,
                        display_name=described.get(method, {}).get("display_name") or method,
                        description=described.get(method, {}).get("description", ""),
                        effect=described.get(method, {}).get("effect"),
                    )
                    for method in sorted(toolset.tools)
                ],
            )
        )
    return catalog


@router.post(
    "/",
    response_model=ClientResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
    return await _to_response(service, client)


@router.get(
    "/platform-toolsets",
    response_model=list[PlatformToolsetResponse],
    dependencies=[unrestricted("the platform toolset catalogue is the same for every workspace")],
)
async def list_platform_toolsets(user_context: UserContextDep):
    """Platform toolsets a client can carry, with the methods each can leave out."""
    return platform_toolset_catalog()


@router.get(
    "/",
    response_model=list[ClientResponse],
    dependencies=[enforced_in_handler("narrowed to the rows the graph says this caller may read")],
)
async def list_clients(
    user_context: UserContextDep,
    service: ClientServiceDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
):
    clients = await service.list(
        limit=limit,
        offset=offset,
        ids=await readable_resource_ids(user_context.user_id),
    )
    return await client_responses(service, clients)


@router.get(
    "/{client_id}",
    response_model=ClientResponse,
    dependencies=[requires("read", "client", id_param="client_id")],
)
async def get_client(
    client_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return await _to_response(service, client)


@router.patch(
    "/{client_id}",
    response_model=ClientResponse,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def update_client(
    client_id: UUID,
    data: ClientUpdate,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    client = await service.update_client(client_id, data)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return await _to_response(service, client)


@router.delete(
    "/{client_id}",
    status_code=204,
    dependencies=[requires("delete", "client", id_param="client_id")],
)
async def delete_client(
    client_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    deleted = await service.delete(client_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Client not found")


@router.post(
    "/{client_id}/skills",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def add_skill_to_client(
    client_id: UUID,
    body: AssociationBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.add_skill(client_id, body.id)


@router.delete(
    "/{client_id}/skills/{skill_id}",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def remove_skill_from_client(
    client_id: UUID,
    skill_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.remove_skill(client_id, skill_id)


@router.post(
    "/{client_id}/mcp-instances",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def add_mcp_instance_to_client(
    client_id: UUID,
    body: McpInstanceAssociationBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.add_mcp_instance(client_id, body.id, body.namespace_prefix, body.allowed_tools)


@router.delete(
    "/{client_id}/mcp-instances/{mcp_instance_id}",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def remove_mcp_instance_from_client(
    client_id: UUID,
    mcp_instance_id: UUID,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    await service.remove_mcp_instance(client_id, mcp_instance_id)


@router.post(
    "/{client_id}/platform-toolsets",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def add_platform_toolset_to_client(
    client_id: UUID,
    body: PlatformToolsetAssociationBody,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    try:
        toolset = attachable_toolset(body.name, body.disabled_methods or ())
    except UnknownToolsetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await service.set_platform_toolset(client_id, toolset, body.disabled_methods)


@router.delete(
    "/{client_id}/platform-toolsets/{toolset:path}",
    status_code=204,
    dependencies=[requires("edit", "client", id_param="client_id")],
)
async def remove_platform_toolset_from_client(
    client_id: UUID,
    toolset: str,
    user_context: UserContextDep,
    service: ClientServiceDep,
):
    """Detach a toolset by the namespace the client lists it under."""
    await service.remove_platform_toolset(client_id, toolset)
