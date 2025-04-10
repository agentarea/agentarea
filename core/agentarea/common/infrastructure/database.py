from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


class DatabaseSettings(BaseSettings):
    """Database configuration settings"""
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "aiagents"
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False

    @property
    def url(self) -> str:
        """Get the database URL"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


class Database:
    """Database connection manager"""
    _instance: Optional['Database'] = None

    def __new__(cls, settings: Optional[DatabaseSettings] = None) -> 'Database':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.settings = settings or DatabaseSettings()
            cls._instance.engine = create_async_engine(
                cls._instance.settings.url,
                echo=cls._instance.settings.echo,
                pool_size=cls._instance.settings.pool_size,
                max_overflow=cls._instance.settings.max_overflow,
            )
            cls._instance.session_factory = sessionmaker(
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
