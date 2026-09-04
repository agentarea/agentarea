"""File tool backed by the task's selected workspace storage.

Every call is issued against an injected ``StorageClient``. Agent execution
injects ``SandboxFileStore`` so file and shell tools see the same live
``/workspace`` filesystem. Durable publication is a separate explicit artifact
operation. Standalone SDK usage retains a tiny in-memory store for examples.

The public tool method names (``save_file``/``read_file``/``list_files``/
``search_files``) are kept because LLMs have mental models around them — the
switch to object storage is invisible to the agent.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .decorator_tool import Toolset, tool_method
from .tool_definition import toolset

# Extensions whose files are binary: writing them as UTF-8 text corrupts the
# payload. save_file is text-only, so it refuses these and directs the agent to
# generate them via the shell (enforcement, not a prompt hint).
_BINARY_EXTENSIONS = frozenset(
    {
        "xlsx",
        "xls",
        "pptx",
        "ppt",
        "docx",
        "doc",
        "pdf",
        "zip",
        "gz",
        "tar",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "ico",
        "tiff",
        "mp3",
        "mp4",
        "wav",
        "ogg",
        "webm",
        "mov",
        "parquet",
        "sqlite",
        "db",
    }
)


@dataclass(frozen=True)
class StoredObject:
    path: str
    size: int
    content_type: str | None = None


class StorageClient(Protocol):
    """Minimal async object-store contract the FileToolset speaks.

    Implementations must scope writes by ``workspace_id``. See
    ``agentarea_common.artifacts.ArtifactService`` for the production impl.
    """

    async def put(
        self,
        workspace_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> Any: ...

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]: ...

    async def exists(self, workspace_id: str, path: str) -> bool: ...

    async def list(self, workspace_id: str, prefix: str = "") -> list[Any]: ...

    async def delete(self, workspace_id: str, path: str) -> None: ...


class WorkspaceRepositoryClient(Protocol):
    """Generation-aware task workspace contract used by SDK toolsets."""

    async def put(
        self,
        workspace_id: str,
        task_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
        **kwargs: Any,
    ) -> Any: ...

    async def get(self, workspace_id: str, task_id: str, path: str) -> tuple[bytes, str | None]: ...

    async def exists(self, workspace_id: str, task_id: str, path: str) -> bool: ...

    async def list(
        self, workspace_id: str, task_id: str, prefix: str = "", max_items: int = 10_000
    ) -> list[Any]: ...

    async def delete(self, workspace_id: str, task_id: str, path: str, **kwargs: Any) -> Any: ...

    async def current_manifest_ref(self, workspace_id: str, task_id: str) -> Any: ...

    async def checkout_for_execution(
        self, workspace_id: str, task_id: str, *, owner: str
    ) -> Any: ...

    async def release_execution_lease(
        self,
        workspace_id: str,
        task_id: str,
        manifest_ref: Mapping[str, Any] | Any,
        *,
        owner: str,
    ) -> None: ...

    async def import_workspace_prefix(
        self,
        workspace_id: str,
        task_id: str,
        *,
        source_prefix: str,
        target_prefix: str,
        provenance: Mapping[str, str] | None = None,
        owner: str | None = None,
    ) -> Any: ...

    async def put_files(
        self,
        workspace_id: str,
        task_id: str,
        files: Mapping[str, bytes],
        **kwargs: Any,
    ) -> Any: ...


class InMemoryStorage:
    """Workspace-scoped dict-backed store for tests and examples."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], tuple[bytes, str | None]] = {}

    async def put(
        self,
        workspace_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        key = (workspace_id, path.lstrip("/"))
        self._data[key] = (data, content_type)
        return StoredObject(path=key[1], size=len(data), content_type=content_type)

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        key = (workspace_id, path.lstrip("/"))
        if key not in self._data:
            raise FileNotFoundError(path)
        return self._data[key]

    async def exists(self, workspace_id: str, path: str) -> bool:
        return (workspace_id, path.lstrip("/")) in self._data

    async def list(self, workspace_id: str, prefix: str = "") -> list[StoredObject]:
        clean = prefix.lstrip("/")
        out: list[StoredObject] = []
        for (ws, path), (data, ct) in self._data.items():
            if ws != workspace_id:
                continue
            if clean and not path.startswith(clean):
                continue
            out.append(StoredObject(path=path, size=len(data), content_type=ct))
        return out

    async def delete(self, workspace_id: str, path: str) -> None:
        self._data.pop((workspace_id, path.lstrip("/")), None)


@toolset(
    namespace="agentarea/files",
    display_name="File Operations",
    description="Read, write, list, and search files in the agent's workspace storage.",
    category="utility",
    requires_user_confirmation=True,
)
class FileToolset(Toolset):
    """Workspace-scoped file operations on top of a StorageClient.

    All keys are resolved under ``{base_prefix}/{file_name}``. ``base_prefix``
    typically encodes task scope (``tasks/{task_id}``) or shared workspace
    scope (``shared``) — the platform chooses, the toolset doesn't care.
    """

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_repository: WorkspaceRepositoryClient | None = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        lease_owner: str | None = None,
        base_prefix: str = "",
        save_files: bool = True,
        read_files: bool = True,
        list_files: bool = True,
        search_files: bool = True,
    ) -> None:
        super().__init__()
        self.storage: StorageClient = storage or InMemoryStorage()
        self.workspace_repository = workspace_repository
        self.workspace_id: str = workspace_id or "_standalone"
        self.task_id = task_id or ""
        self.lease_owner = lease_owner or ""
        self.base_prefix: str = base_prefix.strip("/")
        self._save_files_enabled = save_files
        self._read_files_enabled = read_files
        self._list_files_enabled = list_files
        self._search_files_enabled = search_files

    def _resolve(self, file_name: str) -> str:
        if file_name.startswith("/"):
            raise ValueError(f"path escapes workspace sandbox: {file_name!r}")
        name = file_name
        if not name or ".." in name.split("/") or "\\" in name:
            raise ValueError(f"path escapes workspace sandbox: {file_name!r}")
        if self.workspace_repository is not None:
            return name
        if self.base_prefix:
            return f"{self.base_prefix}/{name}"
        return name

    @tool_method
    async def save_file(self, contents: str, file_name: str, overwrite: bool = True) -> str:
        """Save ``contents`` as a text file in the live task workspace.

        Args:
            contents: Text content. Use a generator tool for binary payloads.
            file_name: Name relative to the task scope.
            overwrite: Error out if the key already exists and this is False.

        Returns:
            The file name on success, or an error message.
        """
        if not self._save_files_enabled:
            return "Error: save_file is disabled for this toolset instance"
        _ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if _ext in _BINARY_EXTENSIONS:
            return (
                f"Error: save_file writes UTF-8 text only and would corrupt a .{_ext} file. "
                "Produce binary deliverables by running a program in the shell that writes the "
                "file into your workspace."
            )
        try:
            path = self._resolve(file_name)
            if not overwrite and await self._exists(path):
                return f"File {file_name} already exists"
            if self.workspace_repository is not None:
                self._require_task()
                await self.workspace_repository.put(
                    self.workspace_id,
                    self.task_id,
                    path,
                    contents.encode("utf-8"),
                    "text/plain; charset=utf-8",
                    owner=self.lease_owner or None,
                )
            else:
                await self.storage.put(
                    self.workspace_id,
                    path,
                    contents.encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
            return file_name
        except Exception as e:
            return f"Error saving to file: {e}"

    @tool_method
    async def read_file(self, file_name: str) -> str:
        """Read a text file from the live task workspace.

        Binary objects (images, PDFs) should be fetched through the
        authenticated AgentArea file API; this method always decodes as UTF-8.
        """
        if not self._read_files_enabled:
            return "Error: read_file is disabled for this toolset instance"
        try:
            path = self._resolve(file_name)
            if self.workspace_repository is not None:
                self._require_task()
                data, _ = await self.workspace_repository.get(self.workspace_id, self.task_id, path)
            else:
                data, _ = await self.storage.get(self.workspace_id, path)
            return data.decode("utf-8")
        except FileNotFoundError:
            return f"Error: File {file_name} does not exist"
        except Exception as e:
            return f"Error reading file: {e}"

    @tool_method
    async def list_files(self, pattern: str = "*") -> str:
        """List files under the task scope, optionally filtered by glob pattern.

        The pattern matches against the file name relative to the task scope,
        so ``*.txt`` returns every text file the agent has written in this
        task's sandbox.
        """
        if not self._list_files_enabled:
            return "Error: list_files is disabled for this toolset instance"
        try:
            objects = await self._list()
            names = [self._relative(o) for o in objects]
            matched = (
                [n for n in names if fnmatch.fnmatch(n, pattern)]
                if pattern and pattern != "*"
                else names
            )
            return json.dumps(
                {
                    "scope": self.base_prefix or "/",
                    "pattern": pattern,
                    "files_found": len(matched),
                    "files": sorted(matched),
                },
                indent=2,
            )
        except Exception as e:
            return f"Error listing files: {e}"

    @tool_method
    async def search_files(self, pattern: str) -> str:
        """Search the task scope for files whose name matches a glob pattern.

        Equivalent to ``list_files`` with the pattern applied — the split
        exists to keep tool semantics explicit for the LLM.
        """
        if not self._search_files_enabled:
            return "Error: search_files is disabled for this toolset instance"
        try:
            if not pattern or not pattern.strip():
                return "Error: Pattern cannot be empty"
            objects = await self._list()
            names = [self._relative(o) for o in objects]
            matched = [n for n in names if fnmatch.fnmatch(n, pattern)]
            return json.dumps(
                {
                    "pattern": pattern,
                    "scope": self.base_prefix or "/",
                    "matches_found": len(matched),
                    "files": sorted(matched),
                },
                indent=2,
            )
        except Exception as e:
            return f"Error searching files with pattern '{pattern}': {e}"

    def _relative(self, obj: Any) -> str:
        raw = getattr(obj, "path", None)
        if raw is None and isinstance(obj, dict):
            raw = obj.get("path")
        path = str(raw or "")
        if self.base_prefix and path.startswith(self.base_prefix + "/"):
            return path[len(self.base_prefix) + 1 :]
        return path

    def _require_task(self) -> None:
        if not self.task_id:
            raise ValueError("task_id is required for canonical workspace operations")

    async def _exists(self, path: str) -> bool:
        if self.workspace_repository is None:
            return await self.storage.exists(self.workspace_id, path)
        self._require_task()
        return await self.workspace_repository.exists(self.workspace_id, self.task_id, path)

    async def _list(self) -> list[Any]:
        if self.workspace_repository is None:
            return await self.storage.list(self.workspace_id, prefix=self.base_prefix)
        self._require_task()
        return await self.workspace_repository.list(self.workspace_id, self.task_id)
