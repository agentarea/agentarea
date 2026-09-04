"""Archiving moves an artifact into the trash prefix instead of destroying it."""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import (
    ACTION_ARCHIVED,
    TRASH_PREFIX,
    ArtifactActor,
    ArtifactService,
)
from agentarea_common.testing.flows import MainFlow
from botocore.exceptions import ClientError


class FakeS3Client:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists
        self.copy_calls: list[dict] = []
        self.delete_calls: list[str] = []

    def copy_object(self, *, Bucket, Key, CopySource):  # noqa: N803
        self.copy_calls.append({"key": Key, "source": CopySource})

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.delete_calls.append(Key)

    def head_object(self, *, Bucket, Key):  # noqa: N803
        if self.exists:
            return {}
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")


class RecordingRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record(self, *, workspace_id, path, action, actor) -> None:
        self.events.append({"path": path, "action": action, "actor": actor})


def _service(client: FakeS3Client, recorder=None) -> ArtifactService:
    return ArtifactService(
        client=client,
        public_client=client,
        bucket="test-bucket",
        recorder=recorder,
        actor=ArtifactActor(user_id="user-1") if recorder else None,
    )


WS = "ws-1"


@pytest.mark.flow(MainFlow.FILES_ARTIFACTS)
async def test_archive_copies_into_trash_then_removes_the_original():
    client = FakeS3Client()
    svc = _service(client)

    trash_path = await svc.archive(WS, "wiki/index.md")

    assert trash_path.startswith(TRASH_PREFIX)
    assert trash_path.endswith("/wiki/index.md")
    # The copy must land before the delete, or archiving would destroy data.
    assert client.copy_calls[0]["source"] == {
        "Bucket": "test-bucket",
        "Key": f"workspaces/{WS}/wiki/index.md",
    }
    assert client.copy_calls[0]["key"] == f"workspaces/{WS}/{trash_path}"
    assert client.delete_calls == [f"workspaces/{WS}/wiki/index.md"]


async def test_archive_records_archived_not_deleted():
    recorder = RecordingRecorder()
    svc = _service(FakeS3Client(), recorder)

    await svc.archive(WS, "wiki/index.md")

    assert [e["action"] for e in recorder.events] == [ACTION_ARCHIVED]
    assert recorder.events[0]["path"] == "wiki/index.md"


async def test_archive_rejects_a_missing_file():
    svc = _service(FakeS3Client(exists=False))

    with pytest.raises(FileNotFoundError):
        await svc.archive(WS, "wiki/gone.md")


async def test_archive_twice_keeps_both_copies():
    client = FakeS3Client()
    svc = _service(client)

    first = await svc.archive(WS, "wiki/index.md")
    second = await svc.archive(WS, "wiki/index.md")

    assert first != second


async def test_copy_moves_between_two_workspace_paths():
    client = FakeS3Client()
    svc = _service(client)

    await svc.copy(WS, "a/from.txt", "b/to.txt")

    assert client.copy_calls == [
        {
            "key": f"workspaces/{WS}/b/to.txt",
            "source": {"Bucket": "test-bucket", "Key": f"workspaces/{WS}/a/from.txt"},
        }
    ]
