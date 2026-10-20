"""Expired days of the events read model, kept in the deployment's object store."""

import asyncio
from typing import IO, Any, Protocol


class EventArchive(Protocol):
    async def put(self, key: str, body: IO[bytes]) -> None:
        """Store ``body`` (a gzipped JSONL file) under ``key``, replacing what was there."""
        raise NotImplementedError


class S3EventArchive:
    def __init__(self, client: Any, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls) -> S3EventArchive:
        from agentarea_common.config.aws import get_aws_settings, get_s3_client

        return cls(get_s3_client(), get_aws_settings().BUCKET)

    async def put(self, key: str, body: IO[bytes]) -> None:
        await asyncio.to_thread(
            self._client.upload_fileobj,
            body,
            self._bucket,
            key,
            ExtraArgs={"ContentType": "application/gzip"},
        )
