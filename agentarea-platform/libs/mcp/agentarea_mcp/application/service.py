from __future__ import annotations

import asyncio
import inspect
import logging
import socket
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from agentarea_common.audit import audited
from agentarea_common.base.service import BaseCrudService
from agentarea_common.config import get_database, get_settings
from agentarea_common.events.broker import EventBroker
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    UnsafeUrlError,
    safe_async_client,
    validate_outbound_url,
)
from mcp import MCPError

from agentarea_mcp.application.auth_service import MCPAuthService, OAuthReauthRequiredError
from agentarea_mcp.application.mcp_client import (
    connected_mcp_client,
    mcp_verdict_key,
    pinned_client_factory,
    platform_client_factory,
    shared_era_verdict_store,
)
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
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from agentarea_mcp.tool_serialization import serialize_mcp_tool
from agentarea_mcp.verification import declared_remote_transport, verify

from .mcp_env_service import MCPEnvironmentService
from .oauth_client_service import MCPOAuthClientService
from .validation_service import MCPConfigurationValidator, MCPValidationError

logger = logging.getLogger(__name__)

# Sentinel value for masked secrets — must match across backend and frontend
SECRET_MASKED_VALUE = "*" * 6
INSTANCE_TRANSPORT_FIELDS = {"type", "endpoint_url", "image", "command", "args"}


