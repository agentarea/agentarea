"""Database configuration and connection management."""

import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from .base import BaseAppSettings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class DatabaseSettings(BaseAppSettings):
    """Database configuration and connection settings."""

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"  # noqa: S105
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "aiagents"
    pool_size: int = 20  # Increased from 5 to handle more concurrent SSE connections
    max_overflow: int = 30  # Increased from 10 to handle bursts
    pool_timeout: int = 30  # Timeout for getting connection from pool
    pool_recycle: int = 3600  # Recycle connections every hour to prevent stale connections
    echo: bool = False

    @property
    def url(self) -> str:
        """Async database URL for SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_url(self) -> str:
        """Sync database URL for SQLAlchemy."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class Database:
    """Database connection manager using singleton pattern."""

    _instance: Optional["Database"] = None
    _initialized: bool = False

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        """Initialize database connections."""
        if self._initialized:
            return

        self.settings = settings or get_db_settings()
        self._setup_engines()
        self._setup_session_factories()
        self._initialized = True

    @classmethod
    def get_instance(cls, settings: DatabaseSettings | None = None) -> "Database":
        """Get the singleton instance of Database."""
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance.__init__(settings)
        return cls._instance

    def _setup_engines(self) -> None:
        """Setup async and sync database engines."""
        engine_kwargs = {
            "echo": self.settings.echo,
            "pool_size": self.settings.pool_size,
            "max_overflow": self.settings.max_overflow,
            "pool_timeout": self.settings.pool_timeout,
            "pool_recycle": self.settings.pool_recycle,
        }

        self.engine: AsyncEngine = create_async_engine(self.settings.url, **engine_kwargs)
        self.sync_engine: Engine = create_engine(self.settings.sync_url, **engine_kwargs)

    def _setup_session_factories(self) -> None:
        """Setup session factories for async and sync sessions."""
        self.async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.sync_session_factory: sessionmaker[Session] = sessionmaker(
            self.sync_engine,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def get_db(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async database session with automatic transaction management."""
        session = self.async_session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @contextmanager
    def get_sync_db(self) -> Generator[Session, None, None]:
        """Get a synchronous database session - used for migrations."""
        session = self.sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@lru_cache
def get_db_settings() -> DatabaseSettings:
    """Get database settings."""
    return DatabaseSettings()


# Global database instance - initialized lazily
_db_instance: Database | None = None


def get_database() -> Database:
    """Get the global database instance, creating it if necessary."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database.get_instance()
    return _db_instance


def get_db():
    """Get an async database session."""
    return get_database().get_db()


def get_sync_db():
    """Get a synchronous database session."""
    return get_database().get_sync_db()
