import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.base.service import BaseCrudService
from agentarea_common.config import get_database
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_mcp.domain.events import (
    MCPServerCreated,
    MCPServerDeleted,
    MCPServerDeployed,
    MCPServerInstanceCreated,
    MCPServerInstanceDeleted,
    MCPServerInstanceUpdated,
    MCPServerUpdated,
)
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import (
    DEFAULT_VERIFICATION,
    VERIFICATION_SCHEMA_VERSION,
)
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_mcp.verification import verify

from .mcp_env_service import MCPEnvironmentService
from .oauth_client_service import MCPOAuthClientService
from .validation_service import MCPConfigurationValidator, MCPValidationError

logger = logging.getLogger(__name__)

# Sentinel value for masked secrets — must match across backend and frontend
SECRET_MASKED_VALUE = "*" * 6


def _normalize_url_keys(spec: dict[str, Any]) -> dict[str, Any]:
    """Canonical key for URL-type instances is `endpoint_url`.

    Historically some callers (and the validation layer) accepted `url` or the
    legacy `external_url`. Normalize on the way in so downstream code only has
    to read one key.
    """
    if spec.get("type") != "url":
        return spec
    if spec.get("endpoint_url"):
        return spec
    for legacy in ("url", "external_url"):
        value = spec.get(legacy)
        if isinstance(value, str) and value.strip():
            spec = {**spec, "endpoint_url": value}
            spec.pop(legacy, None)
            break
    return spec


def derive_bundle_verification(bundle: MCPServerInstance, members: list[MCPServerInstance]) -> dict:
    """Derive a bundle's verification from its members' current verification state."""
    json_spec = bundle.json_spec or {}
    member_ids: list[str] = json_spec.get("members", [])

    if not member_ids:
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "status": "failed",
            "at": datetime.now(UTC).isoformat(),
            "error": {
                "code": "bundle_empty",
                "message": "Bundle has no members.",
                "detail": None,
            },
        }

    member_map = {str(m.id): m for m in members}

    not_ready = []
    missing = []
    for mid in member_ids:
        if mid not in member_map:
            missing.append(mid)
            continue
        m = member_map[mid]
        v = m.verification or {}
        if v.get("status") != "succeeded":
            not_ready.append(m.name)

    if missing:
        names = ", ".join(missing)
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "status": "failed",
            "at": datetime.now(UTC).isoformat(),
            "error": {
                "code": "bundle_member_missing",
                "message": f"Bundle member(s) not found: [{names}]. They may have been deleted.",
                "detail": None,
            },
        }

    if not_ready:
        names = ", ".join(not_ready)
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "status": "failed",
            "at": datetime.now(UTC).isoformat(),
            "error": {
                "code": "bundle_member_not_ready",
                "message": f"Bundle members not ready: [{names}].",
                "detail": None,
            },
        }

    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": "succeeded",
        "at": datetime.now(UTC).isoformat(),
        "error": None,
    }


