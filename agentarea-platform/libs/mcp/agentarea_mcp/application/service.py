import builtins
import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from agentarea_common.base.service import BaseCrudService
from agentarea_common.config import get_database, get_settings
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
from .validation_service import MCPConfigurationValidator, MCPValidationError

logger = logging.getLogger(__name__)


class MCPServerService(BaseCrudService[MCPServer]):
    def __init__(self, repository_factory: Any, event_broker: EventBroker | None = None):
        # Create repository using factory
        repository = repository_factory.create_repository(MCPServerRepository)
        super().__init__(repository)
        self.repository_factory = repository_factory
        self.event_broker = event_broker

    async def create_mcp_server(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: list[str] | None = None,
        is_public: bool = False,
        env_schema: list[dict[str, Any]] | None = None,
        cmd: list[str] | None = None,
        json_spec: dict[str, Any] | None = None,
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
        )
        server = await self.create(server)

        if self.event_broker:
            await self.event_broker.publish(
                MCPServerCreated(server_id=server.id, name=server.name, version=server.version)
            )

        return server

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
    ) -> list[MCPServer]:
        # Use repository directly since we need custom filtering
        return await self.repository.list_servers(status=status, is_public=is_public, tag=tag)

    async def get(self, id: UUID) -> MCPServer | None:
        return await self.repository.get(id)


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
        instance = await self.repository.create(
            name=name,
            description=description,
            server_spec_id=str(server_spec_id),
            json_spec=json_spec,
            status=MCPServerStatus.REQUESTED.value,
        )

        # Publish event for Go MCP Manager to handle container creation
        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=str(instance.id), name=instance.name, json_spec=json_spec
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

    async def create_instance(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
        auth_config_id: str | None = None,
    ) -> MCPServerInstance | None:
        spec = json_spec or {}

        # Validate the JSON specification
        validation_errors = MCPConfigurationValidator.validate_json_spec(spec)
        if validation_errors:
            raise MCPValidationError(validation_errors)

        # Create instance using workspace-scoped repository
        create_kwargs: dict[str, Any] = {
            "name": name,
            "description": description,
            "server_spec_id": server_spec_id,
            "json_spec": spec,
            "status": "pending",  # Will be updated by mcp-infrastructure
        }
        if auth_config_id:
            create_kwargs["auth_config_id"] = auth_config_id

        instance = await self.repository.create(**create_kwargs)

        # Publish event for MCP Infrastructure to handle deployment
        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=str(instance.id),
                server_spec_id=server_spec_id,
                name=instance.name,
                json_spec=spec,
            )
        )

        return instance

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
        if json_spec is not None:
            update_kwargs["json_spec"] = json_spec
        if status is not None:
            update_kwargs["status"] = status

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
        if not instance or instance.status != "running":
            return False

        # Determine the MCP URL based on instance type
        instance_type = (instance.json_spec or {}).get("type", "docker")
        if instance_type == "url":
            # External MCP — connect directly to the configured URL
            mcp_url = (instance.json_spec or {}).get("url", "")
            if not mcp_url:
                logger.warning("URL-type instance %s has no url in json_spec", instance_id)
                return False
        else:
            # Docker or command-type — routed via Traefik gateway using instance ID
            gateway_url = get_settings().mcp.MCP_GATEWAY_URL
            mcp_url = f"{gateway_url}/mcp/{instance_id}/mcp"

        # Build optional headers (e.g. for auth on external MCPs)
        headers: dict[str, str] = {}
        auth_header = (instance.json_spec or {}).get("auth_header")
        auth_value = (instance.json_spec or {}).get("auth_value")
        if auth_header and auth_value:
            headers[auth_header] = auth_value

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                mcp_url, timeout=timedelta(seconds=10), headers=headers
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()

            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if t.inputSchema else {},
                }
                for t in result.tools
            ]

            instance.set_available_tools(tools)
            new_json_spec = dict(instance.json_spec)  # copy to ensure new object

            # Direct DB update to avoid SQLAlchemy JSON mutation detection issues
            from sqlalchemy import update as sa_update

            session = self.repository.session
            stmt = (
                sa_update(type(instance))
                .where(type(instance).id == instance_id)
                .values(json_spec=new_json_spec)
            )
            await session.execute(stmt)
            await session.commit()

            logger.info("Discovered %d tools for instance %s", len(tools), instance_id)
            return True

        except Exception as e:
            logger.warning("Tool discovery failed for %s: %s", instance_id, e)
            return False
