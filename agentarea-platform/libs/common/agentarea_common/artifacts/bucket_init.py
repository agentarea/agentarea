"""Create the storage buckets and give them the browser CORS allowlist.

Browsers upload straight to the object store with presigned URLs, so each
bucket needs a CORS rule naming the app origins. The Helm chart's bucket-init
hook does this in Kubernetes; docker compose runs this module as its init step:

    python -m agentarea_common.artifacts.bucket_init
"""

from __future__ import annotations

import logging
import os
from typing import Any

from botocore.exceptions import ClientError

from agentarea_common.config.aws import get_s3_client

logger = logging.getLogger(__name__)

_ALREADY_THERE = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


def parse_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def init_buckets(client: Any, buckets: list[str], cors_origins: list[str]) -> None:
    if "*" in cors_origins:
        raise ValueError("storage CORS needs explicit origins, not '*'")
    for bucket in buckets:
        try:
            client.create_bucket(Bucket=bucket)
            logger.info("Created bucket %s", bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in _ALREADY_THERE:
                raise
        if cors_origins:
            client.put_bucket_cors(
                Bucket=bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": cors_origins,
                            "AllowedMethods": ["GET", "PUT", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
            logger.info("Bucket %s allows browser uploads from %s", bucket, cors_origins)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    buckets = parse_list(os.environ["STORAGE_BUCKETS"])
    if not buckets:
        raise ValueError("STORAGE_BUCKETS names no bucket")
    init_buckets(
        get_s3_client(), buckets, parse_list(os.environ.get("STORAGE_CORS_ALLOWED_ORIGINS", ""))
    )


if __name__ == "__main__":
    main()
