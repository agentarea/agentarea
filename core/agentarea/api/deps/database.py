from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_db


async def get_db_session() -> AsyncSession:
    """Get database session dependency"""
    async for session in get_db():
        yield session


# Type alias for dependency injection
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
