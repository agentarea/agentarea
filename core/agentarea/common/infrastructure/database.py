from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from agentarea.config import get_db_settings, DatabaseSettings


class Database:
    """Database connection manager"""

    _instance: Optional["Database"] = None

    def __new__(cls, settings: Optional[DatabaseSettings] = None) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.settings = settings or get_db_settings()
            cls._instance.engine = create_async_engine(
                cls._instance.settings.url,
                echo=cls._instance.settings.echo,
                pool_size=cls._instance.settings.pool_size,
                max_overflow=cls._instance.settings.max_overflow,
            )
            cls._instance.session_factory = async_sessionmaker(
                cls._instance.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return cls._instance

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session"""
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_db(self) -> AsyncGenerator[AsyncSession, None]:
        """Dependency for FastAPI"""
        async with self.session() as session:
            yield session


# Create global instances
db = Database()
get_db_session = db.get_db
