from typing import List, Optional
from uuid import UUID

from agentarea.common.base.service import BaseService
from agentarea.common.events.broker import EventBroker

from ..domain.events import (
    MCPServerCreated, MCPServerDeleted, MCPServerDeployed, MCPServerUpdated,
    MCPServerInstanceCreated, MCPServerInstanceDeleted, MCPServerInstanceStarted,
    MCPServerInstanceStopped, MCPServerInstanceUpdated
)
from ..domain.models import MCPServer, MCPServerInstance
from ..infrastructure.repository import MCPServerRepository, MCPServerInstanceRepository


class MCPServerService(BaseService[MCPServer]):
    def __init__(self, repository: MCPServerRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker

    async def create_mcp_server(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: List[str] = None,
        is_public: bool = False
    ) -> MCPServer:
        server = MCPServer(
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            version=version,
            tags=tags or [],
            is_public=is_public
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
        status: Optional[str] = None
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

    async def list(
        self,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        tag: Optional[str] = None
    ) -> List[MCPServer]:
        return await self.repository.list(status=status, is_public=is_public, tag=tag)


class MCPServerInstanceService(BaseService[MCPServerInstance]):
    def __init__(self, repository: MCPServerInstanceRepository, event_broker: EventBroker, 
                 mcp_server_repository: MCPServerRepository):
        super().__init__(repository)
        self.event_broker = event_broker
        self.mcp_server_repository = mcp_server_repository

    async def create_instance(
        self,
        server_id: UUID,
        name: str,
        endpoint_url: str,
        config: dict = None,
    ) -> Optional[MCPServerInstance]:
        # Check if the server exists
        server = await self.mcp_server_repository.get(server_id)
        if not server:
            return None
            
        instance = MCPServerInstance(
            server_id=server_id,
            name=name,
            endpoint_url=endpoint_url,
            config=config or {},
        )
        instance = await self.create(instance)

        await self.event_broker.publish(
            MCPServerInstanceCreated(
                instance_id=instance.id,
                server_id=instance.server_id,
                name=instance.name
            )
        )

        return instance

    async def update_instance(
        self,
        id: UUID,
        name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        config: Optional[dict] = None,
        status: Optional[str] = None
    ) -> Optional[MCPServerInstance]:
        instance = await self.get(id)
        if not instance:
            return None

        if name is not None:
            instance.name = name
        if endpoint_url is not None:
            instance.endpoint_url = endpoint_url
        if config is not None:
            instance.config = config
        if status is not None:
            instance.status = status

        instance = await self.update(instance)

        await self.event_broker.publish(
            MCPServerInstanceUpdated(
                instance_id=instance.id,
                server_id=instance.server_id,
                name=instance.name,
                status=instance.status
            )
        )

        return instance

    async def delete_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False
            
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(
                MCPServerInstanceDeleted(
                    instance_id=id,
                    server_id=instance.server_id
                )
            )
        return success

    async def start_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False

        # TODO: Implement instance startup logic
        instance.status = "running"
        await self.update(instance)

        await self.event_broker.publish(
            MCPServerInstanceStarted(
                instance_id=instance.id,
                server_id=instance.server_id,
                name=instance.name
            )
        )

        return True

    async def stop_instance(self, id: UUID) -> bool:
        instance = await self.get(id)
        if not instance:
            return False

        # TODO: Implement instance stop logic
        instance.status = "stopped"
        await self.update(instance)

        await self.event_broker.publish(
            MCPServerInstanceStopped(
                instance_id=instance.id,
                server_id=instance.server_id,
                name=instance.name
            )
        )

        return True

    async def list(
        self,
        server_id: Optional[UUID] = None,
        status: Optional[str] = None
    ) -> List[MCPServerInstance]:
        return await self.repository.list(server_id=server_id, status=status) 