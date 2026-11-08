"""What a task on a client's runner keeps beside its workflow (ADR-0051).

A task of an agent on a client runs as an ordinary task workflow; each turn is
an activity the client's runner serves. Kept here: the files its CLI made, the
CLI's session id in the task's metadata, and who a turn acts for.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from agentarea_common.broker.interface import BrokerClient
from agentarea_execution.models import RunnerActor

# Task parameter: the model a runner's task runs on, by the CLI's own name for it.
HARNESS_MODEL_PARAMETER = "model"
# Task metadata: the CLI's own session of the task, which every later turn resumes.
RUNNER_SESSION_METADATA_KEY = "runner_session_id"


def actor_of_task(source_identity: str | None, agent_id: UUID) -> RunnerActor:
    """Who a task's first turn acts for: the person who started it, else its agent (ADR-0046)."""
    if source_identity and source_identity.startswith("user:"):
        return RunnerActor(type="user", id=source_identity.removeprefix("user:"))
    return RunnerActor(type="agent", id=str(agent_id))


class HarnessFiles:
    """The files a runner's task CLI made, copied up by its runner after each turn.

    Such a task has no platform sandbox; these stand in for its files, under
    ``harness-files/<workspace>/<task>/``, so the task's file links resolve.
    """

    def __init__(self, client: Any, bucket: str, workspace_id: str, task_id: UUID):
        self._client = client
        self._bucket = bucket
        self._prefix = f"harness-files/{workspace_id}/{task_id}/"

    @classmethod
    def from_settings(cls, workspace_id: str, task_id: UUID) -> HarnessFiles:
        from agentarea_common.config.aws import get_aws_settings, get_s3_client

        return cls(get_s3_client(), get_aws_settings().BUCKET, workspace_id, task_id)

    async def put(self, path: str, body: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=self._prefix + path,
            Body=body,
            ContentType=content_type,
        )

    async def list(self, prefix: str = "") -> list[str]:
        paths: list[str] = []
        token: str | None = None
        while True:
            page = await asyncio.to_thread(
                self._client.list_objects_v2,
                Bucket=self._bucket,
                Prefix=self._prefix + prefix,
                **({"ContinuationToken": token} if token else {}),
            )
            paths.extend(obj["Key"][len(self._prefix) :] for obj in page.get("Contents", []))
            if not page.get("IsTruncated"):
                return sorted(paths)
            token = page["NextContinuationToken"]

    async def get(self, path: str) -> tuple[bytes, str] | None:
        try:
            obj = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=self._prefix + path
            )
        except self._client.exceptions.NoSuchKey:
            return None
        body = await asyncio.to_thread(obj["Body"].read)
        return body, obj.get("ContentType") or "application/octet-stream"


_broker: BrokerClient | None = None


def harness_broker() -> BrokerClient:
    """The process's broker client for runner turns' live events and runner signals."""
    global _broker
    if _broker is None:
        from agentarea_common.broker.redis_streams import RedisStreamsBroker
        from agentarea_common.config import RedisSettings, get_settings

        settings = get_settings()
        if not isinstance(settings.broker, RedisSettings):
            raise RuntimeError(
                "runner turns publish to the Redis broker; set AGENTAREA_BROKER=redis "
                + f"(current: {settings.broker.BROKER})"
            )
        _broker = RedisStreamsBroker(
            settings.broker.REDIS_URL, namespace=settings.streams.NAMESPACE
        )
    return _broker
