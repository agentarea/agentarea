"""File tool backed by a workspace-scoped object store.

Every call is issued against an injected ``StorageClient``. In production the
platform injects an S3-backed ``ArtifactService`` (RustFS locally, real S3 in
cloud). For standalone SDK usage we fall back to a tiny in-memory store so
examples and unit tests keep working without pulling boto3.

The public tool method names (``save_file``/``read_file``/``list_files``/
``search_files``) are kept because LLMs have mental models around them — the
switch to object storage is invisible to the agent.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .decorator_tool import Toolset, tool_method


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

    async def get(
        self, workspace_id: str, path: str
    ) -> tuple[bytes, str | None]: ...

    async def exists(self, workspace_id: str, path: str) -> bool: ...

    async def list(
        self, workspace_id: str, prefix: str = ""
    ) -> list[Any]: ...

    async def delete(self, workspace_id: str, path: str) -> None: ...


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

    async def get(
        self, workspace_id: str, path: str
    ) -> tuple[bytes, str | None]:
        key = (workspace_id, path.lstrip("/"))
        if key not in self._data:
            raise FileNotFoundError(path)
        return self._data[key]

    async def exists(self, workspace_id: str, path: str) -> bool:
        return (workspace_id, path.lstrip("/")) in self._data

    async def list(
        self, workspace_id: str, prefix: str = ""
    ) -> list[StoredObject]:
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


class FileToolset(Toolset):
    """Workspace-scoped file operations on top of a StorageClient.

    All keys are resolved under ``{base_prefix}/{file_name}``. ``base_prefix``
    typically encodes task scope (``tasks/{task_id}``) or shared workspace
    scope (``shared``) — the platform chooses, the toolset doesn't care.
    """

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_id: str | None = None,
        base_prefix: str = "",
        save_files: bool = True,
        read_files: bool = True,
        list_files: bool = True,
        search_files: bool = True,
    ) -> None:
        super().__init__()
        self.storage: StorageClient = storage or InMemoryStorage()
        self.workspace_id: str = workspace_id or "_standalone"
        self.base_prefix: str = base_prefix.strip("/")
        self._save_files_enabled = save_files
        self._read_files_enabled = read_files
        self._list_files_enabled = list_files
        self._search_files_enabled = search_files

    def _resolve(self, file_name: str) -> str:
        name = file_name.lstrip("/")
        if ".." in name.split("/"):
            raise ValueError(f"path escapes workspace sandbox: {file_name!r}")
        if self.base_prefix:
            return f"{self.base_prefix}/{name}"
        return name

    @tool_method
    async def save_file(
        self, contents: str, file_name: str, overwrite: bool = True
    ) -> str:
        """Save ``contents`` as a text file under the task's artifact scope.

        Args:
            contents: Text content. Use a generator tool for binary payloads.
            file_name: Name relative to the task scope.
            overwrite: Error out if the key already exists and this is False.

        Returns:
            The file name on success, or an error message.
        """
        if not self._save_files_enabled:
            return "Error: save_file is disabled for this toolset instance"
        try:
            path = self._resolve(file_name)
            if not overwrite and await self.storage.exists(self.workspace_id, path):
                return f"File {file_name} already exists"
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
        """Read a text file from the task's artifact scope.

        Binary objects (images, PDFs) should be fetched by a dedicated tool
        that returns a presigned URL; this method always decodes as UTF-8.
        """
        if not self._read_files_enabled:
            return "Error: read_file is disabled for this toolset instance"
        try:
            path = self._resolve(file_name)
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
            objects = await self.storage.list(self.workspace_id, prefix=self.base_prefix)
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
            objects = await self.storage.list(self.workspace_id, prefix=self.base_prefix)
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
        path = getattr(obj, "path", None) or (obj.get("path") if isinstance(obj, dict) else "")
        if self.base_prefix and path.startswith(self.base_prefix + "/"):
            return path[len(self.base_prefix) + 1 :]
        return path
