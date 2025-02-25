import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator, Optional


class DatabaseSettings(BaseSettings):
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "aiagents"

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"


class AWSSettings(BaseSettings):
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str
    AWS_ENDPOINT_URL: Optional[str] = None
    PUBLIC_S3_ENDPOINT: Optional[str] = None  # Public endpoint for frontend access

    class Config:
        env_file = ".env"


class AppSettings(BaseSettings):
    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False

    class Config:
        env_file = ".env"


@lru_cache()
def get_db_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache()
def get_aws_settings() -> AWSSettings:
    return AWSSettings()


@lru_cache()
def get_app_settings() -> AppSettings:
    return AppSettings()


class Database:
    def __init__(self, db_settings: DatabaseSettings = None):
        self.db_settings = db_settings or get_db_settings()
        self.engine = create_engine(
            self.db_settings.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=30,
            max_overflow=10,
            pool_size=5,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def get_db(self) -> Generator[Session, None, None]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


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
