"""ClientsToolset — register harnesses (codex, claude, ...) and wire their tools.

A client is an agent-proxy: it connects to ``/mcp/clients/{id}`` and gets the
skills, MCP instances, OpenAPI connections, and platform toolsets attached to it. Attaching is
``privileged`` rather than plain ``write`` because it widens what an outside
harness can reach.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema) but
the source of truth is ``ClientCreate``/``ClientUpdate`` in
``agentarea_mcp.schemas.client_dto``; the contract test in
``libs/agents/tests/test_mcp_rest_parity.py`` enforces parity.
"""

import builtins
import json
from typing import Annotated
from uuid import UUID

from agentarea_agents_sdk.mcp_server import UnknownToolsetError
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.schemas.client_dto import ClientCreate, ClientUpdate
from pydantic import BaseModel, Field

from ..api.v1._access_control_grants import grant_resource_owner
from ..api.v1.clients import ClientResponse, client_mcp_endpoint_url, client_responses
from ..platform_mcp import attachable_toolset
from .base import platform_context, platform_read_context


def _build_service(repo_factory) -> ClientService:
    return ClientService(repo_factory.create_repository(ClientRepository))


ClientId = Annotated[
    str, Field(description="Client id (UUID), from `clients_list` or `clients_create`.")
]


class ClientSummary(BaseModel):
    id: str = Field(description="Client id (UUID).")
    name: str = Field(description="Client name.")
    kind: str = Field(description="Kind of client, e.g. `harness`.")
    mcp_endpoint_url: str = Field(description="MCP endpoint URL the harness connects to.")


class ClientDeleted(BaseModel):
    deleted: bool = Field(description="Whether a client was deleted.")


class ClientAttached(BaseModel):
    added: bool = Field(description="True once the item is attached to the client.")


class ClientToolsetAttached(BaseModel):
    added: str = Field(
        description="Namespace of the attached platform toolset, e.g. `agentarea/runs`."
    )


class ClientDetached(BaseModel):
    removed: bool = Field(description="True once the item is no longer attached to the client.")


def _summary(client) -> dict[str, str]:
    return {
        "id": str(client.id),
        "name": client.name,
        "kind": client.kind,
        "mcp_endpoint_url": client_mcp_endpoint_url(client.id),
    }


