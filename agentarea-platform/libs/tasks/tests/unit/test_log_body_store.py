"""Large log bodies live under the task's stored-context prefix, so they go with the task."""

from io import BytesIO
from uuid import uuid4

from agentarea_tasks.infrastructure.log_body_store import S3LogBodyStore


class _Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:  # noqa: N803
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


async def test_a_body_is_stored_under_the_task_prefix_and_read_back():
    client = _Client()
    store = S3LogBodyStore(client, "bucket")
    task_id, event_id = uuid4(), uuid4()

    ref = await store.put("ws-1", task_id, event_id, "großer Inhalt")

    assert ref == f"tasks/ws-1/{task_id}/log/{event_id}.txt"
    assert await store.get(ref) == "großer Inhalt"
    assert list(client.objects) == [("bucket", ref)]


async def test_a_rows_tool_calls_are_a_part_of_their_own_beside_its_content():
    client = _Client()
    store = S3LogBodyStore(client, "bucket")
    task_id, event_id = uuid4(), uuid4()

    content = await store.put("ws-1", task_id, event_id, "text")
    calls = await store.put("ws-1", task_id, event_id, "[]", part="tool_calls")

    assert calls == f"tasks/ws-1/{task_id}/log/{event_id}.tool_calls.txt"
    assert content != calls
    assert (await store.get(content), await store.get(calls)) == ("text", "[]")