class MCPServerService(BaseCrudService[MCPServer]):
    def __init__(self, repository_factory: Any, event_broker: EventBroker | None = None):
        repository = repository_factory.create_repository(MCPServerRepository)
        super().__init__(repository)
        self.repository_factory = repository_factory
        self.event_broker = event_broker

    @audited("mcp_server.create", resource_type="mcp_server")
    async def create_mcp_server(
        self,
        name: str,
        description: str,
        docker_image_url: str | None = None,
        version: str = "1.0.0",
        tags: list[str] | None = None,
        is_public: bool = False,
        env_schema: list[dict[str, Any]] | None = None,
        cmd: list[str] | None = None,
        json_spec: dict[str, Any] | None = None,
        remote_url: str | None = None,
        registry_url: str | None = None,
    ) -> MCPServer:
        server = MCPServer(
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            version=version,
            tags=tags or [],
            is_public=is_public,
            env_schema=env_schema or [],
            cmd=cmd,
            remote_url=remote_url,
            json_spec=json_spec,
            registry_url=registry_url,
        )
        server = await self.create(server)

        if self.event_broker:
            await self.event_broker.publish(
                MCPServerCreated(server_id=server.id, name=server.name, version=server.version)
            )

        return server

    @audited("mcp_server.update", resource_type="mcp_server", resource_id_param="id")
    async def update_mcp_server(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        docker_image_url: str | None = None,
        version: str | None = None,
        tags: list[str] | None = None,
        is_public: bool | None = None,
        status: str | None = None,
        env_schema: list[dict[str, Any]] | None = None,
        cmd: list[str] | None = None,
        json_spec: dict[str, Any] | None = None,
    ) -> MCPServer | None:
        server = await self.get(id)
        if not server:
            return None

        if name is not None:
            server.name = name
        if description is not None:
            server.description = description
        if docker_image_url is not None:
            server.docker_image_url = docker_image_url
        if version is not None:
            server.version = version
        if tags is not None:
            server.tags = tags
        if is_public is not None:
            server.is_public = is_public
        if status is not None:
            server.status = status
        if env_schema is not None:
            server.env_schema = env_schema
        if cmd is not None:
            server.cmd = cmd

        server = await self.update(server)

        if self.event_broker:
            await self.event_broker.publish(
                MCPServerUpdated(server_id=server.id, name=server.name, version=server.version)
            )

        return server

    @audited("mcp_server.delete", resource_type="mcp_server", resource_id_param="id")
    async def delete_mcp_server(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success and self.event_broker:
            await self.event_broker.publish(MCPServerDeleted(server_id=id))
        return success

    async def deploy_server(self, id: UUID) -> bool:
        server = await self.get(id)
        if not server:
            return False

        server.status = "deployed"
        await self.update(server)

        if self.event_broker:
            await self.event_broker.publish(
                MCPServerDeployed(server_id=server.id, name=server.name, version=server.version)
            )

        return True

    async def list_servers(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        tag: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MCPServer], int]:
        return await self.repository.list_servers(
            status=status, is_public=is_public, tag=tag, search=search, limit=limit, offset=offset
        )

    async def get(self, id: UUID) -> MCPServer | None:
        return await self.repository.get_by_id(id)


