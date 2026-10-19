"""An in-memory S3 client with the calls SkillStorageService makes."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
from botocore.exceptions import ClientError


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []

    def put_object(self, *, Bucket: str, Key: str, Body: Any, ContentType: str = "") -> None:
        self.objects[Key] = Body.encode("utf-8") if isinstance(Body, str) else bytes(Body)
        self.puts.append(Key)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        self.gets.append(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, _name: str) -> FakeS3:
        return self

    def paginate(self, *, Bucket: str, Prefix: str) -> Iterator[dict[str, Any]]:
        yield {
            "Contents": [
                {"Key": key, "Size": len(data)}
                for key, data in sorted(self.objects.items())
                if key.startswith(Prefix)
            ]
        }

    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int = 1000) -> dict[str, Any]:
        keys = [key for key in sorted(self.objects) if key.startswith(Prefix)][:MaxKeys]
        return {"KeyCount": len(keys), "Contents": [{"Key": key} for key in keys]}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> None:
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)

    def generate_presigned_url(self, _op: str, Params: dict[str, Any], ExpiresIn: int) -> str:
        return f"https://s3.test/{Params['Key']}"

    def under(self, prefix: str) -> dict[str, bytes]:
        return {k[len(prefix) :]: v for k, v in self.objects.items() if k.startswith(prefix)}


def fake_storage(s3: FakeS3 | None = None) -> tuple[SkillStorageService, FakeS3]:
    s3 = s3 or FakeS3()
    storage = SkillStorageService()
    settings = MagicMock()
    settings.ARTIFACTS_BUCKET = "test-bucket"
    storage._client = s3
    storage._settings = settings
    return storage, s3
