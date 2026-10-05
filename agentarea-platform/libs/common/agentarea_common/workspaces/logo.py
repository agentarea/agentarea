"""Workspace logo storage.

Logos share the artifacts bucket but live under ``workspace-logos/``, outside
``workspaces/{workspace_id}/``: that prefix is the file tree agents list, read
and write, and a logo is not theirs to see or replace. Keys are the sha256 of
the bytes, so a replaced logo gets a new URL.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_common.config.aws import get_aws_settings, get_s3_client, get_s3_public_client

from .models import Workspace
from .repository import WorkspaceRepository

LOGO_MAX_BYTES = 1024 * 1024
_LOGO_PREFIX = "workspace-logos"


def logo_content_type(data: bytes) -> str | None:
    """The image type *data* is, read from its magic bytes; ``None`` unless PNG, JPEG or WebP."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class WorkspaceLogoStore:
    """Object store for workspace logos; clients are built on first use."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        public_client: Any | None = None,
        bucket: str | None = None,
    ) -> None:
        self._client = client
        self._public_client = public_client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        if self._bucket is None:
            self._bucket = get_aws_settings().ARTIFACTS_BUCKET
        return self._bucket

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_s3_client()
        return self._client

    @property
    def public_client(self) -> Any:
        if self._public_client is None:
            self._public_client = get_s3_public_client()
        return self._public_client

    async def put(self, workspace_id: str, data: bytes, content_type: str) -> str:
        """Store *data* as *workspace_id*'s logo and return its key."""
        if not workspace_id:
            raise ValueError("workspace_id is required")
        key = f"{_LOGO_PREFIX}/{workspace_id}/{hashlib.sha256(data).hexdigest()}"

        def _call() -> None:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_call)
        return key

    async def delete(self, key: str) -> None:
        def _call() -> None:
            self.client.delete_object(Bucket=self.bucket, Key=key)

        await asyncio.to_thread(_call)

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        def _call() -> str:
            return self.public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        return await asyncio.to_thread(_call)


class WorkspaceLogoError(Exception):
    """A logo change that cannot be made; the message is safe to show the caller."""


class LogoTooLargeError(WorkspaceLogoError):
    def __init__(self) -> None:
        super().__init__(f"Logo exceeds the {LOGO_MAX_BYTES}-byte limit")


class UnsupportedLogoTypeError(WorkspaceLogoError):
    def __init__(self) -> None:
        super().__init__("Logo must be a PNG, JPEG or WebP image")


class WorkspaceNotFoundError(WorkspaceLogoError):
    def __init__(self) -> None:
        super().__init__("Workspace not found")


class WorkspaceLogoService:
    """Sets and clears a workspace's logo: the object, the ``logo_key`` column, the old object."""

    def __init__(
        self, session: AsyncSession, workspaces: WorkspaceRepository, store: WorkspaceLogoStore
    ) -> None:
        self._session = session
        self._workspaces = workspaces
        self._store = store

    async def _workspace(self, workspace_id: str) -> Workspace:
        workspace = await self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError
        return workspace

    async def set(self, workspace_id: str, data: bytes) -> Workspace:
        """Make *data* the logo, replacing and deleting any previous one."""
        if len(data) > LOGO_MAX_BYTES:
            raise LogoTooLargeError
        content_type = logo_content_type(data)
        if content_type is None:
            raise UnsupportedLogoTypeError

        workspace = await self._workspace(workspace_id)
        previous = workspace.logo_key
        workspace.logo_key = await self._store.put(workspace.id, data, content_type)
        await self._session.commit()
        if previous is not None and previous != workspace.logo_key:
            await self._store.delete(previous)
        return workspace

    async def remove(self, workspace_id: str) -> Workspace:
        """Clear the logo and delete its object; a workspace without one is left as is."""
        workspace = await self._workspace(workspace_id)
        previous = workspace.logo_key
        if previous is not None:
            workspace.logo_key = None
            await self._session.commit()
            await self._store.delete(previous)
        return workspace
