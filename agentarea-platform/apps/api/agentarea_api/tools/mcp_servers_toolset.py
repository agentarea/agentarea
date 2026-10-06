"""MCPServersToolset — manage MCP server specs and instances.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTOs in
``agentarea_mcp.schemas.dto`` (``MCPServerCreate``,
``MCPServerInstanceCreate``, plus their ``Update`` siblings). The contract
test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity between
toolset kwargs and DTO fields.
"""

import builtins
import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.mcp_server.elicitation import url_elicitation
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from fastapi import HTTPException
from mcp.types import InputRequiredResult

from ..api.v1.mcp_oauth_connect import connect_page_url
from .base import platform_context, platform_read_context


def _serialize_server(server: Any) -> dict:
    return {
        "id": str(server.id),
        "name": server.name,
        "description": server.description,
        "version": server.version,
        "tags": server.tags,
        "is_public": server.is_public,
        "remote_url": server.remote_url,
        "docker_image_url": server.docker_image_url,
        "status": server.status,
    }


def _serialize_instance(instance: Any) -> dict:
    return {
        "id": str(instance.id),
        "name": instance.name,
        "description": instance.description,
        "verification": instance.verification,
        "server_spec_id": instance.server_spec_id,
    }


def _tool_safety_hint(tool: dict[str, Any]) -> str | None:
    """A one-word safety marker from the tool's annotations, if the server set one.

    ``destructiveHint`` and ``readOnlyHint`` are the two annotations worth
    surfacing without reading the full description; destructive wins if a
    (malformed) tool somehow sets both, since that's the more cautious read.
    Rows stored before annotations were kept camelCase spell them snake_case
    until re-verified, so both spellings are read.
    """
    annotations = tool.get("annotations") or {}
    if annotations.get("destructiveHint") or annotations.get("destructive_hint"):
        return "destructive"
    if annotations.get("readOnlyHint") or annotations.get("read_only_hint"):
        return "read-only"
    return None


def _serialize_tool_name(tool: dict[str, Any]) -> str:
    """The compact default list entry: the tool's name, nothing else.

    Even full descriptions and annotation dicts are too much at scale — a
    server like Instantly has 199 tools, and {"name": ..., "description": ...}
    per entry still ran ~69k chars. A plain string per tool (optionally suffixed
    with a safety marker) has no per-entry JSON-key overhead, so it's the most
    compact shape that still lets an agent see every tool name and its safety
    class at a glance. Full descriptions are available on demand via the
    ``tools`` parameter.
    """
    name = tool.get("name", "")
    hint = _tool_safety_hint(tool)
    return f"{name} ({hint})" if hint else name


def _serialize_tool_detail(tool: dict[str, Any]) -> dict[str, Any]:
    """A tool's name, description and annotations — never ``inputSchema``.

    Used by ``get(tools=[...])`` to answer "what does this tool do" for the
    handful of names an agent picked out of the compact default list.
    """
    detail = {"name": tool.get("name"), "description": tool.get("description", "")}
    annotations = tool.get("annotations")
    if annotations:
        detail["annotations"] = annotations
    return detail


async def _connect_action(
    service: Any, user_ctx: UserContext, instance: Any, *, probe: bool
) -> dict[str, str] | None:
    """The link a person opens to connect *instance*, while it waits on a credential."""
    if not await service.needs_connecting(instance, probe=probe):
        return None
    slug = user_ctx.workspace_slug or await workspace_slug_for(user_ctx.workspace_id)
    url = connect_page_url(slug, str(instance.id))
    return {
        "type": "connect",
        "url": url,
        "message": f"Open this link to connect {instance.name}: {url}",
    }


