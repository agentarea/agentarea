"""Contract tests for immutable task workspace generations."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from typing import Any

import pytest
from agentarea_common.artifacts import (
    WorkspaceConflictError,
    WorkspaceQuotaError,
    WorkspaceRepository,
    WorkspaceValidationError,
    normalize_workspace_path,
)
from botocore.exceptions import ClientError


def _error(code: str, operation: str = "PutObject") -> ClientError:
    return ClientError({"Error": {"Code": code}}, operation)


class _Paginator:
    def __init__(self, client: FakeS3) -> None:
        self.client = client

    def paginate(
        self,
        *,
        Bucket: str,
        Prefix: str,
        Delimiter: str | None = None,  # noqa: N803
    ):
        matches = [
            (key, value)
            for key, value in sorted(self.client.objects.items())
            if key.startswith(Prefix)
        ]
        if Delimiter is not None:
            prefixes = sorted(
                {
                    f"{Prefix}{key[len(Prefix) :].split(Delimiter, 1)[0]}{Delimiter}"
                    for key, _ in matches
                    if Delimiter in key[len(Prefix) :]
                }
            )
            return [
                {
                    "CommonPrefixes": [
                        {"Prefix": prefix} for prefix in prefixes[offset : offset + 1000]
                    ]
                }
                for offset in range(0, len(prefixes), 1000)
            ] or [{}]
        contents = [{"Key": key, "Size": len(value["body"])} for key, value in matches]
        return [
            {"Contents": contents[offset : offset + 1000]}
            for offset in range(0, len(contents), 1000)
        ] or [{}]


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.put_kwargs: list[dict[str, Any]] = []
        self.copy_kwargs: list[dict[str, Any]] = []
        self.read_calls: list[tuple[str, int]] = []

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.put_kwargs.append(dict(kwargs))
        key = kwargs["Key"]
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _error("PreconditionFailed")
        if "IfMatch" in kwargs and (
            current is None or current["etag"] != str(kwargs["IfMatch"]).strip('"')
        ):
            raise _error("PreconditionFailed")
        body = kwargs["Body"]
        if not isinstance(body, bytes):
            body = body.read()
        etag = hashlib.md5(body).hexdigest()  # noqa: S324 - test S3 ETag stand-in
        self.objects[key] = {
            "body": body,
            "etag": etag,
            "metadata": dict(kwargs.get("Metadata") or {}),
            "content_type": kwargs.get("ContentType"),
        }
        return {"ETag": f'"{etag}"'}

    def get_object(self, *, Bucket: str, Key: str, **kwargs: Any):  # noqa: N803
        if Key not in self.objects:
            raise _error("NoSuchKey", "GetObject")
        value = self.objects[Key]
        if "IfMatch" in kwargs and value["etag"] != str(kwargs["IfMatch"]).strip('"'):
            raise _error("PreconditionFailed", "GetObject")
        body = io.BytesIO(value["body"])
        original_read = body.read

        def tracked_read(size: int = -1) -> bytes:
            self.read_calls.append((Key, size))
            return original_read(size)

        body.read = tracked_read  # type: ignore[method-assign]
        return {
            "Body": body,
            "ETag": f'"{value["etag"]}"',
            "ContentLength": len(value["body"]),
            "ContentType": value["content_type"],
        }

    def head_object(self, *, Bucket: str, Key: str, **kwargs: Any):  # noqa: N803
        if Key not in self.objects:
            raise _error("404", "HeadObject")
        value = self.objects[Key]
        return {
            "ContentLength": len(value["body"]),
            "ETag": f'"{value["etag"]}"',
            "Metadata": value["metadata"],
            "ContentType": value["content_type"],
        }

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self.copy_kwargs.append(dict(kwargs))
        source = kwargs["CopySource"]
        source_key = source["Key"] if isinstance(source, dict) else str(source)
        if source_key not in self.objects:
            raise _error("NoSuchKey", "CopyObject")
        src = self.objects[source_key]
        if kwargs.get("MetadataDirective") == "REPLACE":
            metadata = dict(kwargs.get("Metadata") or {})
            content_type = kwargs.get("ContentType")
        else:
            metadata = dict(src["metadata"])
            content_type = src["content_type"]
        body = src["body"]
        etag = hashlib.md5(body).hexdigest()  # noqa: S324 - test S3 ETag stand-in
        self.objects[kwargs["Key"]] = {
            "body": body,
            "etag": etag,
            "metadata": metadata,
            "content_type": content_type,
        }
        return {"CopyObjectResult": {"ETag": f'"{etag}"'}}

    def get_paginator(self, operation: str) -> _Paginator:
        assert operation == "list_objects_v2"
        return _Paginator(self)


@pytest.fixture
def repository() -> tuple[WorkspaceRepository, FakeS3]:
    client = FakeS3()
    return WorkspaceRepository(client=client, bucket="artifacts"), client


@pytest.mark.asyncio
async def test_nested_write_read_and_manifest_are_refs_only(repository):
    repo, client = repository

    ref = await repo.put_files(
        "ws-1",
        "task-1",
        {"reports/2026/q3.xlsx": b"xlsx-canary", "src/a.py": b"print(1)"},
        provenance={"source": "agent"},
    )

    assert ref.generation == 1
    assert ref.base_generation == 0
    assert ref.fencing_token == 1
    assert ref.manifest_uri.startswith("s3://artifacts/workspaces/ws-1/tasks/task-1/manifests/1-")
    assert [item.path for item in await repo.list("ws-1", "task-1")] == [
        "reports/2026/q3.xlsx",
        "src/a.py",
    ]
    assert await repo.get("ws-1", "task-1", "src/a.py") == (
        b"print(1)",
        "text/x-python",
    )

    pointer = client.objects["workspaces/ws-1/tasks/task-1/current.json"]["body"]
    assert b"xlsx-canary" not in pointer
    assert b"content_base64" not in pointer
    manifest_key = ref.manifest_uri.removeprefix("s3://artifacts/")
    manifest = json.loads(client.objects[manifest_key]["body"])
    assert manifest["entries"][0]["relative_path"] == "reports/2026/q3.xlsx"
    assert manifest["entries"][0]["object_uri"].startswith(
        "s3://artifacts/workspaces/ws-1/tasks/task-1/objects/"
    )
    assert "xlsx-canary" not in json.dumps(manifest)


@pytest.mark.asyncio
async def test_entry_with_ref_reads_that_committed_generation(repository):
    repo, _ = repository
    first = await repo.put("ws", "task", "result.txt", b"first")
    first_ref = await repo.current_manifest_ref("ws", "task")
    await repo.put("ws", "task", "result.txt", b"second")

    entry = await repo._entry("ws", "task", "result.txt", ref=first_ref)

    assert entry.sha256 == first.sha256
    assert entry.size == len(b"first")


@pytest.mark.asyncio
async def test_stream_reads_verified_object_in_bounded_chunks(repository):
    repo, client = repository
    body = b"0123456789"
    await repo.put("ws", "task", "result.bin", body, "application/octet-stream")

    chunks, content_type, size = await repo.stream("ws", "task", "result.bin", chunk_size=3)

    assert b"".join([chunk async for chunk in chunks]) == body
    assert content_type == "application/octet-stream"
    assert size == len(body)
    object_reads = [read_size for key, read_size in client.read_calls if "/objects/" in key]
    assert object_reads
    assert all(0 < read_size <= 3 for read_size in object_reads)


@pytest.mark.asyncio
async def test_stream_rejects_body_that_does_not_match_manifest(repository):
    repo, client = repository
    await repo.put("ws", "task", "result.bin", b"trusted")
    entry = await repo._entry("ws", "task", "result.bin")
    key = entry.object_uri.removeprefix("s3://artifacts/")
    client.objects[key]["body"] = b"altered"

    with pytest.raises(WorkspaceValidationError, match="verification failed"):
        await repo.stream("ws", "task", "result.bin", chunk_size=2)


@pytest.mark.asyncio
async def test_task_id_discovery_paginates_all_common_prefixes(repository):
    repo, client = repository
    for index in range(1001):
        key = f"workspaces/ws/tasks/task-{index:04d}/current.json"
        client.objects[key] = {
            "body": b"{}",
            "etag": "etag",
            "metadata": {},
            "content_type": "application/json",
        }
    client.objects["workspaces/ws/tasks/uncommitted/objects/deadbeef"] = {
        "body": b"partial",
        "etag": "etag",
        "metadata": {},
        "content_type": "application/octet-stream",
    }

    task_ids = await repo.list_task_ids("ws")

    assert len(task_ids) == 1001
    assert task_ids[0] == "task-0000"
    assert task_ids[-1] == "task-1000"
    assert "uncommitted" not in task_ids


@pytest.mark.asyncio
async def test_checksum_header_is_base64_encoded_digest(repository):
    repo, client = repository
    await repo.put("ws-1", "task-1", "file.bin", b"payload")

    object_put = next(call for call in client.put_kwargs if "/objects/" in str(call.get("Key")))
    assert object_put["ChecksumSHA256"] == base64.b64encode(
        hashlib.sha256(b"payload").digest()
    ).decode("ascii")
    assert isinstance(object_put["ChecksumSHA256"], str)


@pytest.mark.asyncio
async def test_get_object_ref_reads_verified_object_not_yet_in_manifest(repository):
    repo, client = repository
    body = b"stdout-not-in-current-manifest"
    digest = hashlib.sha256(body).hexdigest()
    key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    response = client.put_object(
        Bucket="artifacts",
        Key=key,
        Body=body,
        ContentType="text/plain",
        Metadata={"sha256": digest},
    )
    reference = {
        "relative_path": ".agentarea/executions/execution-1/stdout.txt",
        "object_uri": f"s3://artifacts/{key}",
        "object_version_or_etag": response["ETag"].strip('"'),
        "sha256": digest,
        "size": len(body),
        "content_type": "text/plain",
    }

    assert await repo.list("ws-1", "task-1") == []
    assert await repo.get_object_ref("ws-1", "task-1", reference) == (
        body,
        "text/plain",
    )


@pytest.mark.asyncio
async def test_get_object_ref_accepts_empty_stream_ref_without_size(repository):
    # Regression: an empty stdout/stderr object has size 0, which the Go producer
    # serializes with omitempty (no "size" key at all). The ref's identity is its
    # sha256, so a missing size must be treated as 0, not rejected as malformed.
    repo, client = repository
    body = b""
    digest = hashlib.sha256(body).hexdigest()
    key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    response = client.put_object(
        Bucket="artifacts",
        Key=key,
        Body=body,
        ContentType="text/plain",
        Metadata={"sha256": digest},
    )
    reference = {
        "relative_path": ".agentarea/executions/execution-1/stderr.txt",
        "object_uri": f"s3://artifacts/{key}",
        "object_version_or_etag": response["ETag"].strip('"'),
        "sha256": digest,
        # no "size" key — the empty-stream case the Go producer emits
        "content_type": "text/plain",
    }
    contents, _ = await repo.get_object_ref("ws-1", "task-1", reference)
    assert contents == b""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("object_uri", "s3://artifacts/workspaces/ws-1/tasks/other/objects/deadbeef"),
        ("sha256", "f" * 64),
        ("size", 999),
        ("object_version_or_etag", ""),
        ("object_version_or_etag", "wrong-etag"),
    ],
)
async def test_get_object_ref_rejects_tampered_identity(repository, field, value):
    repo, client = repository
    body = b"trusted"
    digest = hashlib.sha256(body).hexdigest()
    key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    response = client.put_object(Bucket="artifacts", Key=key, Body=body)
    reference = {
        "relative_path": ".agentarea/executions/execution-1/stdout.txt",
        "object_uri": f"s3://artifacts/{key}",
        "object_version_or_etag": response["ETag"].strip('"'),
        "sha256": digest,
        "size": len(body),
        "content_type": "text/plain",
    }
    reference[field] = value

    with pytest.raises(WorkspaceValidationError):
        await repo.get_object_ref("ws-1", "task-1", reference)


@pytest.mark.asyncio
async def test_manifest_checksum_uses_stored_bytes_not_python_reserialization(repository):
    """A Go-written manifest may use a different valid JSON key order."""
    repo, client = repository
    ref = await repo.put_files("ws", "task", {"nested/result.txt": b"ok"})
    original_key = ref.manifest_uri.removeprefix("s3://artifacts/")
    value = json.loads(client.objects[original_key]["body"])
    go_ordered = {
        "schema_version": value["schema_version"],
        "workspace_id": value["workspace_id"],
        "task_id": value["task_id"],
        "generation": value["generation"],
        "base_generation": value["base_generation"],
        "fencing_token": value["fencing_token"],
        "entries": value["entries"],
    }
    raw = json.dumps(go_ordered, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    go_key = f"workspaces/ws/tasks/task/manifests/{ref.generation}-{digest}.json"
    client.put_object(Bucket="artifacts", Key=go_key, Body=raw, ContentType="application/json")

    pointer_key = "workspaces/ws/tasks/task/current.json"
    pointer = json.loads(client.objects[pointer_key]["body"])
    pointer["manifest_uri"] = f"s3://artifacts/{go_key}"
    pointer["manifest_sha256"] = digest
    client.put_object(
        Bucket="artifacts",
        Key=pointer_key,
        Body=json.dumps(pointer, separators=(",", ":")).encode(),
        ContentType="application/json",
    )

    assert [item.path for item in await repo.list("ws", "task")] == ["nested/result.txt"]


@pytest.mark.asyncio
async def test_current_pointer_uses_conditional_create_then_etag_cas(repository):
    repo, client = repository
    await repo.put("ws", "task", "first.txt", b"first")
    await repo.put("ws", "task", "second.txt", b"second")

    current_puts = [
        call
        for call in client.put_kwargs
        if call.get("Key") == "workspaces/ws/tasks/task/current.json"
    ]
    assert current_puts[0]["IfNoneMatch"] == "*"
    assert "IfMatch" not in current_puts[0]
    assert all(call.get("IfMatch") for call in current_puts[1:])
    assert all("IfNoneMatch" not in call for call in current_puts[1:])


@pytest.mark.asyncio
async def test_delete_commits_tombstone_and_never_resurrects(repository):
    repo, client = repository
    first = await repo.put("ws", "task", "nested/file.txt", b"hello")
    deleted = await repo.delete(
        "ws", "task", "nested/file.txt", expected_generation=first.generation
    )

    assert deleted.generation == 2
    assert not await repo.exists("ws", "task", "nested/file.txt")
    manifest_key = deleted.manifest_uri.removeprefix("s3://artifacts/")
    entry = json.loads(client.objects[manifest_key]["body"])["entries"][0]
    assert entry == {
        "content_type": "text/plain",
        "deleted": True,
        "mode": 420,
        "object_uri": "",
        "object_version_or_etag": "",
        "relative_path": "nested/file.txt",
        "sha256": "",
        "size": 0,
    }


@pytest.mark.asyncio
async def test_stale_base_generation_fails_without_advancing_pointer(repository):
    repo, _ = repository
    first = await repo.put("ws", "task", "a.txt", b"one")
    second = await repo.put("ws", "task", "b.txt", b"two")

    with pytest.raises(WorkspaceConflictError, match="does not match"):
        await repo.put("ws", "task", "c.txt", b"three", expected_generation=first.generation)

    assert (await repo.current_manifest_ref("ws", "task")).generation == second.generation
    assert not await repo.exists("ws", "task", "c.txt")


@pytest.mark.asyncio
async def test_active_writer_lease_rejects_second_owner(repository):
    repo, client = repository
    lease = await repo._acquire_lease("ws", "task", "runner-a")
    assert lease.fencing_token == 1

    with pytest.raises(WorkspaceConflictError, match="leased by runner-a"):
        await repo._acquire_lease("ws", "task", "runner-b")

    lease_body = json.loads(client.objects["workspaces/ws/tasks/task/lease.json"]["body"])
    assert lease_body["expires_at"].endswith("Z")


@pytest.mark.asyncio
async def test_execution_checkout_keeps_go_compatible_fence_live(repository):
    repo, client = repository
    ref = await repo.checkout_for_execution("ws", "task", owner="workflow-1")

    assert ref.fencing_token == 1
    assert ref.generation == 1
    lease = json.loads(client.objects["workspaces/ws/tasks/task/lease.json"]["body"])
    assert lease["owner"] == "workflow-1"
    assert lease["fencing_token"] == ref.fencing_token
    assert lease["expires_at"].endswith("Z")
    assert repo._lease_epoch(lease["expires_at"]) > time.time()


@pytest.mark.asyncio
async def test_failed_scheduling_releases_exact_execution_lease(repository):
    repo, client = repository
    ref = await repo.checkout_for_execution("ws", "task", owner="shell-exact")

    await repo.release_execution_lease("ws", "task", ref, owner="shell-exact")

    lease = json.loads(client.objects["workspaces/ws/tasks/task/lease.json"]["body"])
    assert lease["owner"] == "shell-exact"
    assert lease["fencing_token"] == ref.fencing_token
    assert repo._lease_epoch(lease["expires_at"]) == 0


@pytest.mark.asyncio
async def test_stale_execution_cannot_release_newer_lease(repository):
    repo, client = repository
    stale_ref = await repo.checkout_for_execution("ws", "task", owner="shell-stale")
    await repo.release_execution_lease("ws", "task", stale_ref, owner="shell-stale")
    current_ref = await repo.checkout_for_execution("ws", "task", owner="shell-current")

    with pytest.raises(WorkspaceConflictError, match="newer workspace lease"):
        await repo.release_execution_lease("ws", "task", stale_ref, owner="shell-stale")

    lease = json.loads(client.objects["workspaces/ws/tasks/task/lease.json"]["body"])
    assert lease["owner"] == "shell-current"
    assert lease["fencing_token"] == current_ref.fencing_token
    assert repo._lease_epoch(lease["expires_at"]) > time.time()


@pytest.mark.asyncio
async def test_project_import_streams_directly_into_task_objects(repository):
    repo, client = repository
    client.put_object(
        Bucket="artifacts",
        Key="workspaces/ws/projects/project-1/nested/input.txt",
        Body=b"project-input",
        ContentType="text/plain",
    )

    ref = await repo.import_workspace_prefix(
        "ws",
        "task",
        source_prefix="projects/project-1",
        target_prefix="inputs/project",
    )

    assert ref.generation == 1
    assert await repo.get("ws", "task", "inputs/project/nested/input.txt") == (
        b"project-input",
        "text/plain",
    )
    manifest_key = ref.manifest_uri.removeprefix("s3://artifacts/")
    manifest_wire = client.objects[manifest_key]["body"]
    assert b"project-input" not in manifest_wire
    assert b"content_base64" not in manifest_wire


def _stage(client: FakeS3, key: str, body: bytes, *, content_type: str, sha256: str) -> None:
    client.put_object(
        Bucket="artifacts",
        Key=key,
        Body=body,
        ContentType=content_type,
        Metadata={"sha256": sha256},
    )


@pytest.mark.asyncio
async def test_attach_object_copies_staging_into_task_objects(repository):
    repo, client = repository
    body = b"attached-report-bytes"
    digest = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws-1/staging/upload-1/report.csv",
        body,
        content_type="text/csv",
        sha256=digest,
    )

    ref = await repo.attach_object(
        "ws-1",
        "task-1",
        "inputs/report.csv",
        source_key="staging/upload-1/report.csv",
        expected_sha256=digest,
        expected_size=len(body),
        content_type="text/csv",
    )

    assert ref.generation == 1
    listed = await repo.list("ws-1", "task-1")
    assert [item.path for item in listed] == ["inputs/report.csv"]
    entry = listed[0]
    assert entry.sha256 == digest
    assert entry.object_uri == f"s3://artifacts/workspaces/ws-1/tasks/task-1/objects/{digest}"
    dest_key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    manifest_key = ref.manifest_uri.removeprefix("s3://artifacts/")
    manifest_entry = json.loads(client.objects[manifest_key]["body"])["entries"][0]
    assert manifest_entry["object_version_or_etag"] == client.objects[dest_key]["etag"]
    assert client.objects[dest_key]["metadata"]["sha256"] == digest
    assert await repo.get("ws-1", "task-1", "inputs/report.csv") == (body, "text/csv")
    assert client.copy_kwargs
    assert client.copy_kwargs[0]["MetadataDirective"] == "REPLACE"
    assert client.copy_kwargs[0]["Metadata"]["sha256"] == digest


@pytest.mark.asyncio
async def test_attach_uses_destination_etag_not_source_multipart_etag(repository):
    repo, client = repository
    body = b"multipart-source-body"
    digest = hashlib.sha256(body).hexdigest()
    # A multipart-uploaded staging object carries a -partcount etag suffix that
    # is not the content md5; the manifest must record the copy DESTINATION etag.
    client.objects["workspaces/ws-1/staging/mp/data.bin"] = {
        "body": body,
        "etag": "deadbeefdeadbeefdeadbeefdeadbeef-3",
        "metadata": {"sha256": digest},
        "content_type": "application/octet-stream",
    }

    await repo.attach_object(
        "ws-1",
        "task-1",
        "data.bin",
        source_key="staging/mp/data.bin",
        expected_sha256=digest,
        expected_size=len(body),
        content_type="application/octet-stream",
    )

    dest_key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    entry = await repo._entry("ws-1", "task-1", "data.bin")
    assert entry.object_version_or_etag == client.objects[dest_key]["etag"]
    assert entry.object_version_or_etag != "deadbeefdeadbeefdeadbeefdeadbeef-3"


@pytest.mark.asyncio
async def test_attach_rejects_sha256_mismatch_without_copying(repository):
    repo, client = repository
    body = b"honest-bytes"
    actual = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws-1/staging/x/f.bin",
        body,
        content_type="application/octet-stream",
        sha256=actual,
    )

    with pytest.raises(WorkspaceValidationError):
        await repo.attach_object(
            "ws-1",
            "task-1",
            "f.bin",
            source_key="staging/x/f.bin",
            expected_sha256="f" * 64,
            expected_size=len(body),
            content_type="application/octet-stream",
        )

    assert await repo.list("ws-1", "task-1") == []
    assert not client.copy_kwargs


@pytest.mark.asyncio
async def test_attach_rejects_size_mismatch_without_copying(repository):
    repo, client = repository
    body = b"honest-bytes"
    digest = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws-1/staging/y/f.bin",
        body,
        content_type="application/octet-stream",
        sha256=digest,
    )

    with pytest.raises(WorkspaceValidationError):
        await repo.attach_object(
            "ws-1",
            "task-1",
            "f.bin",
            source_key="staging/y/f.bin",
            expected_sha256=digest,
            expected_size=len(body) + 1,
            content_type="application/octet-stream",
        )

    assert not client.copy_kwargs


@pytest.mark.asyncio
async def test_attach_rejects_oversized_before_copy():
    client = FakeS3()
    repo = WorkspaceRepository(client=client, bucket="artifacts", max_file_bytes=4)
    body = b"way too big for the per-file limit"
    digest = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws/staging/o/big.bin",
        body,
        content_type="application/octet-stream",
        sha256=digest,
    )

    with pytest.raises(WorkspaceQuotaError):
        await repo.attach_object(
            "ws",
            "task",
            "big.bin",
            source_key="staging/o/big.bin",
            expected_sha256=digest,
            expected_size=len(body),
            content_type="application/octet-stream",
        )

    assert not client.copy_kwargs
    assert (await repo.current_manifest_ref("ws", "task")).generation == 0


@pytest.mark.asyncio
async def test_attach_is_idempotent_on_retry(repository):
    repo, client = repository
    body = b"idempotent-bytes"
    digest = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws-1/staging/i/f.bin",
        body,
        content_type="text/plain",
        sha256=digest,
    )
    kwargs = {
        "source_key": "staging/i/f.bin",
        "expected_sha256": digest,
        "expected_size": len(body),
        "content_type": "text/plain",
    }

    first = await repo.attach_object("ws-1", "task-1", "f.bin", **kwargs)
    second = await repo.attach_object("ws-1", "task-1", "f.bin", **kwargs)

    assert first.generation == 1
    assert second.generation == first.generation
    assert [i.path for i in await repo.list("ws-1", "task-1")] == ["f.bin"]
    assert len(client.copy_kwargs) == 1


@pytest.mark.asyncio
async def test_attach_restamps_metadata_so_identical_put_files_does_not_collide(repository):
    repo, client = repository
    body = b"shared-content-across-paths"
    digest = hashlib.sha256(body).hexdigest()
    _stage(
        client,
        "workspaces/ws-1/staging/s/a.bin",
        body,
        content_type="application/octet-stream",
        sha256=digest,
    )

    await repo.attach_object(
        "ws-1",
        "task-1",
        "a.bin",
        source_key="staging/s/a.bin",
        expected_sha256=digest,
        expected_size=len(body),
        content_type="application/octet-stream",
    )

    dest_key = f"workspaces/ws-1/tasks/task-1/objects/{digest}"
    assert client.objects[dest_key]["metadata"]["sha256"] == digest

    await repo.put_files("ws-1", "task-1", {"copy/a.bin": body})

    assert [i.path for i in await repo.list("ws-1", "task-1")] == ["a.bin", "copy/a.bin"]


@pytest.mark.asyncio
async def test_attach_rejects_missing_staging_source(repository):
    repo, client = repository
    with pytest.raises(WorkspaceValidationError):
        await repo.attach_object(
            "ws-1",
            "task-1",
            "f.bin",
            source_key="staging/missing/f.bin",
            expected_sha256="a" * 64,
            expected_size=1,
            content_type="application/octet-stream",
        )
    assert not client.copy_kwargs


@pytest.mark.asyncio
async def test_quotas_fail_explicitly_and_atomically():
    client = FakeS3()
    repo = WorkspaceRepository(client=client, bucket="artifacts", max_files=1)

    with pytest.raises(WorkspaceQuotaError, match="limit is 1"):
        await repo.put_files("ws", "task", {"a": b"a", "b": b"b"})

    assert (await repo.current_manifest_ref("ws", "task")).generation == 0


@pytest.mark.parametrize(
    "path",
    ["/absolute", "../escape", "a/../escape", "windows\\escape", "a//b", ""],
)
def test_noncanonical_paths_are_rejected(path: str):
    with pytest.raises(WorkspaceValidationError):
        normalize_workspace_path(path)


def test_task_identity_cannot_escape_server_derived_prefix(repository):
    repo, _ = repository
    with pytest.raises(WorkspaceValidationError):
        repo.task_prefix("ws", "../other-task")
