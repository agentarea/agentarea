"""A path that can never name an object is refused before it reaches S3."""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import ArtifactService, InvalidArtifactPathError
from agentarea_common.artifacts.service import MAX_WRITE_PATH_BYTES


class UnreachableS3Client:
    def __getattr__(self, name):
        raise AssertionError(f"S3 must not be called, got {name}")


def _service() -> ArtifactService:
    client = UnreachableS3Client()
    return ArtifactService(client=client, public_client=client, bucket="b")


@pytest.mark.parametrize(
    "path",
    ["a\rb.txt", "\x1bfile", "dir/\x01name", "tab\there", "del\x7f", "../escape", "a/../b"],
)
async def test_an_unrepresentable_path_is_refused_as_a_client_error(path: str) -> None:
    service = _service()
    for call in (service.exists, service.stream, service.archive, service.delete):
        with pytest.raises(InvalidArtifactPathError) as caught:
            await call("ws-1", path)
        assert caught.value.status_code == 422


def test_the_refusal_is_still_a_value_error() -> None:
    with pytest.raises(ValueError):
        _service()._key("ws-1", "a\rb")


WORKSPACE_ID = "0b6f5a4e-2c1d-4e8f-9a7b-3c5d6e7f8a9b"
KEY_PREFIX_BYTES = len(f"workspaces/{WORKSPACE_ID}/")


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("a" * 1100, id="ascii"),
        pytest.param("é" * (1024 - KEY_PREFIX_BYTES), id="two-byte"),
        pytest.param(f"dir/{'x' * (1021 - KEY_PREFIX_BYTES)}", id="one-byte-over"),
    ],
)
async def test_a_key_over_the_object_store_limit_is_refused_as_a_client_error(path: str) -> None:
    service = _service()
    for call in (service.exists, service.stream, service.archive, service.delete):
        with pytest.raises(InvalidArtifactPathError) as caught:
            await call(WORKSPACE_ID, path)
        assert caught.value.status_code == 422


def test_a_key_exactly_at_the_object_store_limit_is_accepted() -> None:
    path = "a" * (1024 - KEY_PREFIX_BYTES)

    assert len(_service()._key(WORKSPACE_ID, path).encode()) == 1024


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("a" * (MAX_WRITE_PATH_BYTES + 1), id="ascii"),
        pytest.param("é" * (MAX_WRITE_PATH_BYTES // 2 + 1), id="two-byte"),
    ],
)
async def test_a_write_past_the_archivable_bound_is_refused(path: str) -> None:
    service = _service()
    writes = (
        lambda: service.put(WORKSPACE_ID, path, b"x"),
        lambda: service.presigned_put_url(WORKSPACE_ID, path),
        lambda: service.copy(WORKSPACE_ID, "notes.md", path),
    )
    for write in writes:
        with pytest.raises(InvalidArtifactPathError) as caught:
            await write()
        assert caught.value.status_code == 422


class RecordingS3Client:
    def __init__(self) -> None:
        self.copied: list[tuple[str, str]] = []

    def head_object(self, **_):
        return {}

    def copy_object(self, *, Key, CopySource, **_):
        self.copied.append((CopySource["Key"], Key))

    def delete_object(self, **_):
        return None


async def test_a_file_written_at_the_bound_can_still_be_archived() -> None:
    client = RecordingS3Client()
    service = ArtifactService(client=client, public_client=client, bucket="b")
    path = "a" * MAX_WRITE_PATH_BYTES

    archived = await service.archive(WORKSPACE_ID, path)

    assert client.copied == [
        (f"workspaces/{WORKSPACE_ID}/{path}", f"workspaces/{WORKSPACE_ID}/{archived}")
    ]
