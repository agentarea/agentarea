"""ClientsToolset — register harnesses (codex, claude, ...) and wire their tools.

A client is an agent-proxy: it connects to ``/client-mcp/{id}`` and gets the
skills and MCP instances attached to it. Attaching is ``privileged`` rather than
plain ``write`` because it widens what an outside harness can reach.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema) but
the source of truth is ``ClientCreate``/``ClientUpdate`` in
``agentarea_mcp.schemas.client_dto``; the contract test in
``libs/agents/tests/test_mcp_rest_parity.py`` enforces parity.
"""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_mcp.schemas.client_dto import ClientCreate, ClientUpdate

from ..api.v1._access_control_grants import grant_resource_owner
from ..api.v1.clients import client_mcp_endpoint_url
from .base import platform_context, platform_read_context


def _build_service(repo_factory) -> ClientService:
    return ClientService(repo_factory.create_repository(ClientRepository))


def _refs(items) -> list[dict[str, str]]:
    return [{"id": str(i.id), "name": i.name} for i in items or []]


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
    description="Register harnesses as clients and attach skills/MCP instances to them.",
    category="platform",
    plane="federate",
)
class ClientsToolset(Toolset):
    """Manage registered clients: list, get, create, update, delete, and wire their tools."""

    @tool_method(effect="read")
    async def list(self, limit: int = 100, offset: int = 0) -> str:
        """List registered clients and their MCP endpoint URLs."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            clients = await service.list(limit=limit, offset=offset)
            return json.dumps([_summary(c) for c in clients], default=str)

    @tool_method(effect="read")
    async def get(self, client_id: str) -> str:
        """Get a client with the skills and MCP instances attached to it."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            client = await service.get(UUID(client_id))
            if not client:
                return json.dumps({"error": "Client not found"})
            return json.dumps(
                {
                    **_summary(client),
                    "description": client.description,
                    "skills": _refs(client.skills),
                    "mcp_instances": _refs(client.mcp_instances),
                },
                default=str,
            )

    @tool_method(effect="write")
    async def create(
        self,
        name: str,
        description: str | None = None,
        kind: str = "harness",
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
                user_id=user_ctx.user_id,
            )
            return json.dumps(_summary(client), default=str)

    @tool_method(effect="write")
    async def update(
        self,
        client_id: str,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
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
                return json.dumps({"error": "Client not found"})
            return json.dumps(_summary(client), default=str)

    @tool_method(effect="destructive")
    async def delete(self, client_id: str) -> str:
        """Delete a client. Its MCP endpoint stops answering."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete(UUID(client_id))
            return json.dumps({"deleted": deleted})

    @tool_method(effect="privileged")
    async def add_skill(self, client_id: str, skill_id: str) -> str:
        """Attach a skill to a client, widening what the harness can call."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_skill(UUID(client_id), UUID(skill_id))
            return json.dumps({"added": True})

    @tool_method(effect="privileged")
    async def remove_skill(self, client_id: str, skill_id: str) -> str:
        """Detach a skill from a client."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_skill(UUID(client_id), UUID(skill_id))
            return json.dumps({"removed": True})

    @tool_method(effect="privileged")
    async def add_mcp_instance(
        self,
        client_id: str,
        mcp_instance_id: str,
        namespace_prefix: str = "",
    ) -> str:
        """Attach an MCP instance to a client, optionally namespacing its tools."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_mcp_instance(
                UUID(client_id),
                UUID(mcp_instance_id),
                namespace_prefix or None,
            )
            return json.dumps({"added": True})

    @tool_method(effect="privileged")
    async def remove_mcp_instance(self, client_id: str, mcp_instance_id: str) -> str:
        """Detach an MCP instance from a client."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_mcp_instance(UUID(client_id), UUID(mcp_instance_id))
            return json.dumps({"removed": True})
