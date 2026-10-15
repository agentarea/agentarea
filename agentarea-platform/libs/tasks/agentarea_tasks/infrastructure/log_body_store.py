"""Log bodies too large for a row, in the deployment's object store.

They are kept under the task's stored-context prefix (``tasks/{workspace}/{task}``),
the one the context store's cleanup deletes, so a task's bodies go with it.
"""

import asyncio
from typing import Any
from uuid import UUID


class S3LogBodyStore:
    """Bodies as UTF-8 text objects, one per log row, keyed by the row's event id."""

    def __init__(self, client: Any, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls) -> "S3LogBodyStore":
        from agentarea_common.config.aws import get_aws_settings, get_s3_client

        return cls(get_s3_client(), get_aws_settings().BUCKET)

    async def put(self, workspace_id: str, task_id: UUID, event_id: UUID, body: str) -> str:
        ref = f"tasks/{workspace_id}/{task_id}/log/{event_id}.txt"
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=ref,
            Body=body.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        return ref

    async def get(self, ref: str) -> str:
        response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=ref)
        return response["Body"].read().decode("utf-8")
