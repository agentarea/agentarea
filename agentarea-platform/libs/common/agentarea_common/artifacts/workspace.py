"""Immutable, generation-based task workspaces backed by S3.

File bodies live only in immutable S3 objects.  A committed manifest maps
POSIX-relative workspace paths to those objects and a small ``current`` pointer
is advanced with compare-and-swap.  Redis/Temporal callers therefore need only
the :class:`WorkspaceManifestRef` returned by this module.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import re
import stat
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from botocore.exceptions import ClientError

from agentarea_common.artifacts.audit import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    ArtifactActor,
    ArtifactEventRecorder,
)
from agentarea_common.config.aws import get_aws_settings, get_s3_client

WORKSPACE_SCHEMA_VERSION = 1
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_LEASE_SECONDS = 3600
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WorkspaceError(RuntimeError):
    """Base error carrying a stable machine-readable failure code."""

    code = "workspace_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class WorkspaceConflictError(WorkspaceError):
    code = "workspace_conflict"


class WorkspaceValidationError(WorkspaceError):
    code = "invalid_workspace_reference"


class WorkspaceQuotaError(WorkspaceError):
    code = "workspace_quota_exceeded"


def normalize_workspace_path(path: str) -> str:
    """Return a canonical POSIX relative path or reject the path explicitly."""
    if not isinstance(path, str) or not path:
        raise WorkspaceValidationError("workspace path must be a non-empty string")
    if "\x00" in path or "\\" in path:
        raise WorkspaceValidationError(f"workspace path is not canonical POSIX: {path!r}")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise WorkspaceValidationError(f"workspace path escapes task root: {path!r}")
    normalized = parsed.as_posix()
    if normalized != path:
        raise WorkspaceValidationError(f"workspace path is not canonical: {path!r}")
    return normalized


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    relative_path: str
    object_uri: str
    object_version_or_etag: str
    sha256: str
    size: int
    content_type: str
    mode: int = 0o644
    deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkspaceEntry:
        return cls(
            relative_path=str(value["relative_path"]),
            object_uri=str(value.get("object_uri") or ""),
            object_version_or_etag=str(value.get("object_version_or_etag") or ""),
            sha256=str(value.get("sha256") or ""),
            size=int(value.get("size") or 0),
            content_type=str(value.get("content_type") or "application/octet-stream"),
            mode=int(value.get("mode") or 0o644),
            deleted=bool(value.get("deleted", False)),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceManifestRef:
    schema_version: int
    workspace_id: str
    task_id: str
    generation: int
    manifest_uri: str
    manifest_sha256: str
    base_generation: int
    fencing_token: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkspaceManifestRef:
        return cls(
            schema_version=int(value["schema_version"]),
            workspace_id=str(value["workspace_id"]),
            task_id=str(value["task_id"]),
            generation=int(value["generation"]),
            manifest_uri=str(value["manifest_uri"]),
            manifest_sha256=str(value["manifest_sha256"]),
            base_generation=int(value["base_generation"]),
            fencing_token=int(value["fencing_token"]),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    schema_version: int
    workspace_id: str
    task_id: str
    generation: int
    base_generation: int
    fencing_token: int
    entries: tuple[WorkspaceEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "generation": self.generation,
            "base_generation": self.base_generation,
            "fencing_token": self.fencing_token,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class WorkspaceObject:
    path: str
    size: int
    content_type: str | None
    sha256: str
    object_uri: str
    generation: int


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    owner: str
    fencing_token: int
    expires_at: float
    etag: str


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}


def _is_precondition(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {
        "PreconditionFailed",
        "412",
        "ConditionalRequestConflict",
    }


class S3WorkspaceRepository:
    """Manifest-aware repository for ``tasks/{task_id}/workspace``.

    Every mutating call acquires a task lease, uploads immutable content, and
    CAS-advances the current pointer.  Stale base generations and fencing
    tokens are rejected instead of applying last-write-wins.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        bucket: str | None = None,
        key_prefix: str = "",
        recorder: ArtifactEventRecorder | None = None,
        actor: ArtifactActor | None = None,
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._client = client or get_s3_client()
        self._bucket = bucket or get_aws_settings().ARTIFACTS_BUCKET_NAME
        self._key_prefix = key_prefix.strip("/")
        self._recorder = recorder
        self._actor = actor
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._lease_seconds = lease_seconds

    @staticmethod
    def _lease_timestamp(epoch_seconds: float) -> str:
        return datetime.fromtimestamp(epoch_seconds, UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _lease_epoch(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0
        return 0

    @property
    def bucket(self) -> str:
        return self._bucket

    def task_prefix(self, workspace_id: str, task_id: str) -> str:
        if not all(_IDENTIFIER_RE.fullmatch(value or "") for value in (workspace_id, task_id)):
            raise WorkspaceValidationError(
                "workspace_id and task_id must be opaque identifier segments"
            )
        canonical = f"workspaces/{workspace_id}/tasks/{task_id}"
        return f"{self._key_prefix}/{canonical}" if self._key_prefix else canonical

    def _key(self, workspace_id: str, task_id: str, suffix: str) -> str:
        return f"{self.task_prefix(workspace_id, task_id)}/{suffix.lstrip('/')}"

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def _validate_uri(self, workspace_id: str, task_id: str, uri: str) -> str:
        parsed = urlparse(uri)
        if (
            parsed.scheme != "s3"
            or parsed.netloc != self._bucket
            or parsed.query
            or parsed.fragment
            or parsed.params
        ):
            raise WorkspaceValidationError("workspace object uses an untrusted bucket")
        key = parsed.path.lstrip("/")
        expected = self.task_prefix(workspace_id, task_id) + "/"
        if not key.startswith(expected) or ".." in key.split("/"):
            raise WorkspaceValidationError(
                "workspace object is outside the authenticated task prefix"
            )
        return key

    async def _get_json_document(self, key: str) -> tuple[dict[str, Any], str, bytes] | None:
        def call() -> tuple[dict[str, Any], str, bytes] | None:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    return None
                raise
            raw = response["Body"].read()
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise WorkspaceValidationError(f"JSON object expected at {key}")
            return decoded, str(response.get("ETag") or "").strip('"'), raw

        return await asyncio.to_thread(call)

    async def _get_json(self, key: str) -> tuple[dict[str, Any], str] | None:
        document = await self._get_json_document(key)
        if document is None:
            return None
        value, etag, _ = document
        return value, etag

    async def _put_json(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        body = _json_bytes(value)

        def call() -> str:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Key": key,
                "Body": body,
                "ContentType": "application/json",
                "ChecksumSHA256": base64.b64encode(hashlib.sha256(body).digest()).decode("ascii"),
            }
            if if_match:
                kwargs["IfMatch"] = if_match
            if if_none_match:
                kwargs["IfNoneMatch"] = "*"
            response = self._client.put_object(**kwargs)
            return str(response.get("ETag") or hashlib.md5(body).hexdigest()).strip('"')  # noqa: S324

        try:
            return await asyncio.to_thread(call)
        except ClientError as exc:
            if _is_precondition(exc):
                raise WorkspaceConflictError(f"CAS failed for {key}") from exc
            raise

    async def _put_immutable(self, key: str, data: bytes, content_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()

        def call() -> str:
            try:
                response = self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata={"sha256": digest},
                    ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode("ascii"),
                    IfNoneMatch="*",
                )
                version_id = str(response.get("VersionId") or "")
                if version_id:
                    return f"version:{version_id}"
                return str(response.get("ETag") or "").strip('"')
            except ClientError as exc:
                if not _is_precondition(exc):
                    raise
                head = self._client.head_object(Bucket=self._bucket, Key=key)
                existing_hash = (head.get("Metadata") or {}).get("sha256")
                if int(head.get("ContentLength") or -1) != len(data) or existing_hash != digest:
                    raise WorkspaceConflictError(
                        f"immutable object identity collision at {key}"
                    ) from exc
                version_id = str(head.get("VersionId") or "")
                if version_id:
                    return f"version:{version_id}"
                return str(head.get("ETag") or "").strip('"')

        return await asyncio.to_thread(call)

    async def _put_immutable_file(
        self,
        key: str,
        stream: Any,
        *,
        size: int,
        digest: str,
        content_type: str,
    ) -> str:
        """Upload a seekable file without materializing its body in worker memory."""

        def call() -> str:
            stream.seek(0)
            try:
                response = self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=stream,
                    ContentLength=size,
                    ContentType=content_type,
                    Metadata={"sha256": digest},
                    ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
                    IfNoneMatch="*",
                )
                version_id = str(response.get("VersionId") or "")
                if version_id:
                    return f"version:{version_id}"
                return str(response.get("ETag") or "").strip('"')
            except ClientError as exc:
                if not _is_precondition(exc):
                    raise
                head = self._client.head_object(Bucket=self._bucket, Key=key)
                existing_hash = (head.get("Metadata") or {}).get("sha256")
                if int(head.get("ContentLength") or -1) != size or existing_hash != digest:
                    raise WorkspaceConflictError(
                        f"immutable object identity collision at {key}"
                    ) from exc
                version_id = str(head.get("VersionId") or "")
                if version_id:
                    return f"version:{version_id}"
                return str(head.get("ETag") or "").strip('"')

        return await asyncio.to_thread(call)

    async def _acquire_lease(self, workspace_id: str, task_id: str, owner: str) -> WorkspaceLease:
        key = self._key(workspace_id, task_id, "lease.json")
        now = time.time()
        current = await self._get_json(key)
        if current is None:
            token = 1
            expires_at = now + self._lease_seconds
            payload = {
                "owner": owner,
                "fencing_token": token,
                "expires_at": self._lease_timestamp(expires_at),
            }
            etag = await self._put_json(key, payload, if_none_match=True)
            return WorkspaceLease(owner, token, expires_at, etag)

        payload, etag = current
        current_owner = str(payload.get("owner") or "")
        expires_at = self._lease_epoch(payload.get("expires_at"))
        if expires_at > now and current_owner != owner:
            raise WorkspaceConflictError(f"task workspace is leased by {current_owner}")
        token = int(payload.get("fencing_token") or 0) + 1
        next_expires_at = now + self._lease_seconds
        next_payload = {
            "owner": owner,
            "fencing_token": token,
            "expires_at": self._lease_timestamp(next_expires_at),
        }
        next_etag = await self._put_json(key, next_payload, if_match=etag)
        return WorkspaceLease(owner, token, next_expires_at, next_etag)

    async def _assert_lease(
        self, workspace_id: str, task_id: str, lease: WorkspaceLease
    ) -> tuple[dict[str, Any], str]:
        current = await self._get_json(self._key(workspace_id, task_id, "lease.json"))
        if current is None:
            raise WorkspaceConflictError("workspace lease disappeared")
        payload, etag = current
        if (
            payload.get("owner") != lease.owner
            or int(payload.get("fencing_token") or -1) != lease.fencing_token
            or self._lease_epoch(payload.get("expires_at")) <= time.time()
        ):
            raise WorkspaceConflictError("workspace fencing token is stale")
        return payload, etag

    async def _release_lease(self, workspace_id: str, task_id: str, lease: WorkspaceLease) -> None:
        try:
            payload, etag = await self._assert_lease(workspace_id, task_id, lease)
            payload = dict(payload)
            payload["expires_at"] = self._lease_timestamp(0)
            await self._put_json(
                self._key(workspace_id, task_id, "lease.json"), payload, if_match=etag
            )
        except WorkspaceConflictError:
            # Never let a stale owner modify a newer lease merely to "release" it.
            return

    async def _initialize(self, workspace_id: str, task_id: str) -> WorkspaceManifestRef:
        manifest = WorkspaceManifest(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            workspace_id=workspace_id,
            task_id=task_id,
            generation=0,
            base_generation=0,
            fencing_token=0,
            entries=(),
        )
        body = _json_bytes(manifest.to_dict())
        digest = hashlib.sha256(body).hexdigest()
        key = self._key(workspace_id, task_id, f"manifests/0-{digest}.json")
        await self._put_immutable(key, body, "application/json")
        ref = WorkspaceManifestRef(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            workspace_id=workspace_id,
            task_id=task_id,
            generation=0,
            manifest_uri=self._uri(key),
            manifest_sha256=digest,
            base_generation=0,
            fencing_token=0,
        )
        pointer_key = self._key(workspace_id, task_id, "current.json")
        try:
            await self._put_json(pointer_key, ref.to_dict(), if_none_match=True)
            return ref
        except WorkspaceConflictError:
            loaded = await self._get_json(pointer_key)
            if loaded is None:
                raise
            return self._validated_ref(workspace_id, task_id, loaded[0])

    def _validated_ref(
        self, workspace_id: str, task_id: str, value: Mapping[str, Any]
    ) -> WorkspaceManifestRef:
        try:
            ref = WorkspaceManifestRef.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceValidationError("malformed workspace manifest reference") from exc
        if (
            ref.schema_version != WORKSPACE_SCHEMA_VERSION
            or ref.workspace_id != workspace_id
            or ref.task_id != task_id
            or ref.generation < 0
            or ref.base_generation < 0
            or ref.base_generation > ref.generation
            or ref.fencing_token < 0
            or not _SHA256_RE.fullmatch(ref.manifest_sha256)
        ):
            raise WorkspaceValidationError("workspace manifest reference identity is invalid")
        key = self._validate_uri(workspace_id, task_id, ref.manifest_uri)
        expected = self._key(
            workspace_id,
            task_id,
            f"manifests/{ref.generation}-{ref.manifest_sha256}.json",
        )
        if key != expected:
            raise WorkspaceValidationError("workspace manifest URI does not match its identity")
        return ref

    async def current_manifest_ref(self, workspace_id: str, task_id: str) -> WorkspaceManifestRef:
        current = await self._get_json(self._key(workspace_id, task_id, "current.json"))
        if current is None:
            return await self._initialize(workspace_id, task_id)
        return self._validated_ref(workspace_id, task_id, current[0])

    async def checkout_for_execution(
        self,
        workspace_id: str,
        task_id: str,
        *,
        owner: str,
    ) -> WorkspaceManifestRef:
        """Fence a manifest for one sandbox execution and keep its lease live.

        The Go runner validates the same ``lease.json`` before hydration,
        writeback planning, and CAS commit.  Returning a read snapshot or
        releasing its lease first would correctly be rejected as stale.
        """
        if not owner:
            raise WorkspaceValidationError("execution lease owner is required")
        lease = await self._acquire_lease(workspace_id, task_id, owner)
        try:
            ref, entries, pointer_etag = await self._snapshot(workspace_id, task_id)
            return await self._commit(
                workspace_id,
                task_id,
                ref,
                entries,
                pointer_etag,
                lease,
            )
        except Exception:
            await self._release_lease(workspace_id, task_id, lease)
            raise

    async def release_execution_lease(
        self,
        workspace_id: str,
        task_id: str,
        manifest_ref: Mapping[str, Any] | WorkspaceManifestRef,
        *,
        owner: str,
    ) -> None:
        """Expire the exact shell lease when scheduling cannot complete.

        The conditional write uses the current lease ETag and requires both the
        caller's unique owner and the manifest fencing token. A stale caller can
        therefore neither release nor overwrite a newer execution lease.
        """
        ref = (
            manifest_ref
            if isinstance(manifest_ref, WorkspaceManifestRef)
            else WorkspaceManifestRef.from_dict(manifest_ref)
        )
        ref = self._validated_ref(workspace_id, task_id, ref.to_dict())
        current = await self._get_json(self._key(workspace_id, task_id, "lease.json"))
        if current is None:
            raise WorkspaceConflictError("workspace lease disappeared before release")
        payload, etag = current
        if (
            str(payload.get("owner") or "") != owner
            or int(payload.get("fencing_token") or -1) != ref.fencing_token
        ):
            raise WorkspaceConflictError("refusing to release a newer workspace lease")
        if self._lease_epoch(payload.get("expires_at")) <= time.time():
            return
        released = dict(payload)
        released["expires_at"] = self._lease_timestamp(0)
        await self._put_json(
            self._key(workspace_id, task_id, "lease.json"),
            released,
            if_match=etag,
        )

    async def _snapshot(
        self, workspace_id: str, task_id: str
    ) -> tuple[WorkspaceManifestRef, dict[str, WorkspaceEntry], str]:
        pointer_key = self._key(workspace_id, task_id, "current.json")
        current = await self._get_json(pointer_key)
        if current is None:
            await self._initialize(workspace_id, task_id)
            current = await self._get_json(pointer_key)
        if current is None:
            raise WorkspaceConflictError("workspace current pointer was not created")
        ref = self._validated_ref(workspace_id, task_id, current[0])
        entries = await self._entries_for_ref(workspace_id, task_id, ref)
        return ref, entries, current[1]

    async def _entries_for_ref(
        self,
        workspace_id: str,
        task_id: str,
        ref: WorkspaceManifestRef,
    ) -> dict[str, WorkspaceEntry]:
        """Load and verify the immutable manifest identified by ``ref``."""
        ref = self._validated_ref(workspace_id, task_id, ref.to_dict())
        key = self._validate_uri(workspace_id, task_id, ref.manifest_uri)
        manifest_result = await self._get_json_document(key)
        if manifest_result is None:
            raise WorkspaceValidationError("workspace manifest object is missing")
        manifest_value, _, raw = manifest_result
        if hashlib.sha256(raw).hexdigest() != ref.manifest_sha256:
            raise WorkspaceValidationError("workspace manifest checksum mismatch")
        try:
            manifest_identity = (
                int(manifest_value["schema_version"]),
                str(manifest_value["workspace_id"]),
                str(manifest_value["task_id"]),
                int(manifest_value["generation"]),
                int(manifest_value["base_generation"]),
                int(manifest_value["fencing_token"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceValidationError("workspace manifest identity is malformed") from exc
        if manifest_identity != (
            ref.schema_version,
            workspace_id,
            task_id,
            ref.generation,
            ref.base_generation,
            ref.fencing_token,
        ):
            raise WorkspaceValidationError("workspace manifest identity does not match its ref")
        raw_entries = manifest_value.get("entries")
        if not isinstance(raw_entries, list):
            raise WorkspaceValidationError("workspace manifest entries must be a list")
        entries: dict[str, WorkspaceEntry] = {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                raise WorkspaceValidationError("workspace manifest entry must be an object")
            entry = WorkspaceEntry.from_dict(raw_entry)
            self._validate_entry(workspace_id, task_id, entry)
            if entry.relative_path in entries:
                raise WorkspaceValidationError(f"duplicate workspace path: {entry.relative_path!r}")
            entries[entry.relative_path] = entry
        return entries

    def _validate_entry(self, workspace_id: str, task_id: str, entry: WorkspaceEntry) -> None:
        normalize_workspace_path(entry.relative_path)
        if entry.deleted:
            if entry.object_uri or entry.object_version_or_etag or entry.sha256 or entry.size:
                raise WorkspaceValidationError("workspace tombstone carries object data")
            return
        object_key = self._validate_uri(workspace_id, task_id, entry.object_uri)
        if (
            not entry.object_version_or_etag
            or not _SHA256_RE.fullmatch(entry.sha256)
            or entry.size < 0
            or stat.S_IFMT(entry.mode) not in {0, stat.S_IFREG}
        ):
            raise WorkspaceValidationError("workspace entry has mutable or invalid object identity")
        if object_key != self._key(workspace_id, task_id, f"objects/{entry.sha256}"):
            raise WorkspaceValidationError("workspace entry object URI does not match its digest")

    def _check_quotas(self, entries: Mapping[str, WorkspaceEntry]) -> None:
        live = [entry for entry in entries.values() if not entry.deleted]
        total = sum(entry.size for entry in live)
        if len(live) > self._max_files:
            raise WorkspaceQuotaError(
                f"workspace has {len(live)} files; limit is {self._max_files}"
            )
        if any(entry.size > self._max_file_bytes for entry in live):
            raise WorkspaceQuotaError(f"workspace file exceeds {self._max_file_bytes} bytes")
        if total > self._max_total_bytes:
            raise WorkspaceQuotaError(
                f"workspace has {total} bytes; limit is {self._max_total_bytes}"
            )

    async def _record(self, workspace_id: str, task_id: str, path: str, action: str) -> None:
        if self._recorder is None or self._actor is None:
            return
        try:
            await self._recorder.record(
                workspace_id=workspace_id,
                path=f"tasks/{task_id}/workspace/{path}",
                action=action,
                actor=self._actor,
            )
        except Exception:
            # Match ArtifactService: provenance is useful but not a file-commit dependency.
            return

    async def put_files(
        self,
        workspace_id: str,
        task_id: str,
        files: Mapping[str, bytes],
        *,
        content_types: Mapping[str, str] | None = None,
        provenance: Mapping[str, str] | None = None,
        expected_generation: int | None = None,
        owner: str | None = None,
    ) -> WorkspaceManifestRef:
        """Atomically commit one or more paths as a new generation."""
        if not files:
            return await self.current_manifest_ref(workspace_id, task_id)
        normalized = {normalize_workspace_path(path): data for path, data in files.items()}
        for path, data in normalized.items():
            if not isinstance(data, bytes):
                raise WorkspaceValidationError(f"workspace content for {path!r} must be bytes")
            if len(data) > self._max_file_bytes:
                raise WorkspaceQuotaError(
                    f"workspace file {path!r} has {len(data)} bytes; limit is {self._max_file_bytes}"
                )

        lease = await self._acquire_lease(
            workspace_id, task_id, owner or f"python-{uuid.uuid4().hex}"
        )
        try:
            ref, entries, pointer_etag = await self._snapshot(workspace_id, task_id)
            if expected_generation is not None and ref.generation != expected_generation:
                raise WorkspaceConflictError(
                    f"base generation {ref.generation} does not match expected {expected_generation}"
                )
            if all(
                path in entries
                and not entries[path].deleted
                and entries[path].sha256 == hashlib.sha256(data).hexdigest()
                for path, data in normalized.items()
            ):
                return ref
            changed_actions: list[tuple[str, str]] = []
            for path, data in normalized.items():
                digest = hashlib.sha256(data).hexdigest()
                key = self._key(workspace_id, task_id, f"objects/{digest}")
                content_type = (content_types or {}).get(path) or mimetypes.guess_type(path)[0]
                content_type = content_type or "application/octet-stream"
                identity = await self._put_immutable(key, data, content_type)
                existed = path in entries and not entries[path].deleted
                entries[path] = WorkspaceEntry(
                    relative_path=path,
                    object_uri=self._uri(key),
                    object_version_or_etag=identity,
                    sha256=digest,
                    size=len(data),
                    content_type=content_type,
                    mode=0o644,
                    deleted=False,
                )
                changed_actions.append((path, ACTION_MODIFIED if existed else ACTION_CREATED))
            self._check_quotas(entries)
            next_ref = await self._commit(workspace_id, task_id, ref, entries, pointer_etag, lease)
            for path, action in changed_actions:
                await self._record(workspace_id, task_id, path, action)
            return next_ref
        finally:
            await self._release_lease(workspace_id, task_id, lease)

    async def import_workspace_prefix(
        self,
        workspace_id: str,
        task_id: str,
        *,
        source_prefix: str,
        target_prefix: str,
        provenance: Mapping[str, str] | None = None,
        owner: str | None = None,
    ) -> WorkspaceManifestRef:
        """Commit a trusted project prefix without transport encoding.

        Objects are streamed one at a time through a bounded spool in the
        trusted repository process. Bytes never enter a sandbox request,
        Redis, or a Temporal payload, and the Python worker never accumulates
        the whole project in memory. Quotas are checked before any source body
        is read; an oversized import fails as a whole.
        """
        if not workspace_id or "/" in workspace_id:
            raise WorkspaceValidationError("workspace_id must be an opaque path segment")
        source = source_prefix.strip("/")
        if not source or ".." in source.split("/"):
            raise WorkspaceValidationError("source prefix is invalid")
        target = normalize_workspace_path(target_prefix)
        source_key_prefix = f"workspaces/{workspace_id}/{source}/"

        def list_sources() -> list[dict[str, Any]]:
            found: list[dict[str, Any]] = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=source_key_prefix):
                found.extend(page.get("Contents") or [])
            return found

        sources = await asyncio.to_thread(list_sources)
        if len(sources) > self._max_files:
            raise WorkspaceQuotaError(
                f"workspace import has {len(sources)} files; limit is {self._max_files}"
            )
        total = sum(int(item.get("Size") or 0) for item in sources)
        if any(int(item.get("Size") or 0) > self._max_file_bytes for item in sources):
            raise WorkspaceQuotaError(f"workspace import file exceeds {self._max_file_bytes} bytes")
        if total > self._max_total_bytes:
            raise WorkspaceQuotaError(
                f"workspace import has {total} bytes; limit is {self._max_total_bytes}"
            )

        if not sources:
            return await self.current_manifest_ref(workspace_id, task_id)

        source_paths: list[tuple[dict[str, Any], str, str]] = []
        seen_targets: set[str] = set()
        for item in sources:
            source_key = str(item["Key"])
            relative = normalize_workspace_path(source_key[len(source_key_prefix) :])
            target_path = normalize_workspace_path(f"{target}/{relative}")
            if target_path in seen_targets:
                raise WorkspaceValidationError(f"duplicate project path: {target_path!r}")
            seen_targets.add(target_path)
            source_paths.append((item, relative, target_path))

        lease = await self._acquire_lease(
            workspace_id, task_id, owner or f"python-import-{uuid.uuid4().hex}"
        )
        try:
            ref, entries, pointer_etag = await self._snapshot(workspace_id, task_id)
            changed_actions: list[tuple[str, str]] = []

            for item, relative, target_path in source_paths:
                source_key = str(item["Key"])
                expected_size = int(item.get("Size") or 0)

                def download_source(
                    source_object_key: str,
                    source_size: int,
                    source_relative: str,
                ) -> tuple[Any, str, str, int]:
                    response = self._client.get_object(Bucket=self._bucket, Key=source_object_key)
                    source_body = response["Body"]
                    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
                    hasher = hashlib.sha256()
                    copied = 0
                    try:
                        while True:
                            chunk = source_body.read(1024 * 1024)
                            if not chunk:
                                break
                            spool.write(chunk)
                            hasher.update(chunk)
                            copied += len(chunk)
                    except Exception:
                        spool.close()
                        raise
                    finally:
                        close = getattr(source_body, "close", None)
                        if callable(close):
                            close()
                    if copied != source_size:
                        spool.close()
                        raise WorkspaceValidationError(
                            f"source object size changed during import: {source_relative!r}"
                        )
                    content_type = str(
                        response.get("ContentType")
                        or mimetypes.guess_type(source_relative)[0]
                        or "application/octet-stream"
                    )
                    return spool, hasher.hexdigest(), content_type, copied

                spool, digest, content_type, copied = await asyncio.to_thread(
                    download_source, source_key, expected_size, relative
                )
                try:
                    object_key = self._key(workspace_id, task_id, f"objects/{digest}")
                    identity = await self._put_immutable_file(
                        object_key,
                        spool,
                        size=copied,
                        digest=digest,
                        content_type=content_type,
                    )
                finally:
                    spool.close()

                existed = target_path in entries and not entries[target_path].deleted
                entries[target_path] = WorkspaceEntry(
                    relative_path=target_path,
                    object_uri=self._uri(object_key),
                    object_version_or_etag=identity,
                    sha256=digest,
                    size=copied,
                    content_type=content_type,
                    mode=0o644,
                    deleted=False,
                )
                changed_actions.append(
                    (target_path, ACTION_MODIFIED if existed else ACTION_CREATED)
                )

            self._check_quotas(entries)
            next_ref = await self._commit(workspace_id, task_id, ref, entries, pointer_etag, lease)
            for path, action in changed_actions:
                await self._record(workspace_id, task_id, path, action)
            return next_ref
        finally:
            await self._release_lease(workspace_id, task_id, lease)

    async def _commit(
        self,
        workspace_id: str,
        task_id: str,
        base_ref: WorkspaceManifestRef,
        entries: Mapping[str, WorkspaceEntry],
        pointer_etag: str,
        lease: WorkspaceLease,
    ) -> WorkspaceManifestRef:
        await self._assert_lease(workspace_id, task_id, lease)
        generation = base_ref.generation + 1
        manifest = WorkspaceManifest(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            workspace_id=workspace_id,
            task_id=task_id,
            generation=generation,
            base_generation=base_ref.generation,
            fencing_token=lease.fencing_token,
            entries=tuple(entries[path] for path in sorted(entries)),
        )
        body = _json_bytes(manifest.to_dict())
        digest = hashlib.sha256(body).hexdigest()
        manifest_key = self._key(workspace_id, task_id, f"manifests/{generation}-{digest}.json")
        await self._put_immutable(manifest_key, body, "application/json")
        next_ref = WorkspaceManifestRef(
            schema_version=WORKSPACE_SCHEMA_VERSION,
            workspace_id=workspace_id,
            task_id=task_id,
            generation=generation,
            manifest_uri=self._uri(manifest_key),
            manifest_sha256=digest,
            base_generation=base_ref.generation,
            fencing_token=lease.fencing_token,
        )
        await self._assert_lease(workspace_id, task_id, lease)
        await self._put_json(
            self._key(workspace_id, task_id, "current.json"),
            next_ref.to_dict(),
            if_match=pointer_etag,
        )
        return next_ref

    async def put(
        self,
        workspace_id: str,
        task_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
        **kwargs: Any,
    ) -> WorkspaceObject:
        ref = await self.put_files(
            workspace_id,
            task_id,
            {path: data},
            content_types={path: content_type} if content_type else None,
            **kwargs,
        )
        entry = await self._entry(workspace_id, task_id, path, ref=ref)
        return WorkspaceObject(
            path=entry.relative_path,
            size=entry.size,
            content_type=entry.content_type,
            sha256=entry.sha256,
            object_uri=entry.object_uri,
            generation=ref.generation,
        )

    async def _entry(
        self, workspace_id: str, task_id: str, path: str, *, ref: WorkspaceManifestRef | None = None
    ) -> WorkspaceEntry:
        clean = normalize_workspace_path(path)
        if ref is None:
            _, entries, _ = await self._snapshot(workspace_id, task_id)
        else:
            entries = await self._entries_for_ref(workspace_id, task_id, ref)
        entry = entries.get(clean)
        if entry is None or entry.deleted:
            raise FileNotFoundError(clean)
        return entry

    async def get(self, workspace_id: str, task_id: str, path: str) -> tuple[bytes, str | None]:
        entry = await self._entry(workspace_id, task_id, path)
        key = self._validate_uri(workspace_id, task_id, entry.object_uri)

        def call() -> tuple[bytes, str | None]:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
            if entry.object_version_or_etag.startswith("version:"):
                kwargs["VersionId"] = entry.object_version_or_etag.removeprefix("version:")
            elif entry.object_version_or_etag:
                kwargs["IfMatch"] = entry.object_version_or_etag
            try:
                response = self._client.get_object(**kwargs)
            except ClientError as exc:
                if _is_not_found(exc) or _is_precondition(exc):
                    raise WorkspaceValidationError(
                        f"workspace object identity is unavailable for {entry.relative_path!r}"
                    ) from exc
                raise
            data = response["Body"].read()
            if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise WorkspaceValidationError(f"workspace object verification failed for {path!r}")
            return data, entry.content_type

        return await asyncio.to_thread(call)

    async def stream(
        self,
        workspace_id: str,
        task_id: str,
        path: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> tuple[AsyncIterator[bytes], str | None, int]:
        """Verify an immutable object into a bounded spool before exposing bytes."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        entry = await self._entry(workspace_id, task_id, path)
        key = self._validate_uri(workspace_id, task_id, entry.object_uri)

        def open_object() -> Any:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
            if entry.object_version_or_etag.startswith("version:"):
                kwargs["VersionId"] = entry.object_version_or_etag.removeprefix("version:")
            else:
                kwargs["IfMatch"] = entry.object_version_or_etag
            try:
                return self._client.get_object(**kwargs)
            except ClientError as exc:
                if _is_not_found(exc) or _is_precondition(exc):
                    raise WorkspaceValidationError(
                        f"workspace object identity is unavailable for {entry.relative_path!r}"
                    ) from exc
                raise

        response = await asyncio.to_thread(open_object)
        body = response["Body"]
        reported_size = response.get("ContentLength")
        if reported_size is not None and int(reported_size) != entry.size:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            raise WorkspaceValidationError(
                f"workspace object verification failed for {entry.relative_path!r}"
            )

        spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        digest = hashlib.sha256()
        copied = 0
        try:
            while True:
                remaining_with_sentinel = max(1, entry.size - copied + 1)
                read_size = min(chunk_size, remaining_with_sentinel)
                chunk = await asyncio.to_thread(body.read, read_size)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > entry.size:
                    raise WorkspaceValidationError(
                        f"workspace object verification failed for {entry.relative_path!r}"
                    )
                digest.update(chunk)
                await asyncio.to_thread(spool.write, chunk)
            if copied != entry.size or digest.hexdigest() != entry.sha256:
                raise WorkspaceValidationError(
                    f"workspace object verification failed for {entry.relative_path!r}"
                )
            await asyncio.to_thread(spool.seek, 0)
        except Exception:
            spool.close()
            raise
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

        async def verified_chunks() -> AsyncIterator[bytes]:
            try:
                while chunk := await asyncio.to_thread(spool.read, chunk_size):
                    yield chunk
            finally:
                spool.close()

        return verified_chunks(), entry.content_type, entry.size

    async def get_object_ref(
        self,
        workspace_id: str,
        task_id: str,
        value: Mapping[str, Any],
    ) -> tuple[bytes, str | None]:
        """Read a verified immutable task object without requiring manifest membership.

        Sandbox stdout/stderr objects are uploaded under the active fenced
        execution and can be returned before a later manifest CAS makes them
        visible through ``list``. The credential-free reference is therefore
        verified against its authenticated task/object identity directly.
        """
        if not isinstance(value, Mapping):
            raise WorkspaceValidationError("workspace object reference must be a mapping")
        try:
            entry = WorkspaceEntry.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceValidationError("malformed workspace object reference") from exc
        # A content-addressed ref's identity is its sha256, not its size. An
        # empty stdout/stderr object has size 0, which may arrive as an absent
        # key; treat a missing size as 0 rather than rejecting a valid ref.
        raw_size = value.get("size", 0)
        if raw_size is None:
            raw_size = 0
        if (
            isinstance(raw_size, bool)
            or not isinstance(raw_size, int)
            or raw_size < 0
            or raw_size > self._max_file_bytes
            or entry.deleted
            or not _SHA256_RE.fullmatch(entry.sha256)
            or not entry.object_version_or_etag
        ):
            raise WorkspaceValidationError("workspace object reference identity is invalid")
        normalize_workspace_path(entry.relative_path)
        key = self._validate_uri(workspace_id, task_id, entry.object_uri)
        expected_key = self._key(workspace_id, task_id, f"objects/{entry.sha256}")
        if key != expected_key:
            raise WorkspaceValidationError("workspace object URI does not match its sha256")

        def call() -> tuple[bytes, str | None]:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
            if entry.object_version_or_etag.startswith("version:"):
                version_id = entry.object_version_or_etag.removeprefix("version:")
                if not version_id:
                    raise WorkspaceValidationError("workspace object version is empty")
                kwargs["VersionId"] = version_id
            else:
                kwargs["IfMatch"] = entry.object_version_or_etag
            try:
                response = self._client.get_object(**kwargs)
            except ClientError as exc:
                if _is_not_found(exc) or _is_precondition(exc):
                    raise WorkspaceValidationError(
                        f"workspace object identity is unavailable for {entry.relative_path!r}"
                    ) from exc
                raise
            data = response["Body"].read()
            if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise WorkspaceValidationError(
                    f"workspace object verification failed for {entry.relative_path!r}"
                )
            return data, entry.content_type

        return await asyncio.to_thread(call)

    async def exists(self, workspace_id: str, task_id: str, path: str) -> bool:
        try:
            await self._entry(workspace_id, task_id, path)
            return True
        except FileNotFoundError:
            return False

    async def list(
        self, workspace_id: str, task_id: str, prefix: str = "", max_items: int = 10_000
    ) -> list[WorkspaceObject]:
        clean_prefix = normalize_workspace_path(prefix) if prefix else ""
        ref, entries, _ = await self._snapshot(workspace_id, task_id)
        output: list[WorkspaceObject] = []
        for path in sorted(entries):
            entry = entries[path]
            if entry.deleted or (clean_prefix and not path.startswith(clean_prefix)):
                continue
            output.append(
                WorkspaceObject(
                    path=path,
                    size=entry.size,
                    content_type=entry.content_type,
                    sha256=entry.sha256,
                    object_uri=entry.object_uri,
                    generation=ref.generation,
                )
            )
            if len(output) >= max_items:
                break
        return output

    async def list_task_ids(self, workspace_id: str) -> list[str]:
        """Discover every canonical task prefix without scanning object histories."""
        if not _IDENTIFIER_RE.fullmatch(workspace_id or ""):
            raise WorkspaceValidationError("workspace_id must be an opaque identifier segment")
        prefix = f"{self._key_prefix}/" if self._key_prefix else ""
        tasks_prefix = f"{prefix}workspaces/{workspace_id}/tasks/"

        def call() -> list[str]:
            task_ids: set[str] = set()
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self._bucket,
                Prefix=tasks_prefix,
                Delimiter="/",
            ):
                for item in page.get("CommonPrefixes") or []:
                    common_prefix = str(item.get("Prefix") or "")
                    if not common_prefix.startswith(tasks_prefix):
                        continue
                    task_id = common_prefix[len(tasks_prefix) :].rstrip("/")
                    if not _IDENTIFIER_RE.fullmatch(task_id):
                        continue
                    try:
                        self._client.head_object(
                            Bucket=self._bucket,
                            Key=f"{common_prefix}current.json",
                        )
                    except ClientError as exc:
                        if _is_not_found(exc):
                            continue
                        raise
                    task_ids.add(task_id)
            return sorted(task_ids)

        return await asyncio.to_thread(call)

    async def delete(
        self,
        workspace_id: str,
        task_id: str,
        path: str,
        *,
        expected_generation: int | None = None,
        owner: str | None = None,
    ) -> WorkspaceManifestRef:
        clean = normalize_workspace_path(path)
        lease = await self._acquire_lease(
            workspace_id, task_id, owner or f"python-{uuid.uuid4().hex}"
        )
        try:
            ref, entries, pointer_etag = await self._snapshot(workspace_id, task_id)
            if expected_generation is not None and ref.generation != expected_generation:
                raise WorkspaceConflictError(
                    f"base generation {ref.generation} does not match expected {expected_generation}"
                )
            if clean not in entries or entries[clean].deleted:
                raise FileNotFoundError(clean)
            previous = entries[clean]
            entries[clean] = WorkspaceEntry(
                relative_path=clean,
                object_uri="",
                object_version_or_etag="",
                sha256="",
                size=0,
                content_type=previous.content_type,
                mode=previous.mode,
                deleted=True,
            )
            next_ref = await self._commit(workspace_id, task_id, ref, entries, pointer_etag, lease)
            await self._record(workspace_id, task_id, clean, ACTION_DELETED)
            return next_ref
        finally:
            await self._release_lease(workspace_id, task_id, lease)


# Concise production name used by dependency injection sites.
WorkspaceRepository = S3WorkspaceRepository
