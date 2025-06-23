from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.base.repository import BaseRepository
from ..domain.mpc_server_instance_model import MCPServerInstance

from ..domain.models import MCPServer


class MCPServerRepository(BaseRepository[MCPServer]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> Optional[MCPServer]:
        result = await self.session.execute(
            select(MCPServer).where(MCPServer.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        tag: Optional[str] = None,
    ) -> List[MCPServer]:
        query = select(MCPServer)

        conditions = []
        if status is not None:
            conditions.append(MCPServer.status == status)
        if is_public is not None:
            conditions.append(MCPServer.is_public == is_public)
        if tag is not None:
            # For SQLite, use LIKE to search within JSON array
            conditions.append(MCPServer.tags.like(f'%"{tag}"%'))

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: MCPServer) -> MCPServer:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: MCPServer) -> MCPServer:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(
            select(MCPServer).where(MCPServer.id == id)
        )
        server = result.scalar_one_or_none()
        if server:
            await self.session.delete(server)
            await self.session.flush()
            return True
        return False


class MCPServerInstanceRepository(BaseRepository[MCPServerInstance]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> Optional[MCPServerInstance]:
        result = await self.session.execute(
            select(MCPServerInstance).where(MCPServerInstance.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        server_spec_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[MCPServerInstance]:
        query = select(MCPServerInstance)

        conditions = []
        if server_spec_id is not None:
            conditions.append(MCPServerInstance.server_spec_id == server_spec_id)
        if status is not None:
            conditions.append(MCPServerInstance.status == status)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, instance: MCPServerInstance) -> MCPServerInstance:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: MCPServerInstance) -> MCPServerInstance:
        await self.session.merge(instance)
        await self.session.flush()
        return instance

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(
            select(MCPServerInstance).where(MCPServerInstance.id == id)
        )
        instance = result.scalar_one_or_none()
        if instance:
            await self.session.delete(instance)
            await self.session.flush()
            return True
        return False
