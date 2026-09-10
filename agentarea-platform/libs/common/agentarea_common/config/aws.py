"""S3 configuration and client factory."""

from functools import lru_cache
from typing import Any

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class AWSSettings(BaseAppSettings):
    """Object storage configuration.

    Credentials are handed to boto3 explicitly rather than left to its default
    environment chain, so these carry the ``AGENTAREA_S3_`` prefix like every
    other setting we own.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_S3_")

    ACCESS_KEY: str = "minioadmin"
    SECRET_KEY: str = "minioadmin"  # noqa: S105
    REGION: str = "us-east-1"
    BUCKET: str = "ai-agents-bucket"
    ARTIFACTS_BUCKET: str = "artifacts"
    ENDPOINT: str | None = None
    PUBLIC_ENDPOINT: str | None = None  # Public endpoint for frontend access


@lru_cache
def get_aws_settings() -> AWSSettings:
    """Get object storage settings."""
    return AWSSettings()


def _build_s3_client(endpoint_url: str | None) -> Any:
    import boto3
    from botocore.client import Config

    aws_settings = get_aws_settings()
    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.ACCESS_KEY,
        aws_secret_access_key=aws_settings.SECRET_KEY,
        region_name=aws_settings.REGION,
        endpoint_url=endpoint_url,
        config=Config(signature_version="s3v4"),
    )


def get_s3_client() -> Any:
    """S3 client for internal ops (put/get/list/delete) against ``AGENTAREA_S3_ENDPOINT``.

    Forces SigV4 so signatures validate against RustFS and modern AWS
    regions alike (SigV2 is rejected by RustFS and deprecated on AWS).
    """
    return _build_s3_client(get_aws_settings().ENDPOINT)


def get_s3_public_client() -> Any:
    """S3 client used only for generating presigned URLs.

    In production the internal endpoint is reachable only from inside the
    cluster (``rustfs:9000``) while presigned URLs must point at a host
    external callers can reach (``localhost:9000`` dev, S3 public endpoint
    in prod). If ``AGENTAREA_S3_PUBLIC_ENDPOINT`` is unset, falls back to
    ``AGENTAREA_S3_ENDPOINT``.
    """
    s = get_aws_settings()
    return _build_s3_client(s.PUBLIC_ENDPOINT or s.ENDPOINT)