def _normalize_url_keys(spec: dict[str, Any]) -> dict[str, Any]:
    """Canonical key for URL-type instances is `endpoint_url`.

    Callers (and the validation layer) also accept `url` and `external_url`.
    Normalize on the way in so downstream code only has to read one key.
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


def _server_transport_spec(server_spec: MCPServer) -> dict[str, Any]:
    spec = dict(server_spec.json_spec or {})
    if server_spec.remote_url:
        spec.setdefault("type", "url")
        spec.setdefault("endpoint_url", server_spec.remote_url)
    elif server_spec.cmd:
        spec.setdefault("type", "command")
        spec.setdefault("command", server_spec.cmd[0] if server_spec.cmd else "")
        if len(server_spec.cmd or []) > 1:
            spec.setdefault("args", list(server_spec.cmd[1:]))
    elif server_spec.docker_image_url:
        spec.setdefault("type", "docker")
        spec.setdefault("image", server_spec.docker_image_url)
    else:
        spec.setdefault("type", "docker")
    return _normalize_url_keys(spec)


def _is_mcp_protocol_error(exc: BaseException) -> bool:
    """True when the server answered in MCP, rather than the dial failing."""
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_mcp_protocol_error(inner) for inner in exc.exceptions)
    return isinstance(exc, MCPError)


def _endpoint_refusal(url: str | None) -> str | None:
    """Why a member-supplied MCP endpoint may not be stored, if it may not.

    A write-time check only: every dial of a URL-type endpoint goes through the
    pinned transport regardless. A name that does not resolve yet is let through
    for verification to report, since it reaches nothing.
    """
    if not url:
        return None
    try:
        validate_outbound_url(url, policy=OutboundPolicy.from_env())
    except UnsafeUrlError as exc:
        if isinstance(exc.__cause__, socket.gaierror):
            return None
        logger.warning("Refused MCP endpoint %s", url, exc_info=True)
        return "Endpoint URL is not an allowed address"
    return None


def _spec_endpoint_refusal(remote_url: str | None, json_spec: dict[str, Any] | None) -> str | None:
    spec = _normalize_url_keys(dict(json_spec or {}))
    return _endpoint_refusal(remote_url) or (
        _endpoint_refusal(spec.get("endpoint_url")) if spec.get("type") == "url" else None
    )


def _instance_owned_spec(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in spec.items() if key not in INSTANCE_TRANSPORT_FIELDS}


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

    async def _resolve_unique_slug(self, name: str) -> str:
        """Delegate to the repository (single source of truth for slug uniqueness)."""
        return await self.repository.resolve_unique_slug(name)

    async def get_by_slug(self, slug: str) -> MCPServer | None:
        """Get an MCP server spec by workspace-scoped slug."""
        return await self.repository.get_by_slug(slug)

    @audited("mcp_server.create", resource_type="mcp_server")
    async def create_mcp_server(self, payload: MCPServerCreate) -> MCPServer:
        refusal = _spec_endpoint_refusal(payload.remote_url, payload.json_spec)
        if refusal:
            raise BadRequestError(refusal)
        slug = await self._resolve_unique_slug(payload.name)

        server = MCPServer(
            name=payload.name,
            slug=slug,
            description=payload.description,
            docker_image_url=payload.docker_image_url,
            version=payload.version,
            tags=payload.tags or [],
            is_public=payload.is_public,
            env_schema=payload.env_schema or [],
            cmd=payload.cmd,
            remote_url=payload.remote_url,
            json_spec=payload.json_spec,
            registry_url=payload.registry_url,
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
        payload: MCPServerUpdate,
    ) -> MCPServer | None:
        server = await self.get(id)
        if not server:
            return None

        patch = payload.model_dump(exclude_unset=True)
        if "remote_url" in patch or "json_spec" in patch:
            refusal = _spec_endpoint_refusal(patch.get("remote_url"), patch.get("json_spec"))
            if refusal:
                raise BadRequestError(refusal)

        if "name" in patch:
            server.name = patch["name"]
        if "description" in patch:
            server.description = patch["description"]
        if "docker_image_url" in patch:
            server.docker_image_url = patch["docker_image_url"]
        if "remote_url" in patch:
            server.remote_url = patch["remote_url"]
        if "version" in patch:
            server.version = patch["version"]
        if "tags" in patch:
            server.tags = patch["tags"]
        if "is_public" in patch:
            server.is_public = patch["is_public"]
        if "status" in patch:
            server.status = patch["status"]
        if "env_schema" in patch:
            server.env_schema = patch["env_schema"]
        if "cmd" in patch:
            server.cmd = patch["cmd"]
        if "json_spec" in patch:
            server.json_spec = patch["json_spec"]
        if "registry_url" in patch:
            server.registry_url = patch["registry_url"]

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
        ids: set[str] | None = None,
        spec_ids: Collection[str] | None = None,
    ) -> tuple[list[MCPServer], int]:
        """List server specs, narrowed to ``ids`` when the caller has a readable set.

        ``spec_ids`` asks for exactly those specs, tenant or catalog.
        """
        return await self.repository.list_servers(
            status=status,
            is_public=is_public,
            tag=tag,
            search=search,
            limit=limit,
            offset=offset,
            ids=ids,
            spec_ids=spec_ids,
        )

    async def get(self, id: UUID) -> MCPServer | None:
        # Catalog-aware: built-in specs live only in the registry catalog
        # (ADR-003) and are not in mcp_servers. get_server_by_id falls back to
        # a read-only catalog projection so opening a catalog item resolves.
        return await self.repository.get_server_by_id(str(id))


class MCPServerInstanceService:
    def __init__(
        self,
        repository_factory: Any,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
        *,
        era_verdict_store=None,
    ):
        self.repository = repository_factory.create_repository(MCPServerInstanceRepository)
        self.mcp_server_repository = repository_factory.create_repository(MCPServerRepository)

        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self.secret_manager = secret_manager
        self.env_service = MCPEnvironmentService(secret_manager)
        self.db = get_database()
        self.era_verdict_store = (
            era_verdict_store if era_verdict_store is not None else shared_era_verdict_store()
        )

    def _get_secret_env_names(self, env_schema: list[dict[str, Any]]) -> set[str]:
        return {e["name"] for e in env_schema if isinstance(e, dict) and e.get("isSecret")}

    def _derive_env_schema_from_instance_spec(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Derive an env_schema when an instance is created without an explicit
        spec. There is no declared schema to read here, so we never guess a
        variable's sensitivity from its name — every field defaults to secret.
        The caller can mark a value as plain config explicitly via env_schema.
        """
        env_schema: list[dict[str, Any]] = []
        headers = spec.get("headers")
        if isinstance(headers, dict):
            for name in headers:
                env_schema.append(
                    {
                        "name": str(name),
                        "description": f"HTTP header {name}",
                        "isSecret": True,
                    }
                )
        environment = spec.get("environment")
        if isinstance(environment, dict):
            for name in environment:
                env_schema.append(
                    {
                        "name": str(name),
                        "description": f"Environment variable {name}",
                        "isSecret": True,
                    }
                )
        return env_schema

    async def _auto_create_spec_for_instance(
        self,
        payload: MCPServerInstanceCreate,
    ) -> MCPServer:
        spec = _normalize_url_keys(payload.json_spec or {})
        spec_type = spec.get("type", "docker")
        transport_spec = {
            key: value for key, value in spec.items() if key in INSTANCE_TRANSPORT_FIELDS
        }
        env_schema = self._derive_env_schema_from_instance_spec(spec)

        server = MCPServer(
            name=payload.name,
            slug=await self.mcp_server_repository.resolve_unique_slug(payload.name),
            description=payload.description or payload.name,
            docker_image_url=transport_spec.get("image") if spec_type == "docker" else None,
            remote_url=transport_spec.get("endpoint_url") if spec_type == "url" else None,
            version="1.0.0",
            tags=[],
            is_public=False,
            env_schema=env_schema,
            cmd=(
                [transport_spec["command"], *transport_spec.get("args", [])]
                if spec_type == "command" and transport_spec.get("command")
                else None
            ),
            json_spec=transport_spec,
        )
        server.created_by = self.repository.user_context.user_id
        server.workspace_id = self.repository.user_context.workspace_id
        self.repository.session.add(server)
        await self.repository.session.flush()
        return server

    async def _get_transport_spec_for_instance(self, instance: MCPServerInstance) -> dict[str, Any]:
        server_spec = await self.mcp_server_repository.get_server_by_id(instance.server_spec_id)
        if not server_spec:
            raise ValueError(f"MCP server spec {instance.server_spec_id} not found")
        return {**_server_transport_spec(server_spec), **(instance.json_spec or {})}

    def _endpoint_url_from_spec(self, instance: MCPServerInstance, spec: dict[str, Any]) -> str:
        instance_type = spec.get("type", "docker")
        if instance_type == "url":
            return spec.get("endpoint_url", "")
        if instance_type in ("docker", "command"):
            return get_settings().mcp.manager_gateway_url(instance.id)
        raise ValueError("bundle has no endpoint_url")

    async def _extract_secrets_from_spec(
        self,
        spec: dict[str, Any],
        server_spec_id: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        secret_env_vars: dict[str, str] = {}

        server_spec = await self.mcp_server_repository.get_server_by_id(server_spec_id)
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

    async def _materialize_workspace_spec_copy(self, source: MCPServer) -> MCPServer:
        """Copy-on-write a catalog/platform spec into the caller's workspace.

        Connecting a built-in catalog MCP must leave the tenant owning a real
        spec row (ADR-003 copy-on-write, like catalog agents). Only then is the
        connection visible in the workspace spec list (so its icon resolves),
        editable, and decoupled from the global platform mirror.
        """
        copy = MCPServer(
            name=source.name,
            slug=await self.mcp_server_repository.resolve_unique_slug(source.name),
            description=source.description or source.name,
            docker_image_url=source.docker_image_url,
            version=source.version or "1.0.0",
            tags=list(source.tags or []),
            is_public=False,
            env_schema=list(source.env_schema or []),
            cmd=source.cmd,
            remote_url=source.remote_url,
            registry_item_id=getattr(source, "registry_item_id", None),
            json_spec=source.json_spec,
            registry_url=getattr(source, "registry_url", None),
        )
        copy.created_by = self.repository.user_context.user_id
        copy.workspace_id = self.repository.user_context.workspace_id
        self.repository.session.add(copy)
        await self.repository.session.flush()
        return copy

    async def _assert_may_use_auth_config(self, auth_config_id: UUID | str) -> None:
        """Only the auth config's creator or a workspace admin may attach it.

        Attaching one lets this instance send its stored credential wherever
        the connection points, so workspace membership alone is not enough.
        """
        from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository

        auth_repo = MCPAuthConfigRepository(self.repository.session, self.repository.user_context)
        auth_service = MCPAuthService(auth_repo, self.secret_manager)
        config_id = auth_config_id if isinstance(auth_config_id, UUID) else UUID(auth_config_id)
        await auth_service.get_for_use(config_id)

    @audited("mcp_instance.create", resource_type="mcp_instance")
    async def create_instance(self, payload: MCPServerInstanceCreate) -> MCPServerInstance | None:
        name = payload.name
        description = payload.description
        server_spec_id = payload.server_spec_id
        auth_config_id = payload.auth_config_id

        submitted_spec = _normalize_url_keys(payload.json_spec or {})

        try:
            if server_spec_id:
                server_spec = await self.mcp_server_repository.get_server_by_id(server_spec_id)
                if not server_spec:
                    raise MCPValidationError([f"server_spec_id '{server_spec_id}' was not found"])
                # Copy-on-write: connecting a built-in catalog/platform spec (not
                # owned by this workspace) materializes a workspace copy so the
                # connection is visible, editable, and self-contained (ADR-003).
                if str(getattr(server_spec, "workspace_id", "") or "") != str(
                    self.repository.user_context.workspace_id
                ):
                    server_spec = await self._materialize_workspace_spec_copy(server_spec)
                server_spec_id = str(server_spec.id)
            else:
                server_spec = await self._auto_create_spec_for_instance(payload)
                server_spec_id = str(server_spec.id)

            transport_spec = _server_transport_spec(server_spec)
            validation_errors = MCPConfigurationValidator.validate_json_spec(transport_spec)
            if validation_errors:
                raise MCPValidationError(validation_errors)

            instance_type = transport_spec.get("type", "docker")
            if instance_type == "bundle":
                raise MCPValidationError(["bundle is not a valid MCP server instance type"])
            if instance_type == "url":
                refusal = _endpoint_refusal(transport_spec.get("endpoint_url"))
                if refusal:
                    raise MCPValidationError([refusal])

            instance_spec = _instance_owned_spec(submitted_spec)
            spec, secret_env_vars = await self._extract_secrets_from_spec(
                instance_spec, server_spec_id
            )
            # Persist the resolved transport type so the UI derives health/status
            # correctly (a missing type defaults to docker and mis-runs container
            # health checks against a url-type connection).
            spec.setdefault("type", instance_type)

            create_kwargs: dict[str, Any] = {
                "name": name,
                "description": description,
                "server_spec_id": server_spec_id,
                "json_spec": spec,
                "verification": dict(DEFAULT_VERIFICATION),
            }
            if auth_config_id:
                await self._assert_may_use_auth_config(auth_config_id)
                create_kwargs["auth_config_id"] = auth_config_id

            instance = MCPServerInstance(
                **create_kwargs,
                created_by=self.repository.user_context.user_id,
                workspace_id=self.repository.user_context.workspace_id,
            )
            self.repository.session.add(instance)
            await self.repository.session.commit()
            await self.repository.session.refresh(instance)
        except Exception:
            await self.repository.session.rollback()
            raise

        is_url_type = instance_type == "url"

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
            refresh_result = self.repository.session.refresh(instance)
            if inspect.isawaitable(refresh_result):
                await refresh_result

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

    async def create_instance_with_spec(
        self,
        server_payload: MCPServerCreate,
        instance_payload: MCPServerInstanceCreate,
    ) -> MCPServerInstance | None:
        # `slug` is NOT NULL; route through the repository's single slug resolver
        # so this path can't drift from the others (it previously omitted slug
        # entirely -> NotNullViolationError 500 on the UI "Add Server").
        slug = await self.mcp_server_repository.resolve_unique_slug(server_payload.name)
        server = MCPServer(
            name=server_payload.name,
            slug=slug,
            description=server_payload.description,
            docker_image_url=server_payload.docker_image_url,
            version=server_payload.version,
            tags=server_payload.tags or [],
            is_public=server_payload.is_public,
            env_schema=server_payload.env_schema or [],
            cmd=server_payload.cmd,
            remote_url=server_payload.remote_url,
            json_spec=server_payload.json_spec,
            registry_url=server_payload.registry_url,
            created_by=self.repository.user_context.user_id,
            workspace_id=self.repository.user_context.workspace_id,
        )
        self.repository.session.add(server)
        await self.repository.session.flush()

        payload = MCPServerInstanceCreate(
            name=instance_payload.name,
            description=instance_payload.description,
            server_spec_id=server.id,
            json_spec=instance_payload.json_spec,
            auth_config_id=instance_payload.auth_config_id,
        )
        return await self.create_instance(payload)

    @audited("mcp_instance.update", resource_type="mcp_instance", resource_id_param="id")
    async def update_instance(
        self,
        id: UUID,
        payload: MCPServerInstanceUpdate,
    ) -> MCPServerInstance | None:
        patch = payload.model_dump(exclude_unset=True)

        update_kwargs: dict[str, Any] = {}
        instance: MCPServerInstance | None = None
        if "name" in patch:
            update_kwargs["name"] = patch["name"]
        if "description" in patch:
            update_kwargs["description"] = patch["description"]

        if "json_spec" in patch and patch["json_spec"] is not None:
            json_spec = _normalize_url_keys(patch["json_spec"])
            instance = await self.repository.get_by_id(id)
            if instance:
                cleaned_spec, secret_env_vars = await self._extract_secrets_from_spec(
                    json_spec, instance.server_spec_id
                )
                # Transport belongs to the original connection and is immutable
                # through this DTO. Preserve it while replacing the editable
                # instance configuration; otherwise every legitimate PATCH drops
                # ``type`` (and URL endpoints) merely because callers are forbidden
                # from sending those fields back.
                for field in INSTANCE_TRANSPORT_FIELDS:
                    if field in (instance.json_spec or {}):
                        cleaned_spec.setdefault(field, instance.json_spec[field])
                masked_placeholders = {SECRET_MASKED_VALUE, "\u2022" * 6}
                real_secrets = {
                    k: v for k, v in secret_env_vars.items() if v not in masked_placeholders
                }
                runtime_config_changed = cleaned_spec != (instance.json_spec or {}) or bool(
                    real_secrets
                )
                if runtime_config_changed:
                    transport_spec = await self._get_transport_spec_for_instance(instance)
                    if transport_spec.get("type", "docker") in (
                        "docker",
                        "command",
                        "kubernetes",
                    ):
                        # A running MCP process cannot observe changed environment,
                        # command, or rotated secrets. Retire it before persisting
                        # the new desired state; the next demand then cold-starts
                        # from that state. If retirement fails, no configuration or
                        # secret mutation has happened and the old runtime remains
                        # an honest representation of the stored configuration.
                        await self._retire_runtime_before_mutation(instance.id)
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
                status=(instance.verification or {}).get("status", "pending"),
            )
        )

        return instance

    async def verify_instance(self, instance_id: UUID) -> dict:
        """Run verify() on an instance and return the fresh verification payload."""
        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        transport_spec = await self._get_transport_spec_for_instance(instance)
        instance_type = transport_spec.get("type", "docker")
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

        try:
            extra_headers = await self._resolve_auth_headers(instance)
        except OAuthReauthRequiredError:
            return await self._store_reauth_required(instance.id)

        # User-initiated (Verify / Refresh Tools) → force a re-run so a stale
        # in_progress from an interrupted verify can't wedge the row in "verifying".
        payload = await verify(instance, extra_headers=extra_headers or None, force=True)

        # Reactive re-auth: the upstream rejected our token (401/403) and this
        # instance has an OAuth config → force one refresh and retry once. If the
        # session can't be renewed, surface an actionable "reconnect" state
        # instead of the raw 401/403.
        if instance.auth_config_id and self._is_auth_error_payload(payload):
            try:
                extra_headers = await self._resolve_auth_headers(instance, force_refresh=True)
            except OAuthReauthRequiredError:
                return await self._store_reauth_required(instance.id)
            payload = await verify(instance, extra_headers=extra_headers or None, force=True)

        return dict(payload)

    @staticmethod
    def _is_auth_error_payload(payload: Any) -> bool:
        """True when a verification failure looks like an upstream 401/403.

        The verification payload is a plain (TypedDict) mapping.
        """
        if not isinstance(payload, dict) or payload.get("status") != "failed":
            return False
        error = payload.get("error") or {}
        message = (error.get("message") if isinstance(error, dict) else "") or ""
        return any(marker in message for marker in ("401", "403", "Unauthorized", "Forbidden"))

    async def _store_reauth_required(self, instance_id: UUID) -> dict:
        """Persist and return a verification payload asking the user to reconnect."""
        from agentarea_mcp.domain.verification_types import (
            VERIFICATION_SCHEMA_VERSION,
        )

        payload = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "status": "failed",
            "at": datetime.now(UTC).isoformat(),
            "error": {
                "code": "oauth_reauth_required",
                "message": "OAuth session expired or was revoked. Reconnect with OAuth.",
                "detail": None,
            },
        }
        try:
            await self.repository.update(instance_id, verification=payload)
        except Exception:
            logger.warning("Failed to persist reauth state for %s", instance_id, exc_info=True)
        return payload

    async def discover_and_store_tools(self, instance_id: UUID) -> dict:
        """Re-run verification (which lists tools and persists them) and return tools.

        Used by the post-OAuth tool discovery hook and the user-initiated
        "Refresh Tools" / "Discover Tools" action on the instance detail page.
        """
        verification_payload = await self.verify_instance(instance_id)
        instance = await self.repository.get_by_id(instance_id)
        if instance is not None:
            # verify() persists discovered tools in its own short-lived session.
            # get_by_id() may therefore return the already-loaded identity from
            # this service's session with its pre-verification tools collection.
            # Refresh only that column so this response reflects the discovery
            # which just completed, rather than requiring a second HTTP request.
            await self.repository.session.refresh(instance, attribute_names=["tools"])
        tools = (instance.tools if instance else None) or []
        return {"tools": tools, "verification": verification_payload}

    async def _resolve_auth_headers(
        self, instance: MCPServerInstance, *, force_refresh: bool = False
    ) -> dict[str, str]:
        """Resolve auth headers (Bearer / API key) from instance.auth_config_id.

        Returns an empty dict if no auth config is attached or resolution fails
        for a non-actionable reason. ``force_refresh`` forces an OAuth token
        refresh (used to react to an upstream 401/403). Propagates
        :class:`OAuthReauthRequiredError` so callers can surface a "reconnect" state
        instead of a raw upstream 401/403.
        """
        if not instance.auth_config_id:
            return {}
        try:
            from agentarea_mcp.infrastructure.auth_repository import (
                MCPAuthConfigRepository,
            )

            auth_repo = MCPAuthConfigRepository(
                self.repository.session, self.repository.user_context
            )
            auth_service = MCPAuthService(auth_repo, self.secret_manager)
            auth_config = await auth_service.get(instance.auth_config_id)
            if not auth_config:
                return {}
            return await auth_service.get_auth_headers(auth_config, force_refresh=force_refresh)
        except OAuthReauthRequiredError:
            raise
        except Exception:
            logger.warning(
                "Failed to resolve auth headers for instance %s",
                instance.id,
                exc_info=True,
            )
            return {}

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

        transport_spec = await self._get_transport_spec_for_instance(instance)
        if transport_spec.get("type", "docker") in ("docker", "command", "kubernetes"):
            await self._retire_runtime_before_mutation(instance.id)

        deleted = await self.repository.delete(id)
        if deleted:
            # This event is notification only. Runtime deletion has already
            # completed synchronously and never depends on lossy Pub/Sub.
            await self.event_broker.publish(MCPServerInstanceDeleted(instance_id=instance.id))
        return deleted

    async def _retire_runtime_before_mutation(self, instance_id: UUID) -> None:
        settings = get_settings().mcp
        url = settings.manager_retire_url(instance_id)
        headers = settings.manager_gateway_headers()
        retryable = {409, 502, 503, 504}
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=settings.MCP_CLIENT_TIMEOUT) as client:
            for attempt in range(3):
                try:
                    response = await client.delete(url, headers=headers)
                    if response.status_code == 204:
                        return
                    if response.status_code not in retryable:
                        response.raise_for_status()
                    last_error = RuntimeError(
                        f"MCP manager retirement returned HTTP {response.status_code}"
                    )
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.2 * (attempt + 1))

        raise RuntimeError(
            f"MCP runtime retirement failed for {instance_id}; desired state was preserved"
        ) from last_error

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

        instances = await self.repository.list_all(creator_scoped=creator_scoped, **filters)
        return [instance for instance in instances if instance.server_spec_id]

    async def execute_tool(
        self,
        server_instance_id: UUID,
        tool_name: str,
        tool_args: dict[str, Any],
        httpx_client_factory: Callable[..., Any] | None = None,
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

        transport_spec = await self._get_transport_spec_for_instance(instance)
        instance_type = transport_spec.get("type", "docker")

        # Bundle: resolve member and check before dispatching
        if instance_type == "bundle":
            tools = instance.tools or transport_spec.get("available_tools") or []
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

            return await self.execute_tool(
                UUID(member_instance_id),
                original_tool_name,
                tool_args,
                httpx_client_factory=httpx_client_factory,
            )

        try:
            mcp_url, headers, transport = await self._resolve_mcp_url_and_headers(instance)
            verdict_key = mcp_verdict_key(server_instance_id, transport_spec)
            if instance_type == "url":
                httpx_client_factory = pinned_client_factory(httpx_client_factory)
            elif httpx_client_factory is None:
                httpx_client_factory = platform_client_factory
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
            call_result = await self._call_tool_via_mcp(
                mcp_url,
                headers,
                tool_name,
                tool_args,
                httpx_client_factory=httpx_client_factory,
                transport=transport,
                verdict_key=verdict_key,
                verdict_store=self.era_verdict_store,
            )
        except Exception as e:
            logger.error(
                "MCP tool call failed for %s (%s): %s",
                server_instance_id,
                tool_name,
                e,
                exc_info=True,
            )
            reason = (
                "could not connect to the MCP server"
                if instance_type == "url" and not _is_mcp_protocol_error(e)
                else str(e)
            )
            return _fail(
                f"MCP '{instance.name}' tool call failed: {reason}. "
                "Re-verify the instance if this persists.",
                f"MCP tool call failed: {reason}",
            )

        parts: list[str] = []
        for block in getattr(call_result, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                parts.append(getattr(block, "text", "") or "")
            elif block_type == "image":
                mime = getattr(block, "mime_type", "unknown")
                parts.append(f"<image mime={mime}>")
            elif block_type == "resource":
                resource = getattr(block, "resource", None)
                uri = getattr(resource, "uri", "unknown") if resource else "unknown"
                parts.append(f"<resource uri={uri}>")
            else:
                parts.append(str(block))

        structured_content = getattr(call_result, "structured_content", None)
        if not parts and structured_content is not None:
            parts.append(str(structured_content))

        result_str = "\n".join(parts)
        is_error = bool(getattr(call_result, "is_error", False))

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
    ) -> tuple[str, dict[str, str], str | None]:
        transport_spec = await self._get_transport_spec_for_instance(instance)
        instance_type = transport_spec.get("type", "docker")
        mcp_url = self._endpoint_url_from_spec(instance, transport_spec)
        if not mcp_url:
            raise RuntimeError(
                f"Instance {instance.id} has no endpoint URL (missing url/external_url in json_spec)"
            )
        transport = declared_remote_transport(transport_spec)

        headers: dict[str, str] = {}
        custom_headers = transport_spec.get("headers")
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
                logger.warning(
                    "Failed to resolve auth headers for instance %s: %s",
                    instance.id,
                    e,
                    exc_info=True,
                )

        if instance_type in ("docker", "command"):
            headers.update(get_settings().mcp.manager_gateway_headers())
            transport = "streamable-http"

        return mcp_url, headers, transport

    async def _with_mcp_session(
        self,
        mcp_url: str,
        headers: dict[str, str],
        operation: Callable[[Any], Any],
        *,
        httpx_client_factory: Callable[..., Any],
        transport: str | None = None,
        timeout_seconds: float = 30.0,
        verdict_key: str | None = None,
        verdict_store=None,
    ) -> Any:
        """Open a connected v2 MCP client and run one operation."""
        async with connected_mcp_client(
            mcp_url,
            headers or None,
            float(timeout_seconds),
            transport=transport,
            verdict_key=verdict_key,
            verdict_store=verdict_store,
            httpx_client_factory=httpx_client_factory,
        ) as client:
            result = operation(client)
            return await result if inspect.isawaitable(result) else result

    async def _call_tool_via_mcp(
        self,
        mcp_url: str,
        headers: dict[str, str],
        tool_name: str,
        tool_args: dict[str, Any],
        httpx_client_factory: Callable[..., Any],
        transport: str | None = None,
        *,
        verdict_key: str | None = None,
        verdict_store=None,
    ):
        return await self._with_mcp_session(
            mcp_url,
            headers,
            lambda client: client.call_tool(tool_name, tool_args),
            httpx_client_factory=httpx_client_factory,
            transport=transport,
            verdict_key=verdict_key,
            verdict_store=verdict_store,
        )

    async def _list_tools_via_mcp(
        self,
        mcp_url: str,
        headers: dict[str, str],
        transport: str | None = None,
        *,
        httpx_client_factory: Callable[..., Any],
    ):
        return await self._with_mcp_session(
            mcp_url,
            headers,
            lambda client: client.list_tools(),
            transport=transport,
            timeout_seconds=10.0,
            httpx_client_factory=httpx_client_factory,
        )

    async def validate_connection(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        """Probe ``url`` with list_tools without creating an instance.

        ``server_id`` names the catalog spec the caller is connecting; when it
        is given and its stored endpoint is ``url``, an auth failure also
        reports ``auth_methods`` so the create page can render the right form.
        """
        if not url:
            return {"valid": False, "errors": ["URL is required"]}

        # This endpoint returns the upstream tool list to the caller, so an
        # unguarded URL here is a full-read SSRF, not a blind one. Refuse before
        # dialing: a check after the request would still reach the internal host.
        try:
            validate_outbound_url(url, policy=OutboundPolicy.from_env())
        except UnsafeUrlError:
            # Deliberately generic: a specific reason would turn this into a DNS
            # oracle telling the caller which internal names resolve.
            logger.warning("Refused MCP connection validation for a non-public URL", exc_info=True)
            return {"valid": False, "errors": ["URL is not allowed"]}

        try:
            result = await self._list_tools_via_mcp(
                url, headers or {}, httpx_client_factory=pinned_client_factory()
            )
            tools = [serialize_mcp_tool(t) for t in result.tools]
            validated: dict[str, Any] = {
                "valid": True,
                "errors": [],
                "tool_count": len(tools),
                "tools": tools,
            }
            # Listing tools is not using them: Gmail's MCP answers tools/list
            # without a token and 401s every call. For a bare endpoint, report the
            # OAuth it advertises so the page asks to connect instead of creating
            # a connection that can list and never call.
            if not headers:
                auth_methods = await self._catalog_auth_methods(url, server_id)
                if "oauth" in auth_methods:
                    validated["auth_methods"] = auth_methods
            return validated
        except Exception as e:
            all_msgs: list[str] = []
            if isinstance(e, ExceptionGroup):
                for sub in e.exceptions:
                    all_msgs.append(str(sub))
            all_msgs.append(str(e))
            combined = " ".join(all_msgs)

            # The transport fallback (streamable HTTP -> SSE) surfaces only the
            # last failure, so a 401 on /mcp is often masked by a 404 on /sse.
            # Ask the endpoint directly whether it wants auth so the caller can
            # tell "wrong credentials" from "unreachable" and render the right form.
            auth_methods = await self._catalog_auth_methods(url, server_id)
            needs_auth = auth_methods in (["oauth", "credentials"], ["credentials"])
            if "403" in combined and "401" not in combined:
                return {
                    "valid": False,
                    "errors": ["Access denied — insufficient permissions"],
                    "auth_methods": auth_methods,
                }
            if "401" in combined or needs_auth:
                return {
                    "valid": False,
                    "errors": ["Authentication failed — check your credentials"],
                    "auth_methods": auth_methods,
                }
            logger.warning("validate_connection failed for %s: %s", url, e, exc_info=True)
            return {
                "valid": False,
                "errors": ["Connection failed. Verify the URL, headers, and server availability."],
            }

    async def _catalog_auth_methods(self, url: str, server_id: str | None) -> list[str]:
        """Detect auth methods for a catalog spec, using the endpoint stored on it.

        The probe only ever dials a URL recorded in the catalog: the caller's
        ``url`` must match the spec's own ``remote_url``, and it is the stored
        value that is contacted. Without a spec there is nothing to detect.
        """
        if not server_id:
            return []
        spec = await self.mcp_server_repository.get_server_by_id(str(server_id))
        if spec is None or not spec.remote_url or spec.remote_url != url:
            return []
        return await self._detect_auth_methods(spec.remote_url)

    async def _detect_auth_methods(self, mcp_url: str) -> list[str]:
        """Classify how an endpoint wants to be authorized, without an instance.

        ``["oauth", "credentials"]`` when the server publishes OAuth metadata,
        ``["credentials"]`` for any other auth challenge, ``["none"]`` for an open
        endpoint, ``[]`` when the endpoint could not be classified.

        OAuth comes from the shared classifier, not from the status of a GET: an
        MCP endpoint may be POST-only (405) or list tools without a token while
        still requiring one to call them, and the metadata is what says so.
        """
        try:
            validate_outbound_url(mcp_url, policy=OutboundPolicy.from_env())
        except UnsafeUrlError:
            logger.debug("Auth-method detection refused for unsafe URL %s", mcp_url, exc_info=True)
            return []

        capability = await MCPOAuthClientService().assess(mcp_url)
        if capability.advertises_oauth:
            return ["oauth", "credentials"]

        try:
            async with safe_async_client(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(mcp_url, follow_redirects=False)
        except Exception:
            logger.debug("Auth-method detection failed for %s", mcp_url, exc_info=True)
            return []

        if resp.status_code in (200, 405):
            return ["none"]
        if resp.status_code in (401, 403):
            return ["credentials"]
        return []

    async def probe_instance_auth(self, instance_id: UUID) -> dict[str, Any]:
        import httpx

        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            return {"status": "error", "message": "Instance not found"}

        transport_spec = await self._get_transport_spec_for_instance(instance)
        instance_type = transport_spec.get("type", "docker")
        if instance_type != "url":
            return {"status": "error", "message": "Probe is only supported for URL-type instances"}

        mcp_url = self._endpoint_url_from_spec(instance, transport_spec)
        if not mcp_url:
            return {"status": "error", "message": "No endpoint URL configured"}

        try:
            async with safe_async_client(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(mcp_url, follow_redirects=True)

                if resp.status_code in (200, 405):
                    return {"status": "ok", "methods": ["none"]}

                # 401 is the spec'd auth challenge; some servers (e.g. Vercel)
                # answer an unauthenticated request with 403 — treat both the same.
                if resp.status_code in (401, 403):
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
                            spec = await server_repo.get_server_by_id(instance.server_spec_id)
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

        except UnsafeUrlError:
            logger.warning(
                "Refused auth probe of a non-public URL for %s", instance_id, exc_info=True
            )
            return {
                "status": "error",
                "message": "The configured endpoint is not an allowed address",
            }
        except httpx.ConnectError:
            return {"status": "error", "message": "Cannot connect to the configured endpoint"}
        except httpx.TimeoutException:
            return {"status": "error", "message": f"Connection to {mcp_url} timed out"}
        except Exception as e:
            logger.warning("Probe failed for instance %s: %s", instance_id, e, exc_info=True)
            return {"status": "error", "message": "Probe failed due to an internal error"}
