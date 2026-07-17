from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from agentarea_common.config.database import get_read_db_session
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_db


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session as async context manager."""
    async with get_db() as session:
        yield session


# Type alias for dependency injection
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]

ReadDatabaseSessionDep = Annotated[AsyncSession, Depends(get_read_db_session)]
