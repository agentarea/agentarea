import io

from agentarea_streams.infrastructure.event_archive import S3EventArchive


class _Client:
    def __init__(self):
        self.uploads: list[dict] = []

    def upload_fileobj(self, body, bucket, key, ExtraArgs):  # noqa: N803
        self.uploads.append(
            {"body": body.read(), "bucket": bucket, "key": key, "extra": ExtraArgs}
        )


async def test_an_archived_day_is_one_gzip_object_in_the_bucket():
    client = _Client()

    await S3EventArchive(client, "events-bucket").put("event-archive/w/2026-09-01.jsonl.gz", io.BytesIO(b"gz"))

    assert client.uploads == [
        {
            "body": b"gz",
            "bucket": "events-bucket",
            "key": "event-archive/w/2026-09-01.jsonl.gz",
            "extra": {"ContentType": "application/gzip"},
        }
    ]
