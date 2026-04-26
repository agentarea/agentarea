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


def _build_s3_client(endpoint_url: str | None) -> Any:
    import boto3
    from botocore.client import Config

    aws_settings = get_aws_settings()
    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=aws_settings.AWS_SECRET_ACCESS_KEY,
        region_name=aws_settings.AWS_REGION,
        endpoint_url=endpoint_url,
        config=Config(signature_version="s3v4"),
    )


def get_s3_client() -> Any:
    """S3 client for internal ops (put/get/list/delete) against ``AWS_ENDPOINT_URL``.

    Forces SigV4 so signatures validate against RustFS and modern AWS
    regions alike (SigV2 is rejected by RustFS and deprecated on AWS).
    """
    return _build_s3_client(get_aws_settings().AWS_ENDPOINT_URL)


def get_s3_public_client() -> Any:
    """S3 client used only for generating presigned URLs.

    In production the internal endpoint is reachable only from inside the
    cluster (``rustfs:9000``) while presigned URLs must point at a host
    external callers can reach (``localhost:9000`` dev, S3 public endpoint
    in prod). If ``PUBLIC_S3_ENDPOINT`` is unset, falls back to
    ``AWS_ENDPOINT_URL``.
    """
    s = get_aws_settings()
    return _build_s3_client(s.PUBLIC_S3_ENDPOINT or s.AWS_ENDPOINT_URL)
