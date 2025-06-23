import builtins
from typing import Any
from uuid import UUID

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


class MCPServerService(BaseCrudService[MCPServer]):
    def __init__(self, repository: MCPServerRepository, event_broker: EventBroker | None = None):
        super().__init__(repository)
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
        return await self.repository.list(status=status, is_public=is_public, tag=tag)

    async def get(self, id: UUID) -> MCPServer | None:
        return await self.repository.get(id)


class MCPServerInstanceService(BaseCrudService[MCPServerInstance]):
    def __init__(
        self,
        repository: MCPServerInstanceRepository,
        event_broker: EventBroker,
        mcp_server_repository: MCPServerRepository,
        secret_manager: BaseSecretManager,
    ):
        super().__init__(repository)
        self.event_broker = event_broker
        self.mcp_server_repository = mcp_server_repository
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
        instance = MCPServerInstance(
            name=name,
            description=description,
            server_spec_id=str(server_spec_id),
            json_spec=json_spec,
            status=MCPServerStatus.REQUESTED.value,
        )
        instance = await self.repository.create(instance)

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
    ) -> MCPServerInstance | None:
        spec = json_spec or {}

        # Create instance - mcp-infrastructure will determine how to handle it based on json_spec
        instance = MCPServerInstance(
            name=name,
            description=description,
            server_spec_id=server_spec_id,
            json_spec=spec,
            status="pending",  # Will be updated by mcp-infrastructure
        )

        # Save to database
        instance = await self.create(instance)

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
        instance = await self.get(id)
        if not instance:
            return None

        if name is not None:
            instance.name = name
        if description is not None:
            instance.description = description
        if json_spec is not None:
            instance.json_spec = json_spec
        if status is not None:
            instance.status = status

        instance = await self.repository.update(instance)

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
        instance = await self.get(instance_id)
        if not instance:
            return {}

        env_var_names = instance.get_configured_env_vars()
        if not env_var_names:
            return {}

        return await self.env_service.get_instance_environment(instance_id, env_var_names)

    async def delete_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False

        # Publish event for Go MCP Manager to handle container deletion
        await self.event_broker.publish(
            MCPServerInstanceDeleted(instance_id=str(instance.id), name=instance.name)
        )

        # Delete the instance from the database
        return await super().delete(id)

    async def start_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False

        # TODO: Implement actual start logic
        # This would involve:
        # 1. Getting environment variables from secret manager
        # 2. Starting the Docker container with environment variables
        # 3. Updating status

        # Get environment variables for container startup
        env_vars = await self.get_instance_environment(id)
        print(f"Starting instance {id} with {len(env_vars)} environment variables")

        instance.status = "running"
        await self.repository.update(instance)

        await self.event_broker.publish(
            MCPServerInstanceStarted(
                instance_id=instance.id, server_spec_id=instance.server_spec_id, name=instance.name
            )
        )

        return True

    async def stop_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False

        # TODO: Implement actual stop logic
        instance.status = "stopped"
        await self.repository.update(instance)

        await self.event_broker.publish(
            MCPServerInstanceStopped(
                instance_id=instance.id, server_spec_id=instance.server_spec_id, name=instance.name
            )
        )

        return True

    async def list(
        self, server_spec_id: str | None = None, status: str | None = None
    ) -> list[MCPServerInstance]:
        return await self.repository.list(server_spec_id=server_spec_id, status=status)

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
