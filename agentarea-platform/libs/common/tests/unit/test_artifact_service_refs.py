"""Ref-based storage primitives on ArtifactService: presigned PUT, copy, head."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from agentarea_common.artifacts import ArtifactService
from botocore.exceptions import ClientError


class _RefsS3:
    """In-memory S3 stand-in exercising presigned/copy/head signing paths."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.presigned_calls: list[dict[str, Any]] = []
        self.copy_calls: list[dict[str, Any]] = []
        self.head_calls: list[dict[str, Any]] = []

    def generate_presigned_url(self, operation: str, *, Params: dict, ExpiresIn: int):  # noqa: N803
        self.presigned_calls.append(
            {"operation": operation, "params": dict(Params), "expires_in": ExpiresIn}
        )
        return f"https://s3.example/{operation}?key={Params['Key']}"

    def copy_object(self, **kwargs: Any):
        self.copy_calls.append(dict(kwargs))
        source = kwargs["CopySource"]
        source_key = source["Key"] if isinstance(source, dict) else str(source)
        src = self.objects[source_key]
        etag = "dest-etag"
        self.objects[kwargs["Key"]] = {
            "body": src["body"],
            "etag": etag,
            "metadata": dict(kwargs.get("Metadata") or {}),
            "content_type": kwargs.get("ContentType"),
        }
        return {"CopyObjectResult": {"ETag": f'"{etag}"'}}

    def head_object(self, *, Bucket: str, Key: str, **kwargs: Any):  # noqa: N803
        self.head_calls.append({"Key": Key, **kwargs})
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        value = self.objects[Key]
        return {
            "ContentLength": len(value["body"]),
            "ETag": f'"{value["etag"]}"',
            "Metadata": value["metadata"],
            "ContentType": value["content_type"],
        }


def _service(client: _RefsS3, public_client: _RefsS3 | None = None) -> ArtifactService:
    return ArtifactService(
        client=client,
        public_client=public_client or client,
        bucket="artifacts",
    )


@pytest.mark.asyncio
async def test_presigned_put_url_binds_checksum_and_content_type_when_given() -> None:
    client = _RefsS3()
    svc = _service(client)

    url = await svc.presigned_put_url(
        "ws-1",
        "staging/upload-1/report.csv",
        content_type="text/csv",
        sha256_b64="Zm9vYmFy",
        expires_in=120,
    )

    assert url
    call = client.presigned_calls[0]
    assert call["operation"] == "put_object"
    assert call["params"]["Bucket"] == "artifacts"
    assert call["params"]["Key"] == "workspaces/ws-1/staging/upload-1/report.csv"
    assert call["params"]["ChecksumSHA256"] == "Zm9vYmFy"
    assert call["params"]["ContentType"] == "text/csv"
    assert call["expires_in"] == 120


@pytest.mark.asyncio
async def test_presigned_put_url_omits_optional_params_when_absent() -> None:
    client = _RefsS3()
    svc = _service(client)

    await svc.presigned_put_url("ws-1", "staging/upload-1/report.csv")

    call = client.presigned_calls[0]
    assert "ChecksumSHA256" not in call["params"]
    assert "ContentType" not in call["params"]


@pytest.mark.asyncio
async def test_presigned_put_url_signs_via_public_client() -> None:
    internal = _RefsS3()
    public = _RefsS3()
    svc = _service(internal, public)

    await svc.presigned_put_url("ws-1", "staging/upload-1/report.csv", sha256_b64="abc")

    assert public.presigned_calls
    assert not internal.presigned_calls


@pytest.mark.asyncio
async def test_copy_object_replaces_metadata_and_returns_dest_etag() -> None:
    client = _RefsS3()
    svc = _service(client)
    body = b"copy-body"
    sha = hashlib.sha256(body).hexdigest()
    client.objects["workspaces/ws-1/staging/c/src.bin"] = {
        "body": body,
        "etag": "src-etag",
        "metadata": {},
        "content_type": None,
    }

    etag = await svc.copy_object(
        "ws-1",
        "staging/c/src.bin",
        "shared/dst.bin",
        content_type="text/plain",
        sha256_hex=sha,
    )

    assert etag == "dest-etag"
    call = client.copy_calls[0]
    assert call["MetadataDirective"] == "REPLACE"
    assert call["Metadata"]["sha256"] == sha
    assert call["ContentType"] == "text/plain"
    assert call["CopySource"] == {
        "Bucket": "artifacts",
        "Key": "workspaces/ws-1/staging/c/src.bin",
    }
    assert call["Key"] == "workspaces/ws-1/shared/dst.bin"
    assert client.objects["workspaces/ws-1/shared/dst.bin"]["metadata"]["sha256"] == sha


@pytest.mark.asyncio
async def test_head_returns_size_content_type_and_metadata() -> None:
    client = _RefsS3()
    svc = _service(client)
    body = b"headable"
    sha = hashlib.sha256(body).hexdigest()
    client.objects["workspaces/ws-1/shared/h.bin"] = {
        "body": body,
        "etag": "e",
        "metadata": {"sha256": sha},
        "content_type": "text/plain",
    }

    info = await svc.head("ws-1", "shared/h.bin")

    assert info is not None
    assert info["size"] == len(body)
    assert info["content_type"] == "text/plain"
    assert info["metadata"]["sha256"] == sha


@pytest.mark.asyncio
async def test_head_returns_none_when_object_missing() -> None:
    client = _RefsS3()
    svc = _service(client)

    assert await svc.head("ws-1", "shared/nope.bin") is None
