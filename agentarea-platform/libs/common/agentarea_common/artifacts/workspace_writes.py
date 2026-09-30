"""Where a manual write may land in workspace storage.

Shared by every surface that writes a file on a caller's behalf (the REST
upload-plan endpoints, folder moves, the MCP upload tool), so they accept and
refuse the same paths.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Protocol

from .service import MAX_WRITE_PATH_BYTES, TRASH_PREFIX
from .workspace import (
    WorkspaceConflictError,
    WorkspaceError,
    WorkspaceValidationError,
    normalize_workspace_path,
)

MAX_UPLOADS_PER_PLAN = 100

# ``staging/`` holds half-finished attachment uploads, ``tasks/`` is the
# task-owned surface reached through committed manifests, and ``.trash/`` holds
# archived files that only the restore endpoint may resurrect.
RESERVED_PREFIXES = frozenset({"tasks", "staging", TRASH_PREFIX.rstrip("/")})


class _Store(Protocol):
    async def exists(self, workspace_id: str, path: str) -> bool: ...

    async def list(self, workspace_id: str, prefix: str = "", max_items: int = 1000) -> Any: ...


class _PlanningStore(_Store, Protocol):
    async def head(self, workspace_id: str, path: str) -> dict[str, Any] | None: ...

    async def authorize_put(
        self, workspace_id: str, path: str, *, sha256_hex: str, content_type: str | None = None
    ) -> Any: ...


def is_reserved_path(path: str) -> bool:
    parts = PurePosixPath(path.lstrip("/")).parts
    return bool(parts and parts[0] in RESERVED_PREFIXES)


def resolve_write_path(path: str, filename: str = "") -> str:
    """Canonical path for a write, or ``WorkspaceValidationError``.

    An explicit ``path`` keeps the directory structure the caller sent. Without
    one the file lands at the workspace root under its own name.
    """
    if not path:
        path = PurePosixPath(filename or "unnamed").name or "unnamed"
    resolved = normalize_workspace_path(path)
    if len(resolved.encode()) > MAX_WRITE_PATH_BYTES:
        raise WorkspaceValidationError(
            f"workspace path exceeds {MAX_WRITE_PATH_BYTES} bytes of UTF-8"
        )
    if is_reserved_path(resolved):
        raise WorkspaceValidationError(
            f"{resolved!r} is a reserved prefix and cannot be written directly"
        )
    return resolved


async def ensure_no_file_ancestors(store: _Store, workspace_id: str, path: str) -> None:
    """Prevent an existing file from also becoming a parent folder."""
    for parent in PurePosixPath(path).parents:
        if parent != PurePosixPath(".") and await store.exists(workspace_id, str(parent)):
            raise WorkspaceConflictError(f"A file already exists at {str(parent)!r}")


async def ensure_writable_file(store: _Store, workspace_id: str, path: str) -> None:
    await ensure_no_file_ancestors(store, workspace_id, path)
    if await store.list(workspace_id, prefix=f"{path}/", max_items=1):
        raise WorkspaceConflictError("A folder already exists at this path")


async def plan_uploads(store: _PlanningStore, workspace_id: str, entries: list[Any]) -> list[dict]:
    """Decide, per ``{path, sha256, content_type?}``, what a client must upload.

    A file already stored under the same digest is ``unchanged``; anything else
    that may be written gets a presigned PUT (``upload``); the rest is reported
    as ``error`` without blocking its siblings. This is the manifest diff that
    lets a sync send only what changed.
    """
    return [await _plan_one(store, workspace_id, entry) for entry in entries]


async def _plan_one(store: _PlanningStore, workspace_id: str, entry: Any) -> dict:
    if not isinstance(entry, dict):
        return {"path": "", "status": "error", "error": "each entry needs a path and a sha256"}
    path = str(entry.get("path") or "")
    if not path:
        return {"path": path, "status": "error", "error": "path is required"}
    sha256 = str(entry.get("sha256") or "")
    try:
        resolved = resolve_write_path(path)
        head = await store.head(workspace_id, resolved)
        if head is not None and head.get("sha256") == sha256:
            return {"path": resolved, "status": "unchanged"}
        await ensure_writable_file(store, workspace_id, resolved)
        put = await store.authorize_put(
            workspace_id,
            resolved,
            sha256_hex=sha256,
            content_type=entry.get("content_type") or None,
        )
    except (WorkspaceError, ValueError) as exc:
        return {"path": path, "status": "error", "error": str(exc)}
    return {
        "path": resolved,
        "status": "upload",
        "upload_url": put.url,
        "method": "PUT",
        "headers": put.headers,
        "expires_in": put.expires_in,
    }
