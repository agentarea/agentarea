"""A presigned workspace write is content-bound and recorded as the actor's write."""

from __future__ import annotations

import base64
import hashlib

import pytest
from agentarea_common.artifacts import (
    ACTION_CREATED,
    ACTION_MODIFIED,
    ArtifactActor,
    ArtifactService,
)
from botocore.exceptions import ClientError

SHA = hashlib.sha256(b"# wiki\n").hexdigest()
SHA_B64 = base64.b64encode(bytes.fromhex(SHA)).decode("ascii")


class FakeS3Client:
    def __init__(self, exists: bool = False) -> None:
        self.exists = exists
        self.presigned: list[dict] = []

    def head_object(self, *, Bucket, Key, **_):  # noqa: N803
        if self.exists:
            return {}
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
        self.presigned.append({"operation": operation, "params": Params, "expires": ExpiresIn})
        return f"https://store.example/{Params['Key']}?sig=1"


class RecordingRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record(self, *, workspace_id, path, action, actor) -> None:
        self.events.append({"path": path, "action": action, "actor": actor})


def _service(client: FakeS3Client, recorder: RecordingRecorder) -> ArtifactService:
    return ArtifactService(
        client=client,
        public_client=client,
        bucket="test-bucket",
        recorder=recorder,
        actor=ArtifactActor(user_id="user-1"),
    )


@pytest.mark.asyncio
async def test_the_url_is_bound_to_the_declared_content() -> None:
    client = FakeS3Client()

    put = await _service(client, RecordingRecorder()).authorize_put(
        "ws-1", "wiki/index.md", sha256_hex=SHA
    )

    params = client.presigned[0]["params"]
    assert client.presigned[0]["operation"] == "put_object"
    assert params["Key"] == "workspaces/ws-1/wiki/index.md"
    assert params["ChecksumSHA256"] == SHA_B64
    assert params["ContentType"] == "text/markdown"
    assert put.url == "https://store.example/workspaces/ws-1/wiki/index.md?sig=1"
    assert put.headers == {
        "Content-Type": "text/markdown",
        "x-amz-checksum-sha256": SHA_B64,
        "x-amz-meta-sha256": SHA,
    }


@pytest.mark.asyncio
async def test_the_upload_carries_the_digest_downloads_verify_against() -> None:
    """``stream`` refuses an object without ``sha256`` metadata, so a presigned
    write that omitted it would upload fine and then 404 on every download."""
    client = FakeS3Client()

    await _service(client, RecordingRecorder()).authorize_put(
        "ws-1", "wiki/index.md", sha256_hex=SHA
    )

    assert client.presigned[0]["params"]["Metadata"] == {"sha256": SHA}


@pytest.mark.asyncio
async def test_the_url_expires_quickly() -> None:
    client = FakeS3Client()

    put = await _service(client, RecordingRecorder()).authorize_put(
        "ws-1", "wiki/index.md", sha256_hex=SHA
    )

    assert put.expires_in == client.presigned[0]["expires"] <= 600


@pytest.mark.asyncio
@pytest.mark.parametrize(("exists", "action"), [(False, ACTION_CREATED), (True, ACTION_MODIFIED)])
async def test_the_write_is_recorded_for_the_actor(exists: bool, action: str) -> None:
    recorder = RecordingRecorder()

    await _service(FakeS3Client(exists=exists), recorder).authorize_put(
        "ws-1", "wiki/index.md", sha256_hex=SHA
    )

    assert [(e["path"], e["action"], e["actor"].user_id) for e in recorder.events] == [
        ("wiki/index.md", action, "user-1")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "abc", SHA.upper(), SHA + "0"])
async def test_a_malformed_digest_is_refused_before_signing(bad: str) -> None:
    client = FakeS3Client()
    recorder = RecordingRecorder()

    with pytest.raises(ValueError):
        await _service(client, recorder).authorize_put("ws-1", "wiki/index.md", sha256_hex=bad)

    assert client.presigned == []
    assert recorder.events == []
