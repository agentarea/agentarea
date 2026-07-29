"""Read-only tool for the organization context store (tier 1).

The org context store (``ArtifactService`` in production, workspace-scoped) is
the organization's durable knowledge. It is distinct from the agent's task
workspace (tier 2, the agent's own deliverable surface reached via the file
tools) and from the ephemeral sandbox filesystem (tier 3). This toolset exposes
READ access only: the sandbox never mutates the org store as a side effect, and
writing back to it is a separate, explicit capability.
"""

from __future__ import annotations

from .decorator_tool import Toolset, tool_method
from .file_toolset import InMemoryStorage, StorageClient
from .tool_definition import toolset


def _resolve_context_path(path: str) -> str:
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError(f"path escapes the context store: {path!r}")
    return path


@toolset(
    namespace="agentarea/context",
    display_name="Organization Context",
    description="Read files from the organization's durable context store (read-only).",
    category="utility",
    requires_user_confirmation=False,
)
class ContextToolset(Toolset):
    """Workspace-scoped READ access to the org context store (tier 1).

    Backed by an injected ``StorageClient`` (``ArtifactService`` in production),
    scoped by ``workspace_id``. There is no write or delete surface by design.
    """

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_id: str | None = None,
    ) -> None:
        super().__init__()
        self.storage: StorageClient = storage or InMemoryStorage()
        self.workspace_id: str = workspace_id or "_standalone"

    @tool_method
    async def list_context(self, prefix: str = "") -> str:
        """List files available in the organization context store.

        Args:
            prefix: Optional path prefix to filter by.

        Returns:
            A newline-separated list of file paths, or an error message.
        """
        try:
            objects = await self.storage.list(self.workspace_id, prefix=prefix)
        except Exception as e:
            return f"Error listing context: {e}"
        paths = sorted(
            str(getattr(obj, "path", "")) for obj in objects if getattr(obj, "path", None)
        )
        if not paths:
            return "No context files found."
        return "\n".join(paths)

    @tool_method
    async def read_context(self, path: str) -> str:
        """Read a text file from the organization context store.

        Args:
            path: Path of the file within the context store.

        Returns:
            The file's text content, or an error message.
        """
        try:
            resolved = _resolve_context_path(path)
        except ValueError as e:
            return f"Error: {e}"
        try:
            data, _ = await self.storage.get(self.workspace_id, resolved)
        except FileNotFoundError:
            return f"Error: context file {path} does not exist"
        except Exception as e:
            return f"Error reading context: {e}"
        return data.decode("utf-8")
