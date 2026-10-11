"""Restoring from the trash never destroys the file that took the path since (#711)."""

from __future__ import annotations

import pytest
from agentarea_common.artifacts import (
    TRASH_PREFIX,
    ArtifactService,
    WorkspaceConflictError,
)
from agentarea_common.testing.flows import MainFlow
from botocore.exceptions import ClientError

WS = "ws-1"
PREFIX = f"workspaces/{WS}/"


class InMemoryS3:
    """Just enough of S3 to run the real service: keys map to bytes."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Key, Body=b"", **_):  # noqa: N803
        self.objects[Key] = Body

    def head_object(self, *, Key, **_):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key]), "Metadata": {}}

    def copy_object(self, *, Key, CopySource, **_):  # noqa: N803
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, *, Key, **_):  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, _operation):
        store = self

        class Paginator:
            def paginate(self, *, Prefix, **_):  # noqa: N803
                keys = sorted(key for key in store.objects if key.startswith(Prefix))
                yield {"Contents": [{"Key": k, "Size": len(store.objects[k])} for k in keys]}

        return Paginator()

    def files(self) -> dict[str, bytes]:
        return {key.removeprefix(PREFIX): body for key, body in self.objects.items()}

    def trash(self) -> dict[str, bytes]:
        return {path: body for path, body in self.files().items() if path.startswith(TRASH_PREFIX)}


def _service(store: InMemoryS3) -> ArtifactService:
    return ArtifactService(client=store, public_client=store, bucket="b")


@pytest.mark.flow(MainFlow.FILES_ARTIFACTS)
async def test_restore_archives_a_newer_file_at_the_path_instead_of_overwriting_it():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "notes.md", b"v1")
    archived_v1 = await svc.archive(WS, "notes.md")
    await svc.put(WS, "notes.md", b"v2")

    restored = await svc.restore(WS, archived_v1)

    assert restored.path == "notes.md"
    assert restored.restored_from == archived_v1
    assert restored.archived_current is not None
    assert restored.archived_current.startswith(TRASH_PREFIX)
    assert restored.archived_current.endswith("/notes.md")
    files = store.files()
    assert files["notes.md"] == b"v1"
    # v2 is in the trash under the same layout a delete produces, so it can come back too.
    assert store.trash() == {restored.archived_current: b"v2"}

    restored_again = await svc.restore(WS, restored.archived_current)

    assert store.files()["notes.md"] == b"v2"
    assert store.trash() == {restored_again.archived_current: b"v1"}


async def test_restore_onto_a_free_path_archives_nothing():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "wiki/index.md", b"v1")
    archived = await svc.archive(WS, "wiki/index.md")

    restored = await svc.restore(WS, archived)

    assert restored.path == "wiki/index.md"
    assert restored.archived_current is None
    assert store.files() == {"wiki/index.md": b"v1"}


async def test_restore_refuses_a_path_whose_parent_is_now_a_file():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "wiki/index.md", b"v1")
    archived = await svc.archive(WS, "wiki/index.md")
    await svc.put(WS, "wiki", b"a file where the folder was")
    before = dict(store.objects)

    with pytest.raises(WorkspaceConflictError):
        await svc.restore(WS, archived)

    assert store.objects == before


async def test_restore_refuses_a_path_that_is_now_a_folder():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "notes", b"v1")
    archived = await svc.archive(WS, "notes")
    await svc.put(WS, "notes/today.md", b"inside a folder now")
    before = dict(store.objects)

    with pytest.raises(WorkspaceConflictError):
        await svc.restore(WS, archived)

    assert store.objects == before


async def test_a_folder_marker_comes_back_as_a_folder_marker():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "drafts/", b"")
    archived = await svc.archive(WS, "drafts/")

    restored = await svc.restore(WS, archived)

    assert restored.path == "drafts/"
    assert store.files() == {"drafts/": b""}


async def test_a_folder_marker_is_not_restored_over_a_file_of_the_same_name():
    store = InMemoryS3()
    svc = _service(store)
    await svc.put(WS, "drafts/", b"")
    archived = await svc.archive(WS, "drafts/")
    await svc.put(WS, "drafts", b"a file now")
    before = dict(store.objects)

    with pytest.raises(WorkspaceConflictError):
        await svc.restore(WS, archived)

    assert store.objects == before
