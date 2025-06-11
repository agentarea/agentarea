from uuid import UUID
from typing import Optional, List, Dict, Any

from agentarea.common.base.service import BaseCrudService
from agentarea.common.events.broker import EventBroker
from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from agentarea.config import get_database

from ..domain.events import (
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
from ..domain.models import MCPServer
from ..domain.mpc_server_instance_model import MCPServerInstance
from ..infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from .mcp_env_service import MCPEnvironmentService


class MCPServerService(BaseCrudService[MCPServer]):
    def __init__(self, repository: MCPServerRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker

    async def create_mcp_server(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: Optional[List[str]] = None,
        is_public: bool = False,
        env_schema: Optional[List[Dict[str, Any]]] = None
    ) -> MCPServer:
        server = MCPServer(
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            version=version,
            tags=tags or [],
            is_public=is_public,
            env_schema=env_schema or []
        )
        server = await self.create(server)

        await self.event_broker.publish(
            MCPServerCreated(
                server_id=server.id,
                name=server.name,
                version=server.version
            )
        )

        return server

    async def update_mcp_server(
        self,
        id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        docker_image_url: Optional[str] = None,
        version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_public: Optional[bool] = None,
        status: Optional[str] = None,
        env_schema: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[MCPServer]:
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

        server = await self.update(server)

        await self.event_broker.publish(
            MCPServerUpdated(
                server_id=server.id,
                name=server.name,
                version=server.version
            )
        )

        return server

    async def delete_mcp_server(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
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

        await self.event_broker.publish(
            MCPServerDeployed(
                server_id=server.id,
                name=server.name,
                version=server.version
            )
        )

        return True

    async def list_servers(
        self,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        tag: Optional[str] = None
    ) -> List[MCPServer]:
        # Use repository directly since we need custom filtering
        return await self.repository.list(status=status, is_public=is_public, tag=tag)


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
        self.db = get_database()  # Add database access

    async def create_instance(
        self,
        name: str,
        description: Optional[str] = None,
        server_spec_id: Optional[str] = None,
        json_spec: Optional[Dict[str, Any]] = None,
    ) -> Optional[MCPServerInstance]:
        
        spec = json_spec or {}
        
        # Create instance - mcp-infrastructure will determine how to handle it based on json_spec
        instance = MCPServerInstance(
            name=name,
            description=description,
            server_spec_id=server_spec_id,
            json_spec=spec,
            status="pending"  # Will be updated by mcp-infrastructure
        )

        # Save to database
        instance = await self.create(instance)

        # Publish event for MCP Infrastructure to handle deployment
        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=str(instance.id),
                server_spec_id=server_spec_id,
                name=instance.name,
                json_spec=spec
            )
        )

        return instance

    async def update_instance(
        self,
        id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        json_spec: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Optional[MCPServerInstance]:
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
                status=instance.status
            )
        )

        return instance

    async def get_instance_environment(
        self, 
        instance_id: UUID
    ) -> Dict[str, str]:
        """
        Get environment variables for an instance from the secret manager.
        
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

        # Clean up environment variables from secret manager
        env_var_names = instance.get_configured_env_vars()
        if env_var_names:
            await self.env_service.delete_instance_environment(id, env_var_names)

        success = await self.repository.delete(id)
        if success:
            await self.event_broker.publish(MCPServerInstanceDeleted(instance_id=id))
        return success

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
                instance_id=instance.id,
                server_spec_id=instance.server_spec_id,
                name=instance.name
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
                instance_id=instance.id,
                server_spec_id=instance.server_spec_id,
                name=instance.name
            )
        )

        return True

    async def list(
        self,
        server_spec_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[MCPServerInstance]:
        return await self.repository.list(server_spec_id=server_spec_id, status=status)

    async def get(self, id: UUID) -> Optional[MCPServerInstance]:
        """Get MCP server instance with separate session to avoid transaction conflicts."""
        async with self.db.get_db() as session:
            repo = MCPServerInstanceRepository(session)
            return await repo.get(id)

    async def _validate_env_vars(
        self, 
        env_vars: Dict[str, str], 
        env_schema: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Validate environment variables against the server's schema.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []
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
                    errors.append(f"Environment variable '{env_name}' must be a boolean (true/false)")
        
        return errors