@toolset(
    namespace="agentarea/mcp_servers",
    display_name="MCP Server Management",
    description="Start, stop, and manage MCP server instances.",
    category="platform",
    plane="build",
)
class MCPServersToolset(Toolset):
    """Manage MCP server specs (templates) and instances."""

    @property
    def name(self) -> str:
        return "mcp_servers"

    # ------------------------------------------------------------------
    # Specs (catalog templates)
    # ------------------------------------------------------------------

    @tool_method(effect="write")
    @unrestricted("any member may add a spec, as POST /v1/mcp-servers allows")
    async def create_spec(
        self,
        name: str,
        description: str,
        docker_image_url: str | None = None,
        remote_url: str | None = None,
        version: str = "1.0.0",
        tags: list[str] | None = None,
        is_public: bool = False,
        env_schema_json: str = "",
        cmd_json: str = "",
        json_spec_json: str = "",
        registry_url: str | None = None,
    ) -> str:
        """Create a new MCP server spec (catalog template).

        Args:
            name: Human-readable spec name (unique per workspace).
            description: Short summary of what this MCP server provides.
            docker_image_url: Docker image URL for container-based servers.
            remote_url: Remote endpoint URL for HTTP-based servers.
            version: Semantic version string (default ``1.0.0``).
            tags: Tags used for search and categorization.
            is_public: If true, the spec is visible across workspaces.
            env_schema_json: JSON-encoded array of env-var schema entries
                (KeyValueInput; mark secrets with ``isSecret: true``).
            cmd_json: JSON-encoded array overriding the container CMD.
            json_spec_json: JSON-encoded raw ServerJSON spec from the registry.
            registry_url: Source registry URL the spec was imported from.
        """
        env_schema = json.loads(env_schema_json) if env_schema_json else None
        cmd = json.loads(cmd_json) if cmd_json else None
        json_spec = json.loads(json_spec_json) if json_spec_json else None

        payload = MCPServerCreate(
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            remote_url=remote_url,
            version=version,
            tags=tags or [],
            is_public=is_public,
            env_schema=env_schema,
            cmd=cmd,
            json_spec=json_spec,
            registry_url=registry_url,
        )

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            server = await service.create_mcp_server(payload)
            return json.dumps(_serialize_server(server), default=str)

    @tool_method(effect="write")
    @requires("edit", "mcp_server", id_param="spec_id")
    async def update_spec(
        self,
        spec_id: str,
        name: str | None = None,
        description: str | None = None,
        docker_image_url: str | None = None,
        remote_url: str | None = None,
        version: str | None = None,
        tags: list[str] | None = None,
        is_public: bool | None = None,
        status: str | None = None,
        env_schema_json: str = "",
        cmd_json: str = "",
        json_spec_json: str = "",
        registry_url: str | None = None,
    ) -> str:
        """Update fields on an existing MCP server spec. Only fields explicitly
        set are written; pass ``None`` to leave a field untouched.
        """
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if docker_image_url is not None:
            patch["docker_image_url"] = docker_image_url
        if remote_url is not None:
            patch["remote_url"] = remote_url
        if version is not None:
            patch["version"] = version
        if tags is not None:
            patch["tags"] = tags
        if is_public is not None:
            patch["is_public"] = is_public
        if status is not None:
            patch["status"] = status
        if env_schema_json:
            patch["env_schema"] = json.loads(env_schema_json)
        if cmd_json:
            patch["cmd"] = json.loads(cmd_json)
        if json_spec_json:
            patch["json_spec"] = json.loads(json_spec_json)
        if registry_url is not None:
            patch["registry_url"] = registry_url

        if not patch:
            return json.dumps({"error": "no fields to update"})

        payload = MCPServerUpdate.model_validate(patch)

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            server = await service.update_mcp_server(UUID(spec_id), payload)
            if not server:
                return json.dumps({"error": "MCP server spec not found"})
            return json.dumps(_serialize_server(server), default=str)

    @tool_method(effect="read")
    @enforced_in_handler(
        "tenant specs are narrowed to what the graph says is readable; the catalog is not"
    )
    async def list_specs(
        self,
        is_public: bool = False,
        tag: str = "",
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """List MCP server specs (templates) available in the workspace.

        ``limit`` is 1..100; page further with ``offset``.
        """
        if not 1 <= limit <= 100:
            return json.dumps({"error": f"limit must be between 1 and 100, got {limit}"})
        if offset < 0:
            return json.dumps({"error": f"offset must not be negative, got {offset}"})
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            servers, total = await service.list_servers(
                is_public=is_public if is_public else None,
                tag=tag or None,
                search=search or None,
                limit=limit,
                offset=offset,
                ids=await readable_resource_ids(user_ctx.user_id),
            )
            return json.dumps(
                {
                    "items": [_serialize_server(s) for s in servers],
                    "total": total,
                },
                default=str,
            )

    @tool_method(effect="read")
    @enforced_in_handler("the PDP decides for a tenant spec; a catalog projection is platform data")
    async def get_spec(self, spec_id: str) -> str:
        """Get an MCP server spec (template) by ID."""
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            server = await service.get(UUID(spec_id))
            if not server:
                return json.dumps({"error": "MCP server spec not found"})
            if not getattr(server, "is_catalog", False):
                try:
                    await require_permission("read", "mcp_server", spec_id, user_ctx.user_id)
                except HTTPException as exc:
                    return json.dumps({"error": exc.detail})
            payload = _serialize_server(server)
            payload["env_schema"] = server.env_schema
            payload["registry_url"] = server.registry_url
            return json.dumps(payload, default=str)

    @tool_method(effect="destructive")
    @requires("delete", "mcp_server", id_param="spec_id")
    async def delete_spec(self, spec_id: str) -> str:
        """Delete an MCP server spec (template) by ID."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            deleted = await service.delete_mcp_server(UUID(spec_id))
            return json.dumps({"deleted": deleted})

    # ------------------------------------------------------------------
    # Instances (configured deployments of a spec)
    # ------------------------------------------------------------------

    @tool_method(effect="write")
    @unrestricted("any member may add an instance, as POST /v1/mcp-server-instances allows")
    async def create(
        self,
        name: str,
        json_spec_json: str,
        server_spec_id: str,
        description: str | None = None,
        auth_config_id: str | None = None,
    ) -> str:
        """Create a new MCP server instance.

        Args:
            name: Display name for the instance (unique per workspace).
            json_spec_json: JSON-encoded instance configuration (environment,
                env_vars, headers). The transport comes from the server spec;
                transport keys such as ``type`` are ignored.
            description: Optional human-readable description.
            server_spec_id: ID of an existing MCP server spec.
            auth_config_id: Optional MCPAuthConfig UUID for OAuth/credentials.
        """
        try:
            spec_id = UUID(server_spec_id)
        except ValueError:
            return json.dumps({"error": f"server_spec_id must be a UUID, got {server_spec_id!r}"})
        spec = json.loads(json_spec_json) if json_spec_json else {}
        payload = MCPServerInstanceCreate(
            name=name,
            description=description,
            server_spec_id=spec_id,
            json_spec=spec,
            auth_config_id=auth_config_id,
        )

        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.create_instance(payload)
            if not instance:
                return json.dumps({"error": "Failed to create MCP server instance"})
            action = await _connect_action(service, user_ctx, instance, probe=True)
            result = _serialize_instance(instance)
            if action is not None:
                result["action_required"] = action
            return json.dumps(result, default=str)

    @tool_method(effect="write")
    @requires("edit", "mcp_instance", id_param="instance_id")
    async def update(
        self,
        instance_id: str,
        name: str | None = None,
        description: str | None = None,
        json_spec_json: str = "",
    ) -> str:
        """Update fields on an existing MCP server instance."""
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if json_spec_json:
            patch["json_spec"] = json.loads(json_spec_json)

        if not patch:
            return json.dumps({"error": "no fields to update"})

        payload = MCPServerInstanceUpdate.model_validate(patch)

        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.update_instance(UUID(instance_id), payload)
            if not instance:
                return json.dumps({"error": "MCP server instance not found"})
            action = await _connect_action(service, user_ctx, instance, probe=True)
            result = _serialize_instance(instance)
            if action is not None:
                result["action_required"] = action
            return json.dumps(result, default=str)

    @tool_method(effect="read")
    @unrestricted("instances in the caller's workspace, as the REST listing returns them")
    async def list(self) -> str:
        """List all MCP server instances in the workspace."""
        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instances = await service.list()
            return json.dumps(
                [_serialize_instance(i) for i in instances],
                default=str,
            )

    @tool_method(effect="read")
    @unrestricted("an instance in the caller's workspace, as the REST detail returns it")
    async def get(
        self, instance_id: str, tools: builtins.list[str] | None = None
    ) -> str | InputRequiredResult:
        """Get details of an MCP server instance.

        Args:
            instance_id: ID of the MCP server instance.
            tools: Tool names to look up full details for (description and
                annotations, without ``inputSchema``). Pass names exactly as
                they appear in this call's own ``tools`` summary list — strip
                any trailing ``" (read-only)"``/``" (destructive)"`` marker
                first. Names that don't match any tool are reported under
                ``unknown_tools`` instead of raising.
        """
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.get(UUID(instance_id))
            if not instance:
                return json.dumps({"error": "MCP server instance not found"})
            payload = _serialize_instance(instance)
            payload["last_dispatch"] = instance.last_dispatch
            raw_tools = instance.tools or []
            payload["tools"] = [_serialize_tool_name(t) for t in raw_tools]
            payload["tool_count"] = len(raw_tools)
            if tools is not None:
                by_name = {t.get("name"): t for t in raw_tools if t.get("name")}
                details = []
                unknown = []
                for requested in tools:
                    found = by_name.get(requested)
                    if found is None:
                        unknown.append(requested)
                    else:
                        details.append(_serialize_tool_detail(found))
                payload["tool_details"] = details
                if unknown:
                    payload["unknown_tools"] = unknown
            action = await _connect_action(service, user_ctx, instance, probe=False)
            if action is not None:
                elicitation = url_elicitation(action["url"], action["message"])
                if elicitation is not None:
                    return elicitation
                payload["action_required"] = action
            return json.dumps(payload, default=str)

    @tool_method(effect="destructive")
    @requires("delete", "mcp_instance", id_param="instance_id")
    async def delete_instance(self, instance_id: str) -> str:
        """Delete an MCP server instance."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            deleted = await service.delete_instance(UUID(instance_id))
            return json.dumps({"deleted": deleted})

    @tool_method(effect="write")
    @requires("edit", "mcp_instance", id_param="instance_id")
    async def verify(self, instance_id: str) -> str | InputRequiredResult:
        """Run end-to-end verification on an MCP server instance.

        Provisions (if needed), waits for readiness, and lists tools.
        Returns the fresh verification payload.
        """
        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            result = await service.verify_instance(UUID(instance_id))
            instance = await service.get(UUID(instance_id))
            if instance is not None:
                # verify() records the outcome in its own session; read it back.
                await session.refresh(instance, attribute_names=["verification"])
                action = await _connect_action(service, user_ctx, instance, probe=True)
                if action is not None:
                    elicitation = url_elicitation(action["url"], action["message"])
                    if elicitation is not None:
                        return elicitation
                    # The probe may have recorded a sharper verdict than verify's.
                    result = {**instance.verification, "action_required": action}
            return json.dumps(result, default=str)
