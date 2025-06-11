from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Any, Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# ============================================================================
# Base Settings Classes
# ============================================================================


class BaseAppSettings(BaseSettings):
    """Base settings class with common configuration."""

    model_config = {"env_file": ".env", "extra": "ignore"}


# ============================================================================
# Broker Settings
# ============================================================================


class BrokerSettings(BaseAppSettings):
    """Base broker configuration."""

    BROKER_TYPE: Literal["redis", "kafka"] = "redis"


class RedisSettings(BrokerSettings):
    """Redis broker configuration."""

    REDIS_URL: str = "redis://localhost:6379"


class KafkaSettings(BrokerSettings):
    """Kafka broker configuration."""

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_PREFIX: str = ""


# ============================================================================
# Database Settings
# ============================================================================


class DatabaseSettings(BaseAppSettings):
    """Database configuration and connection settings."""

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


# ============================================================================
# AWS Settings
# ============================================================================


class AWSSettings(BaseAppSettings):
    """AWS and S3 configuration."""

    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "ai-agents-bucket"
    AWS_ENDPOINT_URL: str | None = None
    PUBLIC_S3_ENDPOINT: str | None = None  # Public endpoint for frontend access


# ============================================================================
# Application Settings
# ============================================================================


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False


class SecretManagerSettings(BaseAppSettings):
    """Secret manager configuration."""

    SECRET_MANAGER_TYPE: str = "local"
    SECRET_MANAGER_ENDPOINT: str | None = None
    SECRET_MANAGER_ACCESS_KEY: str | None = None
    SECRET_MANAGER_SECRET_KEY: str | None = None


# ============================================================================
# MCP Settings
# ============================================================================


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    MCP_MANAGER_URL: str = "http://mcp-manager:8000"
    MCP_CLIENT_TIMEOUT: int = 30
    REDIS_URL: str = "redis://redis:6379"


# ============================================================================
# MCP Manager Settings
# ============================================================================


class MCPManagerSettings(BaseSettings):
    """MCP Manager service configuration."""
    
    base_url: str = "http://localhost:8001"
    api_key: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    
    class Config:
        env_prefix = "MCP_MANAGER_"


# ============================================================================
# Main Settings
# ============================================================================


class Settings(BaseSettings):
    """Main application settings container."""

    database: DatabaseSettings
    aws: AWSSettings
    app: AppSettings
    secret_manager: SecretManagerSettings
    broker: RedisSettings | KafkaSettings
    mcp: MCPSettings
    mcp_manager: MCPManagerSettings = Field(default_factory=MCPManagerSettings)

    model_config = {"env_file": ".env", "extra": "ignore"}


# ============================================================================
# Settings Factory Functions
# ============================================================================


@lru_cache
def get_settings() -> Settings:
    """Get the main application settings."""
    broker_type = BrokerSettings().BROKER_TYPE
    broker = RedisSettings() if broker_type == "redis" else KafkaSettings()

    return Settings(
        database=DatabaseSettings(),
        aws=AWSSettings(),
        app=AppSettings(),
        secret_manager=SecretManagerSettings(),
        broker=broker,
        mcp=MCPSettings(),
    )


@lru_cache
def get_db_settings() -> DatabaseSettings:
    """Get database settings."""
    return DatabaseSettings()


@lru_cache
def get_aws_settings() -> AWSSettings:
    """Get AWS settings."""
    return AWSSettings()


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    """Get secret manager settings."""
    return SecretManagerSettings()


# ============================================================================
# Database Connection Manager
# ============================================================================


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


# ============================================================================
# AWS Client Factory
# ============================================================================


def get_s3_client() -> Any:
    """Create and return an S3 client with configured settings."""
    import boto3

    aws_settings = get_aws_settings()

    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=aws_settings.AWS_SECRET_ACCESS_KEY,
        region_name=aws_settings.AWS_REGION,
        endpoint_url=aws_settings.AWS_ENDPOINT_URL,
    )


# ============================================================================
# Global Instances
# ============================================================================

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
