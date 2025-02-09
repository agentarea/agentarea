import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class Settings(BaseSettings):
    # AWS Settings
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME")
    aws_endpoint_url: str = os.getenv("AWS_ENDPOINT_URL")

    # Database Settings
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@db:5432/aiagents"
    )

    # App Settings
    app_name: str = "AI Agent Service"
    debug: bool = os.getenv("DEBUG", "False").lower() == "true"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_s3_client():
    settings = get_settings()
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )


# Database setup
settings = get_settings()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
