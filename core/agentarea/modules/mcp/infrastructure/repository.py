from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.base.repository import BaseRepository

from ..domain.models import MCPServer, MCPServerInstance


class MCPServerRepository(BaseRepository[MCPServer]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> Optional[MCPServer]:
        async with self.session.begin():
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
        async with self.session.begin():
            query = select(MCPServer)

            conditions = []
            if status is not None:
                conditions.append(MCPServer.status == status)
            if is_public is not None:
                conditions.append(MCPServer.is_public == is_public)
            if tag is not None:
                conditions.append(MCPServer.tags.contains([tag]))

            if conditions:
                query = query.where(and_(*conditions))

            result = await self.session.execute(query)
            return list(result.scalars().all())

    async def create(self, server: MCPServer) -> MCPServer:
        async with self.session.begin():
            self.session.add(server)
            await self.session.flush()
            return server

    async def update(self, server: MCPServer) -> MCPServer:
        async with self.session.begin():
            await self.session.merge(server)
            await self.session.flush()
            return server

    async def delete(self, id: UUID) -> bool:
        async with self.session.begin():
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
        async with self.session.begin():
            result = await self.session.execute(
                select(MCPServerInstance).where(MCPServerInstance.id == id)
            )
            return result.scalar_one_or_none()

    async def list(
        self,
        server_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> List[MCPServerInstance]:
        async with self.session.begin():
            query = select(MCPServerInstance)

            conditions = []
            if server_id is not None:
                conditions.append(MCPServerInstance.server_id == server_id)
            if status is not None:
                conditions.append(MCPServerInstance.status == status)

            if conditions:
                query = query.where(and_(*conditions))

            result = await self.session.execute(query)
            return list(result.scalars().all())

    async def create(self, instance: MCPServerInstance) -> MCPServerInstance:
        async with self.session.begin():
            self.session.add(instance)
            await self.session.flush()
            return instance

    async def update(self, instance: MCPServerInstance) -> MCPServerInstance:
        async with self.session.begin():
            await self.session.merge(instance)
            await self.session.flush()
            return instance

    async def delete(self, id: UUID) -> bool:
        async with self.session.begin():
            result = await self.session.execute(
                select(MCPServerInstance).where(MCPServerInstance.id == id)
            )
            instance = result.scalar_one_or_none()
            if instance:
                await self.session.delete(instance)
                await self.session.flush()
                return True
            return False
