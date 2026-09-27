"""Where a manual write may land in workspace storage.

Shared by every surface that writes a file on a caller's behalf (the REST
upload, the MCP upload tool), so they accept and refuse the same paths.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Protocol

from .service import TRASH_PREFIX
from .workspace import WorkspaceConflictError, WorkspaceValidationError, normalize_workspace_path

# ``staging/`` holds half-finished attachment uploads, ``tasks/`` is the
# task-owned surface reached through committed manifests, and ``.trash/`` holds
# archived files that only the restore endpoint may resurrect.
RESERVED_PREFIXES = frozenset({"tasks", "staging", TRASH_PREFIX.rstrip("/")})


class _Store(Protocol):
    async def exists(self, workspace_id: str, path: str) -> bool: ...

    async def list(self, workspace_id: str, prefix: str = "", max_items: int = 1000) -> Any: ...


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
