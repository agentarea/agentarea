from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.base.repository import BaseRepository
from ..domain.models import MCPServer


class MCPServerRepository(BaseRepository[MCPServer]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, MCPServer)

    async def list(
        self,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        tag: Optional[str] = None,
    ) -> List[MCPServer]:
        query = self.session.query(MCPServer)
        
        if status is not None:
            query = query.filter(MCPServer.status == status)
        if is_public is not None:
            query = query.filter(MCPServer.is_public == is_public)
        if tag is not None:
            query = query.filter(MCPServer.tags.contains([tag]))
            
        return await query.all() 