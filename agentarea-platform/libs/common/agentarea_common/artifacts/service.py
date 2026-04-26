"""S3-backed artifact storage, always scoped under a workspace.

Keys look like ``workspaces/{workspace_id}/{path}``. Callers pass the plain
``path`` (``tasks/{task_id}/file.png``, ``shared/notes.md``, …) and the
service prepends the workspace prefix so cross-tenant leaks are impossible
without passing a different ``workspace_id``.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from agentarea_common.config.aws import (
    get_aws_settings,
    get_s3_client,
    get_s3_public_client,
)

logger = logging.getLogger(__name__)

_WORKSPACE_PREFIX = "workspaces"


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
    ) -> None:
        self._client = client or get_s3_client()
        # Presigned URLs must be signed against a host the external caller
        # can reach; in dev that's localhost:9000, not the in-docker
        # rustfs:9000. Falls back to the internal client when
        # PUBLIC_S3_ENDPOINT is unset (single-host setups).
        self._public_client = public_client or get_s3_public_client()
        self._bucket = bucket or get_aws_settings().ARTIFACTS_BUCKET_NAME

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

        def _call() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=ct,
            )

        await asyncio.to_thread(_call)
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
