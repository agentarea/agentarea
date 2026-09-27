"""A path that can never name an object is refused before it reaches S3."""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import ArtifactService, InvalidArtifactPathError


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
