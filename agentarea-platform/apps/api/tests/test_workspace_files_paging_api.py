"""Folder moves and the workspace listing see every object, not the first 1000.

Both called ``ArtifactService.list`` with its default ``max_items=1000``. A
folder of 1005 files moved 1000 and left five at the old path, reporting
success; the listing returned 1000 objects as if they were the workspace, and
since task output was cut before it was filtered out, a workspace with enough
task files showed none of a person's own.

The real ``ArtifactService`` runs here over an in-memory object store that
pages the way S3 does: 1000 entries a page, a common prefix counting as one.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import files
from agentarea_common.artifacts import ArtifactService
from botocore.exceptions import ClientError

WS = SimpleNamespace(workspace_id="ws-1", user_id="user-1")
ROOT = "workspaces/ws-1/"
PAGE = 1000


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.listed_prefixes: list[str] = []

    def put_object(self, Bucket, Key, Body=b"", **_):  # noqa: N803 - boto3's keyword names
        self.objects[Key] = Body

    def head_object(self, Bucket, Key, **_):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key]), "Metadata": {}}

    def copy_object(self, Bucket, Key, CopySource, **_):  # noqa: N803
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, Bucket, Key, **_):  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, _operation):
        return SimpleNamespace(paginate=self._paginate)

    def _paginate(self, Bucket, Prefix, Delimiter=None):  # noqa: N803
        self.listed_prefixes.append(Prefix)
        entries: list[tuple[str, str]] = []  # (sort key, kind)
        folders: set[str] = set()
        for key in sorted(k for k in self.objects if k.startswith(Prefix)):
            rest = key[len(Prefix) :]
            if Delimiter and Delimiter in rest:
                folder = Prefix + rest.split(Delimiter, 1)[0] + Delimiter
                if folder not in folders:
                    folders.add(folder)
                    entries.append((folder, "folder"))
            else:
                entries.append((key, "object"))
        for start in range(0, len(entries), PAGE):
            chunk = entries[start : start + PAGE]
            yield {
                "Contents": [
                    {"Key": key, "Size": len(self.objects[key])}
                    for key, kind in chunk
                    if kind == "object"
                ],
                "CommonPrefixes": [{"Prefix": key} for key, kind in chunk if kind == "folder"],
            }

    def keys_under(self, path: str) -> list[str]:
        return [k[len(ROOT) :] for k in self.objects if k.startswith(ROOT + path)]


@pytest.fixture
def store(monkeypatch) -> _FakeS3:
    s3 = _FakeS3()

    def service(**_kwargs) -> ArtifactService:
        return ArtifactService(client=s3, public_client=s3, bucket="bucket")

    monkeypatch.setattr(files, "ArtifactService", service)
    monkeypatch.setattr(files, "_get_artifact_service", service)
    return s3


def _fill(store: _FakeS3, folder: str, count: int) -> None:
    for i in range(count):
        store.objects[f"{ROOT}{folder}/f{i:05d}.txt"] = b"x"


async def _listing() -> files.WorkspaceFileListResponse:
    return await files.list_workspace_files(WS, SimpleNamespace(list=AsyncMock(return_value=[])))


@pytest.mark.asyncio
async def test_moving_a_folder_moves_every_file_past_the_first_page(store) -> None:
    _fill(store, "big", PAGE + 5)

    result = await files.move_workspace_file(
        files.MoveWorkspaceFileRequest(source="big", destination="moved"), WS
    )

    assert result.moved == PAGE + 5
    assert store.keys_under("big/") == []
    assert len(store.keys_under("moved/")) == PAGE + 5


@pytest.mark.asyncio
async def test_the_listing_returns_every_file_past_the_first_page(store) -> None:
    _fill(store, "big", PAGE + 5)

    listing = await _listing()

    assert len(listing.files) == PAGE + 5
    assert listing.truncated is False


@pytest.mark.asyncio
async def test_task_output_does_not_crowd_a_persons_files_out_of_the_listing(store) -> None:
    _fill(store, "tasks/t-1/workspace", PAGE + 500)
    _fill(store, ".trash/20260826T101500.000000Z", 10)
    _fill(store, "wiki", 3)

    listing = await _listing()

    assert [f.path for f in listing.files] == [f"wiki/f{i:05d}.txt" for i in range(3)]
    assert listing.truncated is False
    # Reserved folders are skipped by name, never walked.
    assert not any(p.startswith(f"{ROOT}tasks/") for p in store.listed_prefixes)
    assert not any(p.startswith(f"{ROOT}.trash/") for p in store.listed_prefixes)


@pytest.mark.asyncio
async def test_a_listing_past_the_cap_says_it_was_cut_short(store, monkeypatch) -> None:
    monkeypatch.setattr(files, "MAX_LISTED_FILES", 3)
    _fill(store, "wiki", 5)

    listing = await _listing()

    assert len(listing.files) == 3
    assert listing.truncated is True


@pytest.mark.asyncio
async def test_a_listing_at_the_cap_is_complete(store, monkeypatch) -> None:
    monkeypatch.setattr(files, "MAX_LISTED_FILES", 4)
    _fill(store, "wiki", 3)
    store.objects[f"{ROOT}notes.md"] = b"x"

    listing = await _listing()

    assert sorted(f.path for f in listing.files) == ["notes.md"] + [
        f"wiki/f{i:05d}.txt" for i in range(3)
    ]
    assert listing.truncated is False
