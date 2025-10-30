from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentarea_common.config import DatabaseSettings, get_db_settings


class Database:
    """Database connection manager."""

    _instance: Optional["Database"] = None
    _initialized: bool = False

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        if not Database._initialized:
            self.settings = settings or get_db_settings()
            self.engine: AsyncEngine = create_async_engine(
                self.settings.url,
                echo=self.settings.echo,
                pool_size=self.settings.pool_size,
                max_overflow=self.settings.max_overflow,
            )
            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            Database._initialized = True

    def __new__(cls, settings: DatabaseSettings | None = None) -> "Database":
        """Create or return the singleton `Database` instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
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
        """Dependency for FastAPI."""
        async with self.session() as session:
            yield session


# Create global instances
db = Database()
get_db_session = db.get_db