@toolset(
    namespace="agentarea/clients",
    display_name="Registered Clients",
    description=(
        "Register harnesses as clients and attach skills, MCP instances, OpenAPI "
        "connections, and platform toolsets to them."
    ),
    category="platform",
    plane="federate",
)
class ClientsToolset(Toolset):
    """Manage registered clients: list, get, create, update, delete, and wire their tools."""

    open_world = False

    @tool_method(display_name="List clients", effect="read", output=builtins.list[ClientSummary])
    @enforced_in_handler("narrowed to the rows the graph says this caller may read")
    async def list(
        self,
        limit: Annotated[int, Field(description="Maximum number of clients to return.")] = 100,
        offset: Annotated[int, Field(description="Number of clients to skip, for paging.")] = 0,
    ) -> str:
        """List registered clients and their MCP endpoint URLs."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            clients = await service.list(
                limit=limit,
                offset=offset,
                ids=await readable_resource_ids(user_ctx),
            )
            return json.dumps([_summary(c) for c in clients], default=str)

    @tool_method(display_name="Get client", effect="read", output=ClientResponse)
    @requires("read", "client", id_param="client_id")
    async def get(self, client_id: ClientId) -> str:
        """Get a client with the skills, connections, and platform toolsets attached to it."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            client = await service.get(UUID(client_id))
            if not client:
                raise ToolError("Client not found")
            (response,) = await client_responses(service, [client])
            return response.model_dump_json()

    @tool_method(display_name="Register client", effect="write", output=ClientSummary)
    @unrestricted("any member may register a client, as POST /v1/clients allows")
    async def create(
        self,
        name: Annotated[str, Field(description="Client name, 1-255 characters, e.g. `codex`.")],
        description: Annotated[
            str | None, Field(description="What the client is for, up to 1000 characters.")
        ] = None,
        kind: Annotated[
            str, Field(description="Kind of client, up to 32 characters; `harness` by default.")
        ] = "harness",
    ) -> str:
        """Register a client. Returns the MCP endpoint URL the harness connects to."""
        payload = ClientCreate(
            name=name,
            description=description,
            kind=kind,
        )
        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            client = await service.create_client(payload)
            await grant_resource_owner(
                resource_id=client.id,
                workspace_id=user_ctx.workspace_id,
                owner=user_ctx.graph_subject,
            )
            return json.dumps(_summary(client), default=str)

    @tool_method(
        display_name="Update client", effect="write", idempotent=True, output=ClientSummary
    )
    @requires("edit", "client", id_param="client_id")
    async def update(
        self,
        client_id: ClientId,
        name: Annotated[
            str | None, Field(description="New name, 1-255 characters; omit to keep it.")
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New description, up to 1000 characters; omit to keep it."),
        ] = None,
        kind: Annotated[
            str | None, Field(description="New kind, up to 32 characters; omit to keep it.")
        ] = None,
    ) -> str:
        """Update a client's fields. Only fields explicitly set are written."""
        patch: dict[str, object] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if kind is not None:
            patch["kind"] = kind
        payload = ClientUpdate.model_validate(patch)

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            client = await service.update_client(UUID(client_id), payload)
            if not client:
                raise ToolError("Client not found")
            return json.dumps(_summary(client), default=str)

    @tool_method(
        display_name="Delete client", effect="destructive", idempotent=True, output=ClientDeleted
    )
    @requires("delete", "client", id_param="client_id")
    async def delete(self, client_id: ClientId) -> str:
        """Delete a client. Its MCP endpoint stops answering."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete(UUID(client_id))
            return json.dumps({"deleted": deleted})

    @tool_method(
        display_name="Attach skill to client",
        effect="privileged",
        idempotent=True,
        output=ClientAttached,
    )
    @requires("edit", "client", id_param="client_id")
    async def add_skill(
        self,
        client_id: ClientId,
        skill_id: Annotated[str, Field(description="Skill id (UUID), from `skills_list`.")],
    ) -> str:
        """Attach a skill to a client, widening what the harness can call."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_skill(UUID(client_id), UUID(skill_id))
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach skill from client",
        effect="privileged",
        idempotent=True,
        output=ClientDetached,
    )
    @requires("edit", "client", id_param="client_id")
    async def remove_skill(
        self,
        client_id: ClientId,
        skill_id: Annotated[
            str, Field(description="Skill id (UUID), from the client's `skills` in `clients_get`.")
        ],
    ) -> str:
        """Detach a skill from a client."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_skill(UUID(client_id), UUID(skill_id))
            return json.dumps({"removed": True})

    @tool_method(
        display_name="Attach MCP instance to client",
        effect="privileged",
        idempotent=True,
        output=ClientAttached,
    )
    @requires("edit", "client", id_param="client_id")
    async def add_mcp_instance(
        self,
        client_id: ClientId,
        mcp_instance_id: Annotated[
            str, Field(description="MCP server instance id (UUID), from `mcp_servers_list`.")
        ],
        namespace_prefix: Annotated[
            str,
            Field(
                description=(
                    "Prefix put before the instance's tool names on the client's "
                    "endpoint; empty for none."
                )
            ),
        ] = "",
        allowed_tools: Annotated[
            builtins.list[str] | None,
            Field(
                description=(
                    "Names of the instance's tools the client serves, as "
                    "`mcp_servers_get` lists them; omit to serve all of them."
                )
            ),
        ] = None,
    ) -> str:
        """Attach an MCP instance to a client, optionally namespacing and narrowing its tools.

        ``allowed_tools`` names the instance's tools the client serves; omit it to
        serve all of them. Re-attaching replaces both settings.
        """
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_mcp_instance(
                UUID(client_id),
                UUID(mcp_instance_id),
                namespace_prefix or None,
                allowed_tools,
            )
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach MCP instance from client",
        effect="privileged",
        idempotent=True,
        output=ClientDetached,
    )
    @requires("edit", "client", id_param="client_id")
    async def remove_mcp_instance(
        self,
        client_id: ClientId,
        mcp_instance_id: Annotated[
            str,
            Field(
                description=(
                    "MCP server instance id (UUID), from the client's "
                    "`mcp_instances` in `clients_get`."
                )
            ),
        ],
    ) -> str:
        """Detach an MCP instance from a client."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_mcp_instance(UUID(client_id), UUID(mcp_instance_id))
            return json.dumps({"removed": True})

    @tool_method(
        display_name="Attach OpenAPI connection to client",
        effect="privileged",
        idempotent=True,
        output=ClientAttached,
    )
    @requires("edit", "client", id_param="client_id")
    async def add_openapi_connection(
        self,
        client_id: ClientId,
        openapi_connection_id: Annotated[
            str, Field(description="OpenAPI connection id (UUID), from `openapi_connections_list`.")
        ],
        namespace_prefix: Annotated[
            str,
            Field(
                description=(
                    "Prefix put before the connection's operation names on the "
                    "client's endpoint; empty for none."
                )
            ),
        ] = "",
        allowed_tools: Annotated[
            builtins.list[str] | None,
            Field(
                description=(
                    "Names of the connection's operations the client serves, as "
                    "`openapi_connections_get` lists its tools; omit to serve all of them."
                )
            ),
        ] = None,
    ) -> str:
        """Attach an OpenAPI connection to a client, optionally namespacing and narrowing it.

        The workspace's own connections and the platform's can be attached.
        ``allowed_tools`` names the operations the client serves; omit it to serve
        all of them. Re-attaching replaces both settings.
        """
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_openapi_connection(
                UUID(client_id),
                UUID(openapi_connection_id),
                namespace_prefix or None,
                allowed_tools,
            )
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach OpenAPI connection from client",
        effect="privileged",
        idempotent=True,
        output=ClientDetached,
    )
    @requires("edit", "client", id_param="client_id")
    async def remove_openapi_connection(
        self,
        client_id: ClientId,
        openapi_connection_id: Annotated[
            str,
            Field(
                description=(
                    "OpenAPI connection id (UUID), from the client's "
                    "`openapi_connections` in `clients_get`."
                )
            ),
        ],
    ) -> str:
        """Detach an OpenAPI connection from a client."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_openapi_connection(UUID(client_id), UUID(openapi_connection_id))
            return json.dumps({"removed": True})

    @tool_method(
        display_name="Attach platform toolset to client",
        effect="privileged",
        idempotent=True,
        output=ClientToolsetAttached,
    )
    @requires("edit", "client", id_param="client_id")
    async def add_platform_toolset(
        self,
        client_id: ClientId,
        toolset: Annotated[
            str,
            Field(
                description=(
                    "Platform toolset namespace (`agentarea/runs`) or name (`runs`), "
                    "as GET /v1/clients/platform-toolsets lists them."
                )
            ),
        ],
        disabled_methods: Annotated[
            builtins.list[str] | None,
            Field(
                description=(
                    "Method names of the toolset the client does not serve, e.g. "
                    "`delete`; omit to serve all of them."
                )
            ),
        ] = None,
    ) -> str:
        """Attach a platform toolset (e.g. ``agentarea/runs``) to a client.

        The client's endpoint then serves the toolset's tools, minus
        ``disabled_methods``, in the client's workspace. Re-attaching replaces
        ``disabled_methods``.
        """
        try:
            namespace = attachable_toolset(toolset, disabled_methods or ())
        except UnknownToolsetError as exc:
            raise ToolError(str(exc)) from exc
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.set_platform_toolset(UUID(client_id), namespace, disabled_methods)
            return json.dumps({"added": namespace})

    @tool_method(
        display_name="Detach platform toolset from client",
        effect="privileged",
        idempotent=True,
        output=ClientDetached,
    )
    @requires("edit", "client", id_param="client_id")
    async def remove_platform_toolset(
        self,
        client_id: ClientId,
        toolset: Annotated[
            str,
            Field(
                description=(
                    "Platform toolset namespace, e.g. `agentarea/runs`, as the "
                    "client's `platform_toolsets` in `clients_get` lists it."
                )
            ),
        ],
    ) -> str:
        """Detach a platform toolset from a client, by the namespace the client lists."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_platform_toolset(UUID(client_id), toolset)
            return json.dumps({"removed": True})
