from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseSettings(BaseSettings):
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
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


class AWSSettings(BaseSettings):
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str
    AWS_ENDPOINT_URL: str | None = None
    PUBLIC_S3_ENDPOINT: str | None = None  # Public endpoint for frontend access

    class Config:
        env_file = ".env"


class AppSettings(BaseSettings):
    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False

    class Config:
        env_file = ".env"


class SecretManagerSettings(BaseSettings):
    SECRET_MANAGER_TYPE: str = "local"
    SECRET_MANAGER_ENDPOINT: str | None = None
    SECRET_MANAGER_ACCESS_KEY: str | None = None
    SECRET_MANAGER_SECRET_KEY: str | None = None

    class Config:
        env_file = ".env"


class Settings(BaseSettings):
    database: DatabaseSettings
    aws: AWSSettings
    app: AppSettings
    secret_manager: SecretManagerSettings

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database=DatabaseSettings(),
        aws=AWSSettings(),
        app=AppSettings(),
        secret_manager=SecretManagerSettings(),
    )


@lru_cache
def get_db_settings() -> DatabaseSettings:
    return get_settings().database


@lru_cache
def get_aws_settings() -> AWSSettings:
    return get_settings().aws


@lru_cache
def get_app_settings() -> AppSettings:
    return get_settings().app


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    return get_settings().secret_manager


class Database:
    """Database connection manager."""

    _instance: Optional["Database"] = None

    def __new__(cls, settings: DatabaseSettings | None = None) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.settings = settings or get_db_settings()
            cls._instance.engine = create_async_engine(
                cls._instance.settings.url,
                echo=cls._instance.settings.echo,
                pool_size=cls._instance.settings.pool_size,
                max_overflow=cls._instance.settings.max_overflow,
            )
            cls._instance.sync_engine = create_engine(
                cls._instance.settings.sync_url,
                echo=cls._instance.settings.echo,
                pool_size=cls._instance.settings.pool_size,
                max_overflow=cls._instance.settings.max_overflow,
            )
            cls._instance.async_session_factory = async_sessionmaker(
                cls._instance.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            cls._instance.sync_session_factory = sessionmaker(
                cls._instance.sync_engine,
                expire_on_commit=False,
            )
        return cls._instance

    async def get_db(self) -> AsyncSession:
        """Get an async database session"""
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
        """Get a synchronous database session - used for migrations"""
        session = self.sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def get_s3_client():
    aws_settings = get_aws_settings()
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=aws_settings.AWS_SECRET_ACCESS_KEY,
        region_name=aws_settings.AWS_REGION,
        endpoint_url=aws_settings.AWS_ENDPOINT_URL,
    )


# Create global instances
db = Database()
get_db = db.get_db
get_sync_db = db.get_sync_db
