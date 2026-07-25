"""ArtifactService records provenance events on writes and deletes."""

from __future__ import annotations

import logging

import pytest
from agentarea_common.artifacts import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    ACTOR_AGENT,
    ArtifactActor,
    ArtifactService,
)
from agentarea_common.testing.flows import MainFlow
from botocore.exceptions import ClientError


class FakeS3Client:
    """Minimal S3 stand-in; ``exists`` drives head_object behaviour."""

    def __init__(self, exists: bool = False) -> None:
        self.exists = exists
        self.put_calls: list[str] = []
        self.put_options: list[dict] = []
        self.delete_calls: list[str] = []

    def put_object(
        self, *, Bucket, Key, Body, ContentType, Metadata, ChecksumSHA256  # noqa: N803
    ):
        self.put_calls.append(Key)
        self.put_options.append(
            {"metadata": Metadata, "checksum_sha256": ChecksumSHA256}
        )

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.delete_calls.append(Key)

    def head_object(self, *, Bucket, Key):  # noqa: N803
        if self.exists:
            return {}
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")


class RecordingRecorder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict] = []

    async def record(self, *, workspace_id, path, action, actor) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.events.append(
            {
                "workspace_id": workspace_id,
                "path": path,
                "action": action,
                "actor": actor,
            }
        )


def _service(client: FakeS3Client, recorder=None, actor=None) -> ArtifactService:
    return ArtifactService(
        client=client,
        public_client=client,
        bucket="test-bucket",
        recorder=recorder,
        actor=actor,
    )


WS = "ws-1"
USER_ACTOR = ArtifactActor(user_id="user-1")
AGENT_ACTOR = ArtifactActor(
    user_id="owner-1", actor_type=ACTOR_AGENT, agent_id="agent-9", task_id="task-7"
)


@pytest.mark.flow(MainFlow.FILES_ARTIFACTS)
async def test_put_new_file_records_created():
    client = FakeS3Client(exists=False)
    recorder = RecordingRecorder()
    svc = _service(client, recorder, USER_ACTOR)

    await svc.put(WS, "shared/note.txt", b"hi")

    assert client.put_calls  # file actually written
    assert len(client.put_options[0]["metadata"]["sha256"]) == 64
    assert client.put_options[0]["checksum_sha256"]
    assert len(recorder.events) == 1
    ev = recorder.events[0]
    assert ev["action"] == ACTION_CREATED
    assert ev["path"] == "shared/note.txt"
    assert ev["actor"] is USER_ACTOR


async def test_put_existing_file_records_modified():
    client = FakeS3Client(exists=True)
    recorder = RecordingRecorder()
    svc = _service(client, recorder, AGENT_ACTOR)

    await svc.put(WS, "/tasks/task-7/out.txt", b"v2")

    assert len(recorder.events) == 1
    ev = recorder.events[0]
    assert ev["action"] == ACTION_MODIFIED
    assert ev["path"] == "tasks/task-7/out.txt"  # leading slash stripped
    assert ev["actor"].actor_type == ACTOR_AGENT


async def test_delete_records_deleted():
    client = FakeS3Client(exists=True)
    recorder = RecordingRecorder()
    svc = _service(client, recorder, USER_ACTOR)

    await svc.delete(WS, "shared/note.txt")

    assert client.delete_calls
    assert recorder.events[0]["action"] == ACTION_DELETED


async def test_recording_failure_does_not_break_put(caplog):
    client = FakeS3Client(exists=False)
    svc = _service(client, RecordingRecorder(fail=True), USER_ACTOR)

    with caplog.at_level(logging.ERROR):
        result = await svc.put(WS, "shared/note.txt", b"hi")

    assert result.path == "shared/note.txt"  # operation still succeeds
    assert client.put_calls
    assert any("Failed to record artifact event" in r.message for r in caplog.records)


async def test_no_recorder_skips_audit_and_extra_head():
    client = FakeS3Client(exists=False)
    svc = _service(client)  # no recorder/actor

    await svc.put(WS, "shared/note.txt", b"hi")

    # exists() short-circuits when no recorder, so head_object is never used
    # to classify created vs modified.
    assert client.put_calls
