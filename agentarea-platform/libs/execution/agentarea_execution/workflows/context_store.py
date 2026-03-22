"""MinIO-backed storage for offloaded context.

Used inside Temporal activities only — never in workflow code directly.
Follows the same lazy-loading pattern as SkillStorageService.
"""

import json
import logging
import re
from typing import Any


class ContextStore:
    """Manages offloaded context in MinIO for a task execution.

    Stores large tool outputs and compacted message history to MinIO,
    allowing agents to selectively read back via grep/head/tail.
    """

    def __init__(self, workspace_id: str, task_id: str):
        self._client = None
        self._settings = None
        self.workspace_id = workspace_id
        self.task_id = task_id

    @property
    def client(self):
        if self._client is None:
            from agentarea_common.config.aws import get_s3_client

            self._client = get_s3_client()
        return self._client

    @property
    def bucket(self) -> str:
        if self._settings is None:
            from agentarea_common.config.aws import get_aws_settings

            self._settings = get_aws_settings()
        return self._settings.S3_BUCKET_NAME

    @property
    def prefix(self) -> str:
        return f"tasks/{self.workspace_id}/{self.task_id}"

    # --- Tool outputs ---

    async def store_output(self, output_id: str, content: str) -> None:
        """Store a tool output to MinIO."""
        key = f"{self.prefix}/outputs/{output_id}.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    async def read_output(
        self,
        output_id: str,
        grep: str | None = None,
        head: int | None = None,
        tail: int | None = None,
    ) -> str:
        """Read a stored tool output with optional filtering.

        Args:
            output_id: The output identifier.
            grep: Regex pattern to filter lines.
            head: Return only the first N lines.
            tail: Return only the last N lines.

        Returns:
            Filtered content string.
        """
        from .constants import READ_OUTPUT_MAX_RETURN_CHARS

        key = f"{self.prefix}/outputs/{output_id}.json"
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        content = response["Body"].read().decode("utf-8")

        lines = content.split("\n")

        if grep:
            try:
                pattern = re.compile(grep, re.IGNORECASE)
                lines = [line for line in lines if pattern.search(line)]
            except re.error:
                # Invalid regex — treat as literal substring match
                lines = [line for line in lines if grep in line]

        if head is not None and head > 0:
            lines = lines[:head]
        elif tail is not None and tail > 0:
            lines = lines[-tail:]

        result = "\n".join(lines)

        # Safety limit
        if len(result) > READ_OUTPUT_MAX_RETURN_CHARS:
            result = (
                result[:READ_OUTPUT_MAX_RETURN_CHARS]
                + f"\n... [truncated at {READ_OUTPUT_MAX_RETURN_CHARS} chars]"
            )

        return result

    # --- History chunks ---

    async def store_history_chunk(self, chunk_index: int, messages: list[dict[str, Any]]) -> None:
        """Store a chunk of compacted messages to MinIO."""
        key = f"{self.prefix}/history/chunk_{chunk_index}.json"
        body = json.dumps(messages, default=str, ensure_ascii=False)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

    async def search_history(
        self,
        grep: str | None = None,
        tool_name: str | None = None,
    ) -> str:
        """Search across all stored history chunks.

        Args:
            grep: Regex pattern to filter message content.
            tool_name: Filter to messages from a specific tool.

        Returns:
            Formatted search results.
        """
        from .constants import HISTORY_SEARCH_MAX_RESULTS, READ_OUTPUT_MAX_RETURN_CHARS

        prefix = f"{self.prefix}/history/"
        results: list[str] = []

        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    if len(results) >= HISTORY_SEARCH_MAX_RESULTS:
                        break

                    response = self.client.get_object(Bucket=self.bucket, Key=obj["Key"])
                    chunk_data = json.loads(response["Body"].read().decode("utf-8"))

                    for msg in chunk_data:
                        if len(results) >= HISTORY_SEARCH_MAX_RESULTS:
                            break

                        # Filter by tool_name
                        if tool_name and msg.get("name") != tool_name:
                            continue

                        content = msg.get("content", "")
                        role = msg.get("role", "unknown")

                        # Filter by grep
                        if grep:
                            try:
                                if not re.search(grep, content, re.IGNORECASE):
                                    continue
                            except re.error:
                                if grep not in content:
                                    continue

                        # Format result
                        name_suffix = f" ({msg['name']})" if msg.get("name") else ""
                        preview = content[:500] if len(content) > 500 else content
                        results.append(f"[{role}{name_suffix}]: {preview}")

        except self.client.exceptions.NoSuchKey:
            return "No history chunks found."
        except Exception as e:
            return f"Error searching history: {e}"

        if not results:
            return "No matching messages found in history."

        output = "\n---\n".join(results)
        if len(output) > READ_OUTPUT_MAX_RETURN_CHARS:
            output = output[:READ_OUTPUT_MAX_RETURN_CHARS] + "\n... [truncated]"

        return output

    # --- Cleanup ---

    async def cleanup(self) -> None:
        """Delete all stored context for this task."""
        prefix = f"{self.prefix}/"
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            keys_to_delete: list[dict[str, str]] = []

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys_to_delete.append({"Key": obj["Key"]})

            # Delete in batches of 1000 (S3 limit)
            for i in range(0, len(keys_to_delete), 1000):
                batch = keys_to_delete[i : i + 1000]
                self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": batch},
                )
        except Exception as e:
            logging.getLogger(__name__).debug("Context cleanup failed: %s", e)
