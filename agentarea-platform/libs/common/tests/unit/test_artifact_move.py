"""Moving an artifact relocates it copy-first and records a move, not a delete."""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import (
    ACTION_MOVED,
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
async def test_move_copies_to_the_destination_then_removes_the_source():
    client = FakeS3Client()
    svc = _service(client)

    await svc.move(WS, "wiki/index.md", "docs/index.md")

    # The copy must land before the delete, or a move would destroy data.
    assert client.copy_calls == [
        {
            "key": f"workspaces/{WS}/docs/index.md",
            "source": {"Bucket": "test-bucket", "Key": f"workspaces/{WS}/wiki/index.md"},
        }
    ]
    assert client.delete_calls == [f"workspaces/{WS}/wiki/index.md"]


async def test_move_records_moved_at_the_destination():
    recorder = RecordingRecorder()
    svc = _service(FakeS3Client(), recorder)

    await svc.move(WS, "wiki/index.md", "docs/index.md")

    assert [e["action"] for e in recorder.events] == [ACTION_MOVED]
    assert recorder.events[0]["path"] == "docs/index.md"


async def test_move_rejects_a_missing_source():
    client = FakeS3Client(exists=False)
    svc = _service(client)

    with pytest.raises(FileNotFoundError):
        await svc.move(WS, "wiki/gone.md", "docs/gone.md")

    assert client.copy_calls == []
    assert client.delete_calls == []
