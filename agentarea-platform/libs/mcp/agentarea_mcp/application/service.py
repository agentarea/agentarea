import builtins
import logging
from datetime import UTC, timedelta
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
    MCPServerInstanceStarted,
    MCPServerInstanceStopped,
    MCPServerInstanceUpdated,
    MCPServerUpdated,
)
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)

# McpManagerClient removed - using event-driven architecture instead
from agentarea_mcp.schemas import MCPServerStatus

from .mcp_env_service import MCPEnvironmentService
from .oauth_client_service import MCPOAuthClientService
from .validation_service import MCPConfigurationValidator, MCPValidationError

logger = logging.getLogger(__name__)

# Sentinel value for masked secrets — must match across backend and frontend
SECRET_MASKED_VALUE = "*" * 6


class MCPServerService(BaseCrudService[MCPServer]):
    def __init__(self, repository_factory: Any, event_broker: EventBroker | None = None):
        # Create repository using factory
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

        # TODO: Implement actual deployment logic
        # This would involve:
        # 1. Pulling the Docker image
        # 2. Starting the container
        # 3. Configuring networking
        # 4. Updating status

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
        # Use repository directly since we need custom filtering
        return await self.repository.list_servers(
            status=status, is_public=is_public, tag=tag, search=search, limit=limit, offset=offset
        )

    async def get(self, id: UUID) -> MCPServer | None:
        return await self.repository.get_by_id(id)


