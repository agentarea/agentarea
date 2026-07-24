"""Streaming integrity contract for workspace artifacts."""

from __future__ import annotations

import io
from typing import Any

import pytest
from agentarea_common.artifacts import ArtifactIntegrityError, ArtifactService
from botocore.exceptions import ClientError


class _Body(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class _S3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.last_body: _Body | None = None

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.objects[kwargs["Key"]] = {
            "body": kwargs["Body"],
            "content_type": kwargs["ContentType"],
            "metadata": kwargs.get("Metadata") or {},
        }
        return {"ETag": '"etag"'}

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        try:
            value = self.objects[Key]
        except KeyError as exc:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject") from exc
        self.last_body = _Body(value["body"])
        return {
            "Body": self.last_body,
            "ContentLength": len(value["body"]),
            "ContentType": value["content_type"],
            "Metadata": value["metadata"],
        }


@pytest.mark.asyncio
async def test_stream_reads_bounded_chunks_and_verifies_digest() -> None:
    client = _S3()
    service = ArtifactService(client=client, public_client=client, bucket="artifacts")
    await service.put("ws", "shared/result.bin", b"0123456789")

    chunks, content_type, size = await service.stream(
        "ws", "shared/result.bin", chunk_size=3
    )

    assert b"".join([chunk async for chunk in chunks]) == b"0123456789"
    assert content_type == "application/octet-stream"
    assert size == 10
    assert client.last_body is not None
    assert all(0 < read_size <= 3 for read_size in client.last_body.read_sizes)


@pytest.mark.asyncio
async def test_stream_rejects_corrupted_artifact() -> None:
    client = _S3()
    service = ArtifactService(client=client, public_client=client, bucket="artifacts")
    await service.put("ws", "shared/result.bin", b"trusted")
    client.objects["workspaces/ws/shared/result.bin"]["body"] = b"altered"

    with pytest.raises(ArtifactIntegrityError, match="verification failed"):
        await service.stream("ws", "shared/result.bin", chunk_size=2)


@pytest.mark.asyncio
async def test_stream_rejects_object_without_integrity_digest() -> None:
    client = _S3()
    client.objects["workspaces/ws/shared/unknown.bin"] = {
        "body": b"unverified",
        "content_type": "application/octet-stream",
        "metadata": {},
    }
    service = ArtifactService(client=client, public_client=client, bucket="artifacts")

    with pytest.raises(ArtifactIntegrityError, match="digest is missing"):
        await service.stream("ws", "shared/unknown.bin")
