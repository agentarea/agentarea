"""S3-backed artifact storage, always scoped under a workspace.

Keys look like ``workspaces/{workspace_id}/{path}``. Callers pass the plain
``path`` (``tasks/{task_id}/file.png``, ``shared/notes.md``, …) and the
service prepends the workspace prefix so cross-tenant leaks are impossible
without passing a different ``workspace_id``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import mimetypes
import re
import tempfile
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from agentarea_common.artifacts.audit import (
    ACTION_ARCHIVED,
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    ArtifactActor,
    ArtifactEventRecorder,
)
from agentarea_common.config.aws import (
    get_aws_settings,
    get_s3_client,
    get_s3_public_client,
)

logger = logging.getLogger(__name__)

_WORKSPACE_PREFIX = "workspaces"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Archived files stay in the workspace under this prefix instead of being
# destroyed. Every listing that shows the workspace to a human or an agent must
# filter it out, so the prefix is defined once here and imported by callers.
TRASH_PREFIX = ".trash/"


def sha256_hex_from_head(head: Mapping[str, Any]) -> str | None:
    """Resolve an object's lowercase-hex sha256 from a HEAD response.

    Prefers the ``sha256`` user-metadata that :meth:`ArtifactService.put` writes;
    otherwise derives it from the S3-native ``ChecksumSHA256`` (base64 of the raw
    32-byte digest), which is all a presigned direct upload can guarantee. Returns
    ``None`` when neither is present so the caller can fail loudly rather than
    guess a digest. The HEAD must have been issued with ``ChecksumMode=ENABLED``
    for ``ChecksumSHA256`` to be populated.
    """
    meta_sha = str((head.get("Metadata") or {}).get("sha256") or "")
    if _SHA256_RE.fullmatch(meta_sha):
        return meta_sha
    checksum_b64 = head.get("ChecksumSHA256")
    if checksum_b64:
        try:
            digest = base64.b64decode(str(checksum_b64), validate=True)
        except (ValueError, TypeError):
            return None
        if len(digest) == 32:
            return digest.hex()
    return None


class ArtifactIntegrityError(RuntimeError):
    """The stored artifact cannot be verified against its immutable digest."""


@dataclass(frozen=True)
class ArtifactObject:
    path: str
    size: int
    content_type: str | None
    last_modified: str | None = None


class ArtifactService:
    """Workspace-scoped object store wrapper.

    Single client + single bucket. ``workspace_id`` is not optional on any
    method — pass it on every call.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        public_client: Any | None = None,
        bucket: str | None = None,
        recorder: ArtifactEventRecorder | None = None,
        actor: ArtifactActor | None = None,
    ) -> None:
        self._client = client or get_s3_client()
        # Presigned URLs must be signed against a host the external caller
        # can reach; in dev that's localhost:9000, not the in-docker
        # rustfs:9000. Falls back to the internal client when
        # PUBLIC_S3_ENDPOINT is unset (single-host setups).
        self._public_client = public_client or get_s3_public_client()
        self._bucket = bucket or get_aws_settings().ARTIFACTS_BUCKET_NAME
        # Provenance is only recorded when both a recorder and an actor are
        # supplied; read-only callers construct the service without either.
        self._recorder = recorder
        self._actor = actor

    async def _record(self, workspace_id: str, path: str, action: str) -> None:
        if self._recorder is None or self._actor is None:
            return
        try:
            await self._recorder.record(
                workspace_id=workspace_id,
                path=path.lstrip("/"),
                action=action,
                actor=self._actor,
            )
        except Exception:
            # Provenance is best-effort: never fail the file operation because
            # the audit row could not be written.
            logger.error(
                "Failed to record artifact event action=%s path=%s workspace=%s",
                action,
                path,
                workspace_id,
                exc_info=True,
            )

    @property
    def bucket(self) -> str:
        return self._bucket

    def _key(self, workspace_id: str, path: str) -> str:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        clean = path.lstrip("/")
        if ".." in clean.split("/"):
            raise ValueError(f"path may not contain '..' segments: {path!r}")
        return f"{_WORKSPACE_PREFIX}/{workspace_id}/{clean}"

    def _prefix(self, workspace_id: str, path: str = "") -> str:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        clean = path.lstrip("/")
        base = f"{_WORKSPACE_PREFIX}/{workspace_id}/"
        return f"{base}{clean}" if clean else base

    @staticmethod
    def _guess_content_type(path: str) -> str:
        ct, _ = mimetypes.guess_type(path)
        return ct or "application/octet-stream"

    async def put(
        self,
        workspace_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> ArtifactObject:
        key = self._key(workspace_id, path)
        ct = content_type or self._guess_content_type(path)
        digest = hashlib.sha256(data).hexdigest()

        # Distinguish a first write (created) from an overwrite (modified) for
        # provenance; only pay the extra head_object when we'll record it.
        existed = (
            await self.exists(workspace_id, path)
            if self._recorder is not None and self._actor is not None
            else False
        )

        def _call() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=ct,
                Metadata={"sha256": digest},
                ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
            )

        await asyncio.to_thread(_call)
        await self._record(workspace_id, path, ACTION_MODIFIED if existed else ACTION_CREATED)
        return ArtifactObject(path=path.lstrip("/"), size=len(data), content_type=ct)

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        key = self._key(workspace_id, path)

        def _call() -> tuple[bytes, str | None]:
            try:
                resp = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "404"}:
                    raise FileNotFoundError(path) from e
                raise
            return resp["Body"].read(), resp.get("ContentType")

        return await asyncio.to_thread(_call)

    async def stream(
        self,
        workspace_id: str,
        path: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> tuple[AsyncIterator[bytes], str | None, int]:
        """Verify into a bounded spool before yielding any artifact bytes."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        key = self._key(workspace_id, path)

        def open_object() -> Any:
            try:
                return self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "404", "NotFound"}:
                    raise FileNotFoundError(path) from exc
                raise

        response = await asyncio.to_thread(open_object)
        body = response["Body"]
        size = int(response.get("ContentLength") or 0)
        digest = str((response.get("Metadata") or {}).get("sha256") or "")
        if not _SHA256_RE.fullmatch(digest):
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            raise ArtifactIntegrityError(f"artifact integrity digest is missing for {path!r}")

        spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        hasher = hashlib.sha256()
        copied = 0
        try:
            while True:
                remaining_with_sentinel = max(1, size - copied + 1)
                read_size = min(chunk_size, remaining_with_sentinel)
                chunk = await asyncio.to_thread(body.read, read_size)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > size:
                    raise ArtifactIntegrityError(f"artifact verification failed for {path!r}")
                hasher.update(chunk)
                await asyncio.to_thread(spool.write, chunk)
            if copied != size or hasher.hexdigest() != digest:
                raise ArtifactIntegrityError(f"artifact verification failed for {path!r}")
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

        return verified_chunks(), response.get("ContentType"), size

    async def exists(self, workspace_id: str, path: str) -> bool:
        key = self._key(workspace_id, path)

        def _call() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return False
                raise

        return await asyncio.to_thread(_call)

    async def delete(self, workspace_id: str, path: str) -> None:
        key = self._key(workspace_id, path)

        def _call() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(_call)
        await self._record(workspace_id, path, ACTION_DELETED)

    async def copy(self, workspace_id: str, source: str, destination: str) -> None:
        """Copy one workspace path onto another, server-side.

        The bytes never leave the object store, so this is cheap regardless of
        file size. ``MetadataDirective`` is left at its ``COPY`` default so the
        sha256 user-metadata written by :meth:`put` survives the move.
        """
        source_key = self._key(workspace_id, source)
        destination_key = self._key(workspace_id, destination)

        def _call() -> None:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=destination_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )

        await asyncio.to_thread(_call)

    async def archive(self, workspace_id: str, path: str) -> str:
        """Move a file into the trash prefix and return its archived path.

        Deletion through the API is never destructive: the object is copied
        under ``.trash/{timestamp}/{path}`` first, and only then removed from
        its original location. Timestamps carry microseconds so archiving the
        same path repeatedly keeps every generation instead of overwriting the
        previous one.
        """
        clean = path.lstrip("/")
        if not await self.exists(workspace_id, clean):
            raise FileNotFoundError(clean)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        archived_path = f"{TRASH_PREFIX}{stamp}/{clean}"
        await self.copy(workspace_id, clean, archived_path)

        key = self._key(workspace_id, clean)

        def _call() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(_call)
        await self._record(workspace_id, clean, ACTION_ARCHIVED)
        return archived_path

    async def list(
        self,
        workspace_id: str,
        prefix: str = "",
        max_items: int = 1000,
    ) -> list[ArtifactObject]:
        full_prefix = self._prefix(workspace_id, prefix)
        prefix_len = len(self._prefix(workspace_id, ""))

        def _call() -> list[ArtifactObject]:
            out: list[ArtifactObject] = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    rel = key[prefix_len:]
                    if not rel:
                        continue
                    out.append(
                        ArtifactObject(
                            path=rel,
                            size=obj["Size"],
                            content_type=self._guess_content_type(rel),
                            last_modified=obj["LastModified"].isoformat()
                            if obj.get("LastModified")
                            else None,
                        )
                    )
                    if len(out) >= max_items:
                        return out
            return out

        return await asyncio.to_thread(_call)

    async def presigned_url(
        self,
        workspace_id: str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        key = self._key(workspace_id, path)

        def _call() -> str:
            return self._public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        return await asyncio.to_thread(_call)

    async def presigned_put_url(
        self,
        workspace_id: str,
        path: str,
        *,
        content_type: str | None = None,
        sha256_b64: str | None = None,
        expires_in: int = 3600,
    ) -> str:
        """Sign a direct-upload URL against the externally reachable endpoint.

        When ``sha256_b64`` is supplied the digest is bound into the signature
        as ``ChecksumSHA256``; the object store then rejects a body whose
        content does not hash to it, so the upload is content-verified without
        trusting the client.
        """
        key = self._key(workspace_id, path)

        def _call() -> str:
            params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
            if content_type is not None:
                params["ContentType"] = content_type
            if sha256_b64 is not None:
                params["ChecksumSHA256"] = sha256_b64
            return self._public_client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_in,
            )

        return await asyncio.to_thread(_call)

    async def head(self, workspace_id: str, path: str) -> dict[str, Any] | None:
        """Return ``{size, content_type, metadata}`` or ``None`` when absent."""
        key = self._key(workspace_id, path)

        def _call() -> dict[str, Any] | None:
            try:
                resp = self._client.head_object(
                    Bucket=self._bucket, Key=key, ChecksumMode="ENABLED"
                )
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return None
                raise
            return {
                "size": int(resp.get("ContentLength") or 0),
                "content_type": resp.get("ContentType"),
                "metadata": dict(resp.get("Metadata") or {}),
                "sha256": sha256_hex_from_head(resp),
            }

        return await asyncio.to_thread(_call)