class MCPServerInstanceService:
    def __init__(
        self,
        repository_factory: Any,  # RepositoryFactory type
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        # Create repositories using factory
        self.repository = repository_factory.create_repository(MCPServerInstanceRepository)
        self.mcp_server_repository = repository_factory.create_repository(MCPServerRepository)

        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self.secret_manager = secret_manager
        self.env_service = MCPEnvironmentService(secret_manager)
        self.db = get_database()

    async def create_instance_from_spec(
        self,
        name: str,
        json_spec: dict[str, Any],
        server_spec_id: UUID,
        description: str | None = None,
    ) -> MCPServerInstance:
        # Extract secret env vars before persisting
        spec, secret_env_vars = await self._extract_secrets_from_spec(
            json_spec, str(server_spec_id)
        )

        instance = await self.repository.create(
            name=name,
            description=description,
            server_spec_id=str(server_spec_id),
            json_spec=spec,
            status=MCPServerStatus.REQUESTED.value,
        )

        # Store secrets in secret manager
        if secret_env_vars:
            await self.env_service.set_instance_environment(instance.id, secret_env_vars)

        # Publish event for Go MCP Manager to handle container creation
        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=str(instance.id), name=instance.name, json_spec=spec
            )
        )
        return instance

    async def create_instance_from_template(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
    ) -> MCPServerInstance | None:
        # Implementation of create_instance_from_template method
        # This method should be implemented based on the original implementation
        # It should return an instance of MCPServerInstance or None if the creation fails
        pass

    def _get_secret_env_names(self, env_schema: list[dict[str, Any]]) -> set[str]:
        """Get names of env vars marked as secret in the schema."""
        return {e["name"] for e in env_schema if isinstance(e, dict) and e.get("isSecret")}

    async def _extract_secrets_from_spec(
        self,
        spec: dict[str, Any],
        server_spec_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Extract secret values from json_spec before DB persistence.

        Returns (cleaned_spec, secret_env_vars) where:
        - cleaned_spec has secret values removed from environment/headers
        - secret_env_vars maps env var names to their secret values
        """
        secret_env_vars: dict[str, str] = {}

        if not server_spec_id:
            return spec, secret_env_vars

        # Look up the server spec to get env_schema with isSecret flags
        server_spec = await self.mcp_server_repository.get_by_id(server_spec_id)
        if not server_spec:
            return spec, secret_env_vars

        env_schema = server_spec.env_schema or []
        secret_names = self._get_secret_env_names(env_schema)
        if not secret_names:
            return spec, secret_env_vars

        spec = dict(spec)  # shallow copy to avoid mutating caller's dict

        # Extract secrets from environment (docker/command types)
        environment = spec.get("environment")
        if isinstance(environment, dict):
            clean_env = {}
            for key, value in environment.items():
                if key in secret_names:
                    secret_env_vars[key] = value
                else:
                    clean_env[key] = value
            spec["environment"] = clean_env

        # Extract secrets from headers (URL types)
        headers = spec.get("headers")
        if isinstance(headers, dict):
            clean_headers = {}
            for key, value in headers.items():
                if key in secret_names:
                    secret_env_vars[key] = value
                else:
                    clean_headers[key] = value
            spec["headers"] = clean_headers

        # Store the list of secret env var names for later resolution
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
        spec = json_spec or {}

        # Skip Docker image/port validation when server_spec_id is provided,
        # since the spec already defines the container image.
        # MCP infrastructure resolves the image from the server spec at deploy time.
        if not server_spec_id:
            validation_errors = MCPConfigurationValidator.validate_json_spec(spec)
            if validation_errors:
                raise MCPValidationError(validation_errors)

        # Extract secret env vars BEFORE persisting to DB
        spec, secret_env_vars = await self._extract_secrets_from_spec(spec, server_spec_id)

        # URL-type and bundle-type instances need no container
        is_url_type = spec.get("type") == "url"
        is_bundle_type = spec.get("type") == "bundle"

        # Create instance using workspace-scoped repository
        create_kwargs: dict[str, Any] = {
            "name": name,
            "description": description,
            "server_spec_id": server_spec_id,
            "json_spec": spec,
            "status": "connected" if (is_url_type or is_bundle_type) else "pending",
        }
        if auth_config_id:
            create_kwargs["auth_config_id"] = auth_config_id

        instance = await self.repository.create(**create_kwargs)

        # Store extracted secrets in secret manager (never in DB)
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
            # No container workflow needed — try discovering tools directly
            try:
                await self.discover_and_store_tools(instance.id)
            except Exception as e:
                logger.warning("Auto tool discovery failed for URL instance", extra={"instance_id": str(instance.id), "error": str(e)})
        elif is_bundle_type:
            # Bundle aggregates other instances — no container needed.
            # Discover and cache tools from all members.
            try:
                await self.discover_and_store_tools(instance.id)
            except Exception as e:
                logger.warning("Auto tool discovery failed for bundle", extra={"instance_id": str(instance.id), "error": str(e)})
        else:
            # Publish event for MCP Infrastructure to handle container deployment
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
        # Build update kwargs
        update_kwargs = {}
        if name is not None:
            update_kwargs["name"] = name
        if description is not None:
            update_kwargs["description"] = description
        if status is not None:
            update_kwargs["status"] = status

        # Handle secret env vars in json_spec update
        if json_spec is not None:
            instance = await self.repository.get_by_id(id)
            if instance:
                cleaned_spec, secret_env_vars = await self._extract_secrets_from_spec(
                    json_spec, instance.server_spec_id
                )
                # Filter out masked placeholder values — don't overwrite real secrets
                masked_placeholders = {SECRET_MASKED_VALUE, "\u2022" * 6}  # "******" and "••••••"
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
                status=instance.status,
            )
        )

        return instance

    async def get_instance_environment(self, instance_id: UUID) -> dict[str, str]:
        """Get environment variables for an instance from the secret manager.

        Args:
            instance_id: The MCP server instance ID

        Returns:
            Dictionary of environment variable names and values
        """
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

        # Publish event for Go MCP Manager to handle container deletion
        await self.event_broker.publish(MCPServerInstanceDeleted(instance_id=instance.id))

        # Delete the instance from the database
        return await self.repository.delete(id)

    async def start_instance(self, id: UUID) -> bool:
        instance = await self.repository.get_by_id(id)
        if not instance:
            return False

        # Get environment variables for container startup
        env_vars = await self.get_instance_environment(id)
        logger.info("Starting instance %s with %d environment variables", id, len(env_vars))

        # Set to "starting" — the actual "running" status comes from Go manager via Redis event
        updated_instance = await self.repository.update(id, status="starting")
        if not updated_instance:
            return False

        await self.event_broker.publish(
            MCPServerInstanceStarted(
                instance_id=updated_instance.id,
                server_spec_id=updated_instance.server_spec_id,
                name=updated_instance.name,
            )
        )

        return True

    async def stop_instance(self, id: UUID) -> bool:
        instance = await self.repository.get_by_id(id)
        if not instance:
            return False

        # Set to "stopping" — the actual "stopped" status comes from Go manager via Redis event
        updated_instance = await self.repository.update(id, status="stopping")
        if not updated_instance:
            return False

        await self.event_broker.publish(
            MCPServerInstanceStopped(
                instance_id=updated_instance.id,
                server_spec_id=updated_instance.server_spec_id,
                name=updated_instance.name,
            )
        )

        return True

    async def get(self, id: UUID) -> MCPServerInstance | None:
        """Get an MCP server instance by ID."""
        return await self.repository.get_by_id(id)

    async def get_by_name(self, name: str) -> MCPServerInstance | None:
        """Get an MCP server instance by name within the current workspace.

        Used by tool discovery when an agent's tools_config references an MCP
        instance by display name (e.g. {"type": "mcp", "name": "Dev Bundle"}).
        """
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
        # Build filters for the repository
        filters = {}
        if server_spec_id:
            filters["server_spec_id"] = server_spec_id
        if status:
            filters["status"] = status

        # Use the repository's list_all method with creator_scoped parameter
        return await self.repository.list_all(creator_scoped=creator_scoped, **filters)

    async def _validate_env_vars(
        self, env_vars: dict[str, str], env_schema: builtins.list[dict[str, Any]]
    ) -> builtins.list[str]:
        """Validate environment variables against the server's schema.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []
        schema_by_name = {item["name"]: item for item in env_schema}

        # Check required environment variables
        for schema_item in env_schema:
            env_name = schema_item["name"]
            is_required = schema_item.get("required", False)

            if is_required and env_name not in env_vars:
                errors.append(f"Required environment variable '{env_name}' is missing")

        # Check provided environment variables against schema
        for env_name, env_value in env_vars.items():
            if env_name not in schema_by_name:
                errors.append(f"Environment variable '{env_name}' is not defined in server schema")
                continue

            schema_item = schema_by_name[env_name]
            env_type = schema_item.get("type", "string")

            # Basic type validation
            if env_type == "number":
                try:
                    float(env_value)
                except ValueError:
                    errors.append(f"Environment variable '{env_name}' must be a number")
            elif env_type == "boolean":
                if env_value.lower() not in ["true", "false", "1", "0"]:
                    errors.append(
                        f"Environment variable '{env_name}' must be a boolean (true/false)"
                    )

        return errors

    async def probe_instance_auth(self, instance_id: UUID) -> dict[str, Any]:
        """Probe an MCP server instance to detect its auth requirements.

        For URL-type instances only. Connects to the endpoint and checks:
        - 200 OK → no auth needed
        - 401 + WWW-Authenticate with OAuth metadata → OAuth supported
        - 401 without OAuth → needs credentials (API key / bearer)
        - Connection error → unreachable

        Returns a dict with:
            status: "ok" | "auth_required" | "error"
            methods: list of supported auth methods ["oauth", "credentials"]
            hints: list of env_schema hints for credential form
            message: error message if status is "error"
        """
        import httpx

        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            return {"status": "error", "message": "Instance not found"}

        instance_type = (instance.json_spec or {}).get("type", "docker")
        if instance_type != "url":
            return {"status": "error", "message": "Probe is only supported for URL-type instances"}

        mcp_url = (instance.json_spec or {}).get("endpoint_url") or (instance.json_spec or {}).get(
            "url", ""
        )
        if not mcp_url:
            return {"status": "error", "message": "No endpoint URL configured"}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(mcp_url, follow_redirects=True)

                if resp.status_code == 200 or resp.status_code == 405:
                    # Server is reachable and doesn't require auth
                    # 405 Method Not Allowed is common for MCP servers that only accept POST
                    return {"status": "ok", "methods": ["none"]}

                if resp.status_code == 401:
                    www_auth = resp.headers.get("www-authenticate", "")

                    # Check for OAuth metadata in WWW-Authenticate header
                    has_oauth = (
                        "resource_metadata" in www_auth.lower() or "bearer" in www_auth.lower()
                    )

                    if has_oauth:
                        # Try to discover OAuth metadata
                        try:
                            oauth_service = MCPOAuthClientService()
                            await oauth_service.discover_auth_server(mcp_url)
                            # If discovery succeeds, OAuth is supported
                            return {
                                "status": "auth_required",
                                "methods": ["oauth", "credentials"],
                            }
                        except Exception:
                            # OAuth discovery failed, fall back to credentials only
                            logger.debug(
                                "OAuth discovery failed for %s, falling back to credentials",
                                mcp_url,
                            )

                    # No OAuth metadata or discovery failed — needs credentials
                    # Get hints from the server spec's env_schema if available
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

                # Other status codes
                return {
                    "status": "error",
                    "message": f"Unexpected response: {resp.status_code}",
                }

        except httpx.ConnectError:
            return {"status": "error", "message": "Cannot connect to the configured endpoint"}
        except httpx.TimeoutException:
            return {"status": "error", "message": f"Connection to {mcp_url} timed out"}
        except Exception as e:
            logger.warning("Probe failed for instance", extra={"instance_id": str(instance_id), "error": str(e)}, exc_info=True)
            return {"status": "error", "message": "Probe failed due to an internal error"}

    async def discover_and_store_tools(self, instance_id: UUID) -> bool:
        """Discover available tools from MCP server instance and store them.

        Connects to the running MCP server via Traefik gateway, lists tools,
        and persists them in json_spec["available_tools"].

        Args:
            instance_id: The MCP server instance ID

        Returns:
            True if tools were successfully discovered and stored, False otherwise
        """
        instance = await self.repository.get_by_id(instance_id)
        if not instance:
            return False

        # Determine the MCP URL based on instance type
        instance_type = (instance.json_spec or {}).get("type", "docker")

        # Bundle type: aggregate tools from all member instances
        if instance_type == "bundle":
            return await self._discover_bundle_tools(instance)

        if instance_type == "url":
            # External MCP — connect directly to the configured URL
            mcp_url = (instance.json_spec or {}).get("endpoint_url") or (
                instance.json_spec or {}
            ).get("url", "")
            if not mcp_url:
                logger.warning("URL-type instance has no endpoint_url in json_spec", extra={"instance_id": str(instance_id)})
                return False
        else:
            # Docker or command-type — connect directly to container by name
            # Must match Go manager's generateSlug: lowercase, replace non-alnum with '-', trim
            import re

            slug = re.sub(r"[^a-z0-9]+", "-", instance.name.lower()).strip("-")
            container_name = f"mcp-{slug}"
            container_port = (instance.json_spec or {}).get("port", 8080)
            # command-type runs via mcp-bridge which serves on /mcp
            # docker-type serves on whatever path the image exposes (default: root)
            path = "/mcp" if instance_type == "command" else ""
            mcp_url = f"http://{container_name}:{container_port}{path}"

        # Build optional headers (e.g. for auth on external MCPs)
        # Headers are stored as a dict in json_spec.headers by the creation form
        headers: dict[str, str] = {}
        custom_headers = (instance.json_spec or {}).get("headers")
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)

        # Resolve OAuth/bearer token from linked auth config
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
                logger.warning("Failed to resolve auth headers for instance", extra={"instance_id": str(instance_id), "error": str(e)})

        try:
            result = await self._list_tools_via_mcp(mcp_url, headers)

            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if t.inputSchema else {},
                }
                for t in result.tools
            ]

            instance.set_available_tools(tools)
            new_json_spec = dict(instance.json_spec)

            # Compute tools hash for change detection
            import hashlib
            import json as _json
            from datetime import datetime as _dt

            sorted_sigs = sorted(
                [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": tool["inputSchema"],
                    }
                    for tool in tools
                ],
                key=lambda x: x["name"],
            )
            tools_hash = hashlib.sha256(
                _json.dumps(sorted_sigs, sort_keys=True).encode()
            ).hexdigest()

            previous_hash = new_json_spec.get("tools_hash")
            tools_changed = previous_hash != tools_hash
            if tools_changed and previous_hash is not None:
                logger.info(
                    "Tools changed for instance %s: %s -> %s",
                    instance_id,
                    previous_hash[:12],
                    tools_hash[:12],
                )

            new_json_spec["tools_hash"] = tools_hash
            new_json_spec["tools_updated_at"] = _dt.now(UTC).isoformat()
            new_json_spec["tools_changed"] = tools_changed

            from sqlalchemy import update as sa_update

            db_session = self.repository.session
            stmt = (
                sa_update(type(instance))
                .where(type(instance).id == instance_id)
                .values(json_spec=new_json_spec)
            )
            await db_session.execute(stmt)
            await db_session.commit()

            logger.info("Discovered %d tools for instance %s", len(tools), instance_id)
            return True

        except Exception as e:
            logger.error("Tool discovery failed for %s: %s", instance_id, e, exc_info=True)
            return False

    async def _list_tools_via_mcp(self, mcp_url: str, headers: dict[str, str]):
        """Connect to MCP server and list tools. Tries streamable HTTP first, falls back to SSE."""
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

    async def _discover_bundle_tools(self, instance) -> bool:
        """Aggregate tools from all bundle member instances with namespace prefixes."""
        import hashlib
        import json as _json
        from datetime import datetime as _dt

        from sqlalchemy import update as sa_update

        json_spec = instance.json_spec or {}
        member_ids: list[str] = json_spec.get("members", [])
        if not member_ids:
            logger.warning("Bundle %s has no members", instance.id)
            return False

        ns_sep = "__"
        all_tools: list[dict[str, Any]] = []

        for mid in member_ids:
            try:
                member = await self.repository.get_by_id(mid)
            except Exception:
                member = None
            if not member:
                logger.warning("Bundle member %s not found, skipping", mid)
                continue

            # Use cached tools from member if available
            member_tools = (member.json_spec or {}).get("available_tools", [])
            if not member_tools:
                # Try live discovery for this member
                try:
                    await self.discover_and_store_tools(member.id)
                    member = await self.repository.get_by_id(mid)
                    member_tools = (
                        (member.json_spec or {}).get("available_tools", []) if member else []
                    )
                except Exception as e:
                    logger.warning("Failed to discover tools for bundle member %s: %s", mid, e)
                    continue

            # Namespace: slugified member name
            namespace = member.name.lower().replace(" ", "_").replace("-", "_")

            for tool in member_tools:
                all_tools.append(
                    {
                        "name": f"{namespace}{ns_sep}{tool['name']}",
                        "description": f"[{member.name}] {tool.get('description', '')}",
                        "inputSchema": tool.get("inputSchema", {}),
                        "member_instance_id": str(member.id),
                        "original_tool_name": tool["name"],
                    }
                )

        # Store aggregated tools
        new_json_spec = dict(json_spec)
        new_json_spec["available_tools"] = all_tools

        sorted_sigs = sorted(
            [{"name": t["name"], "description": t["description"]} for t in all_tools],
            key=lambda x: x["name"],
        )
        tools_hash = hashlib.sha256(_json.dumps(sorted_sigs, sort_keys=True).encode()).hexdigest()

        new_json_spec["tools_hash"] = tools_hash
        new_json_spec["tools_updated_at"] = _dt.now(UTC).isoformat()

        db_session = self.repository.session
        stmt = (
            sa_update(type(instance))
            .where(type(instance).id == instance.id)
            .values(json_spec=new_json_spec)
        )
        await db_session.execute(stmt)
        await db_session.commit()

        logger.info(
            "Discovered %d tools across %d members for bundle %s",
            len(all_tools),
            len(member_ids),
            instance.id,
        )
        return True

    async def validate_connection(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Test a connection to an MCP server without creating an instance.

        Returns:
            dict with status, tools list, and tool_count on success,
            or error details on failure.
        """
        if not url:
            return {"status": "error", "message": "URL is required"}

        try:
            result = await self._list_tools_via_mcp(url, headers or {})
            tools = [{"name": t.name, "description": t.description or ""} for t in result.tools]
            return {
                "status": "ok",
                "tool_count": len(tools),
                "tools": tools,
            }
        except Exception as e:
            # Flatten ExceptionGroup sub-exceptions to inspect root causes
            all_msgs: list[str] = []
            if isinstance(e, ExceptionGroup):
                for sub in e.exceptions:
                    all_msgs.append(str(sub))
            all_msgs.append(str(e))
            combined = " ".join(all_msgs)

            if "401" in combined:
                return {
                    "status": "auth_error",
                    "message": "Authentication failed — check your credentials",
                }
            if "403" in combined:
                return {
                    "status": "auth_error",
                    "message": "Access denied — insufficient permissions",
                }
            logger.warning("validate_connection failed for %s: %s", url, e, exc_info=True)
            return {
                "status": "error",
                "message": "Connection failed. Verify the URL, headers, and server availability.",
            }
