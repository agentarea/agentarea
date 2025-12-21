"""Filesystem middleware for virtual FS and context eviction."""

from typing import Any


class FilesystemMiddleware:
    """Manages virtual filesystem and context eviction."""

    def __init__(self, eviction_threshold: int = 80_000):
        self.eviction_threshold = eviction_threshold

    async def before_llm_call(self, state: dict) -> dict[str, Any] | None:
        if "files" not in state:
            return {"files": {}}
        return None

    async def after_llm_call(self, state: dict, response) -> dict[str, Any] | None:
        return None

    async def before_tool_call(
        self, tool_call: dict, state: dict
    ) -> tuple[dict, dict[str, Any] | None]:
        return tool_call, None

    async def after_tool_call(
        self, tool_call: dict, result: Any, state: dict
    ) -> tuple[Any, dict[str, Any] | None]:
        state_updates = None

        # Context eviction for large results
        if isinstance(result, str) and len(result) > self.eviction_threshold:
            file_path = f"/large_tool_results/{tool_call.get('id', 'unknown')}"

            # Store in virtual FS
            files = state.get("files", {})
            files[file_path] = result

            state_updates = {"files": files}

            # Replace result with eviction notice
            result = {
                "evicted": True,
                "original_size": len(result),
                "file_path": file_path,
                "message": f"Result too large ({len(result)} chars). Saved to {file_path}. Use read_file() to access.",
            }

            return result, state_updates

        # Handle file write operations
        tool_name = tool_call.get("function", {}).get("name")
        if tool_name in ["write_file", "save_file"]:
            args = tool_call.get("function", {}).get("arguments", {})
            path = args.get("file_name") or args.get("path")
            content = args.get("contents") or args.get("content")

            if path and content:
                files = state.get("files", {})
                files[path] = content
                state_updates = {"files": files}

        return result, state_updates
