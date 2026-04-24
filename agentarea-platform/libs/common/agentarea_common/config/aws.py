"""AWS configuration and client factory."""

from functools import lru_cache
from typing import Any

from .base import BaseAppSettings


class AWSSettings(BaseAppSettings):
    """AWS and S3 configuration."""

    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"  # noqa: S105
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "ai-agents-bucket"
    ARTIFACTS_BUCKET_NAME: str = "artifacts"
    AWS_ENDPOINT_URL: str | None = None
    PUBLIC_S3_ENDPOINT: str | None = None  # Public endpoint for frontend access


@lru_cache
def get_aws_settings() -> AWSSettings:
    """Get AWS settings."""
    return AWSSettings()


def get_s3_client() -> Any:
    """Create and return an S3 client with configured settings.

    Forces SigV4 so presigned URLs validate against RustFS and modern AWS
    regions alike (SigV2 is rejected by RustFS and deprecated on AWS).
    """
    import boto3
    from botocore.client import Config

    aws_settings = get_aws_settings()

    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=aws_settings.AWS_SECRET_ACCESS_KEY,
        region_name=aws_settings.AWS_REGION,
        endpoint_url=aws_settings.AWS_ENDPOINT_URL,
        config=Config(signature_version="s3v4"),
    )