class MCPServerInstanceService:
    def __init__(
        self,
        repository_factory: Any,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        self.repository = repository_factory.create_repository(MCPServerInstanceRepository)
        self.mcp_server_repository = repository_factory.create_repository(MCPServerRepository)

        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self.secret_manager = secret_manager
        self.env_service = MCPEnvironmentService(secret_manager)
        self.db = get_database()

    def _get_secret_env_names(self, env_schema: list[dict[str, Any]]) -> set[str]:
        return {e["name"] for e in env_schema if isinstance(e, dict) and e.get("isSecret")}

    async def _extract_secrets_from_spec(
        self,
        spec: dict[str, Any],
        server_spec_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        secret_env_vars: dict[str, str] = {}

        if not server_spec_id:
            return spec, secret_env_vars

        server_spec = await self.mcp_server_repository.get_by_id(server_spec_id)
        if not server_spec:
            return spec, secret_env_vars

        env_schema = server_spec.env_schema or []
        secret_names = self._get_secret_env_names(env_schema)
        if not secret_names:
            return spec, secret_env_vars

        spec = dict(spec)

        environment = spec.get("environment")
        if isinstance(environment, dict):
            clean_env = {}
            for key, value in environment.items():
                if key in secret_names:
                    secret_env_vars[key] = value
                else:
                    clean_env[key] = value
            spec["environment"] = clean_env

        headers = spec.get("headers")
        if isinstance(headers, dict):
            clean_headers = {}
            for key, value in headers.items():
                if key in secret_names:
                    secret_env_vars[key] = value
                else:
                    clean_headers[key] = value
            spec["headers"] = clean_headers

        if secret_env_vars:
            existing_env_vars = spec.get("env_vars", [])
            all_env_var_names = list(set(existing_env_vars) | set(secret_env_vars.keys()))
            spec["env_vars"] = all_env_var_names

        return spec, secret_env_vars

    @audited("mcp_instance.create", resource_type="mcp_instance")
    async def create_instance(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
        auth_config_id: str | None = None,
    ) -> MCPServerInstance | None:
        spec = _normalize_url_keys(json_spec or {})

        if not server_spec_id:
            validation_errors = MCPConfigurationValidator.validate_json_spec(spec)
            if validation_errors:
                raise MCPValidationError(validation_errors)

        spec, secret_env_vars = await self._extract_secrets_from_spec(spec, server_spec_id)

        instance_type = spec.get("type", "docker")
        is_url_type = instance_type == "url"
        is_bundle_type = instance_type == "bundle"

        create_kwargs: dict[str, Any] = {
            "name": name,
            "description": description,
            "server_spec_id": server_spec_id,
            "json_spec": spec,
            "verification": dict(DEFAULT_VERIFICATION),
        }
        if auth_config_id:
            create_kwargs["auth_config_id"] = auth_config_id

        instance = await self.repository.create(**create_kwargs)

        if secret_env_vars:
            try:
                await self.env_service.set_instance_environment(instance.id, secret_env_vars)
                logger.info(
                    "Stored %d secret env vars for instance %s",
                    len(secret_env_vars),
                    instance.id,
                )
            except Exception:
                logger.error(
                    "Failed to store secrets for instance %s",
                    instance.id,
                    exc_info=True,
                )
                raise

        if is_url_type:
            # Synchronous verify — blocks until succeeded or failed
            verification = await verify(instance)
            instance.verification = dict(verification)

        elif is_bundle_type:
            # Validate all members are succeeded before persisting the bundle
            member_ids: list[str] = spec.get("members", [])
            if not member_ids:
                try:
                    await self.repository.delete(instance.id)
                except Exception:
                    logger.error(
                        "Failed to clean up bundle instance %s after empty members",
                        instance.id,
                        exc_info=True,
                    )
                raise ValueError("Cannot create bundle: no members specified.")

            not_ready = []
            for mid in member_ids:
                try:
                    member = await self.repository.get_by_id(UUID(mid))
                except Exception:
                    member = None
                if not member:
                    not_ready.append(f"id={mid} (not found)")
                    continue
                v = member.verification or {}
                if v.get("status") != "succeeded":
                    not_ready.append(f"name={member.name}, status={v.get('status', 'unknown')}")

            if not_ready:
                try:
                    await self.repository.delete(instance.id)
                except Exception:
                    logger.error(
                        "Failed to clean up bundle instance %s after validation failure",
                        instance.id,
                        exc_info=True,
                    )
                names = "; ".join(not_ready)
                raise ValueError(
                    f"Cannot create bundle: members are not ready: [{names}]. "
                    "Fix or recreate the failed members first."
                )

        else:
            # docker/command — fire background verify; monitor will also sweep.
            # Hold a strong reference so the GC doesn't drop the task mid-flight
            # (https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task).
            self._background_verify_tasks: set[asyncio.Task] = getattr(
                self, "_background_verify_tasks", set()
            )
            task = asyncio.create_task(verify(instance))
            self._background_verify_tasks.add(task)
            task.add_done_callback(self._background_verify_tasks.discard)

        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=str(instance.id),
                server_spec_id=server_spec_id,
                name=instance.name,
                json_spec=spec,
            )
        )

        return instance

    @audited("mcp_instance.update", resource_type="mcp_instance", resource_id_param="id")
    async def update_instance(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        json_spec: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> MCPServerInstance | None:
        update_kwargs: dict[str, Any] = {}
        if name is not None:
            update_kwargs["name"] = name
        if description is not None:
            update_kwargs["description"] = description

        if json_spec is not None:
            json_spec = _normalize_url_keys(json_spec)
            instance = await self.repository.get_by_id(id)
            if instance:
                cleaned_spec, secret_env_vars = await self._extract_secrets_from_spec(
                    json_spec, instance.server_spec_id
                )
                masked_placeholders = {SECRET_MASKED_VALUE, "\u2022" * 6}
                real_secrets = {
                    k: v for k, v in secret_env_vars.items() if v not in masked_placeholders
                }
                if real_secrets:
                    await self.env_service.set_instance_environment(id, real_secrets)
                    logger.info(
                        "Updated %d secret env vars for instance %s",
                        len(real_secrets),
                        id,
                    )
                update_kwargs["json_spec"] = cleaned_spec

        instance = await self.repository.update(id, **update_kwargs)
        if not instance:
            return None

        await self.event_broker.publish(
            MCPServerInstanceUpdated(
                instance_id=instance.id,
                server_spec_id=instance.server_spec_id,
                name=instance.name,
                status=None,
            )
        )

        return instance

    async def verify_instance(self, instance_id: UUID) -> dict:
        """Run verify() on an instance and return the fresh verification payload."""
        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance_type = (instance.json_spec or {}).get("type", "docker")
        if instance_type == "bundle":
            member_ids: list[str] = (instance.json_spec or {}).get("members", [])
            members = []
            for mid in member_ids:
                try:
                    m = await self.repository.get_by_id(UUID(mid))
                    if m:
                        members.append(m)
                except Exception as e:
                    logger.debug("bundle member %s lookup failed: %s", mid, e)
            return derive_bundle_verification(instance, members)

        payload = await verify(instance)
        return dict(payload)

    async def get_instance_environment(self, instance_id: UUID) -> dict[str, str]:
        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            return {}

        env_var_names = instance.get_configured_env_vars()
        if not env_var_names:
            return {}

        return await self.env_service.get_instance_environment(instance_id, env_var_names)

    @audited("mcp_instance.delete", resource_type="mcp_instance", resource_id_param="id")
    async def delete_instance(self, id: UUID) -> bool:
        instance = await self.repository.get_by_id(id)
        if not instance:
            return False

        await self.event_broker.publish(MCPServerInstanceDeleted(instance_id=instance.id))
        return await self.repository.delete(id)

    async def get(self, id: UUID) -> MCPServerInstance | None:
        return await self.repository.get_by_id(id)

    async def get_by_name(self, name: str) -> MCPServerInstance | None:
        instances = await self.repository.list_all()
        for instance in instances:
            if instance.name == name:
                return instance
        return None

    async def list(
        self,
        server_spec_id: str | None = None,
        status: str | None = None,
        creator_scoped: bool = False,
    ) -> list[MCPServerInstance]:
        filters: dict[str, Any] = {}
        if server_spec_id:
            filters["server_spec_id"] = server_spec_id

        return await self.repository.list_all(creator_scoped=creator_scoped, **filters)

    async def execute_tool(
        self,
        server_instance_id: UUID,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool on an MCP server instance.

        Handles url/docker/command types directly. For bundle instances,
        resolves the original member via tools metadata and dispatches to that member.

        Returns {"success": bool, "result": str, "error": str|None,
                 "tool_name": str, "server_instance_id": str}
        """
        from agentarea_execution.activities.agent_execution_activities import (
            _enqueue_last_dispatch,
        )

        def _fail(result_msg: str, error_msg: str) -> dict[str, Any]:
            _enqueue_last_dispatch(
                str(server_instance_id),
                {
                    "schema_version": VERIFICATION_SCHEMA_VERSION,
                    "status": "failed",
                    "at": datetime.now(UTC).isoformat(),
                    "error": error_msg,
                },
            )
            return {
                "success": False,
                "result": result_msg,
                "error": error_msg,
                "tool_name": tool_name,
                "server_instance_id": str(server_instance_id),
            }

        instance = await self.repository.get_by_id(server_instance_id)
        if not instance:
            return _fail(
                f"MCP server instance {server_instance_id} not found. It may have been deleted.",
                f"MCP server instance {server_instance_id} not found",
            )

        instance_type = (instance.json_spec or {}).get("type", "docker")

        # Bundle: resolve member and check before dispatching
        if instance_type == "bundle":
            tools = instance.tools or (instance.json_spec or {}).get("available_tools") or []
            matched = next((t for t in tools if t.get("name") == tool_name), None)
            if not matched:
                return _fail(
                    f"Bundle '{instance.name}' does not expose tool '{tool_name}'. "
                    "Try re-verifying the bundle to refresh the tool list.",
                    f"Tool '{tool_name}' not found in bundle '{instance.name}'",
                )

            member_instance_id = matched.get("member_instance_id")
            original_tool_name = matched.get("original_tool_name") or tool_name
            if not member_instance_id:
                return _fail(
                    f"Bundle entry for '{tool_name}' is missing member_instance_id. "
                    "Re-verify the bundle to rebuild the tool index.",
                    f"Bundle entry for '{tool_name}' is missing member_instance_id",
                )

            try:
                member = await self.repository.get_by_id(UUID(member_instance_id))
            except Exception:
                member = None

            if not member:
                return _fail(
                    f"Bundle member for tool '{tool_name}' (id={member_instance_id}) not found. "
                    "Recreate or re-verify the bundle.",
                    f"Bundle member {member_instance_id} not found",
                )

            member_v = member.verification or {}
            if member_v.get("status") != "succeeded":
                member_err = (member_v.get("error") or {}).get("message", "unknown error")
                return _fail(
                    f"Bundle member '{member.name}' is not available: {member_err}. "
                    "Recreate or re-verify the member.",
                    f"Bundle member '{member.name}' verification status: {member_v.get('status')}",
                )

            return await self.execute_tool(UUID(member_instance_id), original_tool_name, tool_args)

        # Non-bundle: check verification status
        verification = instance.verification or {}
        if verification.get("status") != "succeeded":
            reason = verification.get("status", "unknown")
            v_err = (verification.get("error") or {}).get("message", "")
            detail = f" ({v_err})" if v_err else ""
            return _fail(
                f"MCP '{instance.name}' is not available (status: {reason}{detail}). "
                "Re-verify the instance.",
                f"Instance {server_instance_id} verification status: {reason}",
            )

        try:
            mcp_url, headers = await self._resolve_mcp_url_and_headers(instance)
        except Exception as e:
            return _fail(
                f"MCP '{instance.name}' is not available (cannot resolve URL: {e}). "
                "Re-verify the instance.",
                str(e),
            )

        logger.info(
            "MCP tool call to %s: instance=%s tool=%s",
            mcp_url,
            server_instance_id,
            tool_name,
        )

        try:
            call_result = await self._call_tool_via_mcp(mcp_url, headers, tool_name, tool_args)
        except Exception as e:
            logger.error(
                "MCP tool call failed for %s (%s): %s",
                server_instance_id,
                tool_name,
                e,
                exc_info=True,
            )
            return _fail(
                f"MCP '{instance.name}' tool call failed: {e}. "
                "Re-verify the instance if this persists.",
                f"MCP tool call failed: {e}",
            )

        parts: list[str] = []
        for block in getattr(call_result, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                parts.append(getattr(block, "text", "") or "")
            elif block_type == "image":
                mime = getattr(block, "mimeType", "unknown")
                parts.append(f"<image mime={mime}>")
            elif block_type == "resource":
                resource = getattr(block, "resource", None)
                uri = getattr(resource, "uri", "unknown") if resource else "unknown"
                parts.append(f"<resource uri={uri}>")
            else:
                parts.append(str(block))

        result_str = "\n".join(parts)
        is_error = bool(getattr(call_result, "isError", False))

        if is_error:
            error_msg = result_str or "MCP tool returned error"
            return _fail(error_msg, error_msg)

        _enqueue_last_dispatch(
            str(server_instance_id),
            {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "status": "succeeded",
                "at": datetime.now(UTC).isoformat(),
                "error": None,
            },
        )
        return {
            "success": True,
            "result": result_str,
            "error": None,
            "tool_name": tool_name,
            "server_instance_id": str(server_instance_id),
        }

    async def _resolve_mcp_url_and_headers(
        self, instance: MCPServerInstance
    ) -> tuple[str, dict[str, str]]:
        mcp_url = instance.endpoint_url
        if not mcp_url:
            raise RuntimeError(
                f"Instance {instance.id} has no endpoint URL (missing url/external_url in json_spec)"
            )

        headers: dict[str, str] = {}
        custom_headers = (instance.json_spec or {}).get("headers")
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)

        if not headers and instance.auth_config_id:
            try:
                from agentarea_mcp.application.auth_service import MCPAuthService
                from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository

                auth_repo = MCPAuthConfigRepository(
                    self.repository.session, self.repository.user_context
                )
                auth_service = MCPAuthService(auth_repo, self.secret_manager)
                auth_config = await auth_service.get(instance.auth_config_id)
                if auth_config:
                    headers = await auth_service.get_auth_headers(auth_config)
            except Exception as e:
                logger.warning("Failed to resolve auth headers for instance %s: %s", instance.id, e)

        return mcp_url, headers

    async def _call_tool_via_mcp(
        self,
        mcp_url: str,
        headers: dict[str, str],
        tool_name: str,
        tool_args: dict[str, Any],
    ):
        from mcp import ClientSession

        try:
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                mcp_url, timeout=timedelta(seconds=30), headers=headers or None
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await session.call_tool(tool_name, tool_args)
        except Exception as e:
            logger.info("Streamable HTTP call failed for %s (%s), trying SSE fallback", mcp_url, e)

        from mcp.client.sse import sse_client

        sse_url = mcp_url.rstrip("/")
        if sse_url.endswith("/mcp"):
            sse_url = sse_url[:-4] + "/sse"
        elif not sse_url.endswith("/sse"):
            sse_url = sse_url + "/sse"

        async with sse_client(sse_url, timeout=30, headers=headers or None) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(tool_name, tool_args)

    async def _list_tools_via_mcp(self, mcp_url: str, headers: dict[str, str]):
        from mcp import ClientSession

        try:
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                mcp_url, timeout=timedelta(seconds=10), headers=headers or None
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await session.list_tools()
        except Exception as e:
            logger.info("Streamable HTTP failed for %s (%s), trying SSE fallback", mcp_url, e)

        from mcp.client.sse import sse_client

        sse_url = mcp_url.rstrip("/")
        if sse_url.endswith("/mcp"):
            sse_url = sse_url[:-4] + "/sse"
        elif not sse_url.endswith("/sse"):
            sse_url = sse_url + "/sse"

        async with sse_client(sse_url, timeout=10, headers=headers or None) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.list_tools()

    async def validate_connection(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if not url:
            return {"valid": False, "errors": ["URL is required"]}

        try:
            result = await self._list_tools_via_mcp(url, headers or {})
            tools = [{"name": t.name, "description": t.description or ""} for t in result.tools]
            return {
                "valid": True,
                "errors": [],
                "tool_count": len(tools),
                "tools": tools,
            }
        except Exception as e:
            all_msgs: list[str] = []
            if isinstance(e, ExceptionGroup):
                for sub in e.exceptions:
                    all_msgs.append(str(sub))
            all_msgs.append(str(e))
            combined = " ".join(all_msgs)

            if "401" in combined:
                return {
                    "valid": False,
                    "errors": ["Authentication failed — check your credentials"],
                }
            if "403" in combined:
                return {
                    "valid": False,
                    "errors": ["Access denied — insufficient permissions"],
                }
            logger.warning("validate_connection failed for %s: %s", url, e, exc_info=True)
            return {
                "valid": False,
                "errors": ["Connection failed. Verify the URL, headers, and server availability."],
            }

    async def probe_instance_auth(self, instance_id: UUID) -> dict[str, Any]:
        import httpx

        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            return {"status": "error", "message": "Instance not found"}

        instance_type = (instance.json_spec or {}).get("type", "docker")
        if instance_type != "url":
            return {"status": "error", "message": "Probe is only supported for URL-type instances"}

        mcp_url = instance.endpoint_url
        if not mcp_url:
            return {"status": "error", "message": "No endpoint URL configured"}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(mcp_url, follow_redirects=True)

                if resp.status_code in (200, 405):
                    return {"status": "ok", "methods": ["none"]}

                if resp.status_code == 401:
                    www_auth = resp.headers.get("www-authenticate", "")
                    has_oauth = (
                        "resource_metadata" in www_auth.lower() or "bearer" in www_auth.lower()
                    )

                    if has_oauth:
                        try:
                            oauth_service = MCPOAuthClientService()
                            await oauth_service.discover_auth_server(mcp_url)
                            return {
                                "status": "auth_required",
                                "methods": ["oauth", "credentials"],
                            }
                        except Exception:
                            logger.debug(
                                "OAuth discovery failed for %s, falling back to credentials",
                                mcp_url,
                            )

                    hints = []
                    if instance.server_spec_id:
                        try:
                            from agentarea_mcp.infrastructure.repository import MCPServerRepository

                            server_repo = MCPServerRepository(
                                self.repository.session, self.repository.user_context
                            )
                            spec = await server_repo.get_by_id(instance.server_spec_id)
                            if spec and spec.env_schema:
                                for env_var in spec.env_schema:
                                    if isinstance(env_var, dict) and env_var.get(
                                        "name", ""
                                    ).upper() in ("AUTHORIZATION", "API_KEY", "TOKEN"):
                                        hints.append(
                                            {
                                                "name": env_var.get("name", ""),
                                                "description": env_var.get("description", ""),
                                                "required": env_var.get("required", True),
                                            }
                                        )
                        except Exception:
                            logger.debug("Failed to load spec env_schema for hints", exc_info=True)

                    return {
                        "status": "auth_required",
                        "methods": ["credentials"],
                        "hints": hints,
                    }

                return {
                    "status": "error",
                    "message": f"Unexpected response: {resp.status_code}",
                }

        except httpx.ConnectError:
            return {"status": "error", "message": "Cannot connect to the configured endpoint"}
        except httpx.TimeoutException:
            return {"status": "error", "message": f"Connection to {mcp_url} timed out"}
        except Exception as e:
            logger.warning("Probe failed for instance %s: %s", instance_id, e, exc_info=True)
            return {"status": "error", "message": "Probe failed due to an internal error"}
