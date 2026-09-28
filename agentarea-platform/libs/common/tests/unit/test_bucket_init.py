"""The compose bucket-init step creates the buckets and their browser CORS rule.

Browsers PUT presigned uploads straight to the object store, so a bucket with
no CORS rule makes every browser upload fail its preflight.
"""

from __future__ import annotations

import pytest
from agentarea_common.artifacts.bucket_init import init_buckets, parse_list
from botocore.exceptions import ClientError


class FakeS3:
    def __init__(self, existing: set[str] = frozenset()) -> None:
        self.buckets = set(existing)
        self.cors: dict[str, dict] = {}

    def create_bucket(self, *, Bucket):  # noqa: N803
        if Bucket in self.buckets:
            raise ClientError({"Error": {"Code": "BucketAlreadyOwnedByYou"}}, "CreateBucket")
        self.buckets.add(Bucket)

    def put_bucket_cors(self, *, Bucket, CORSConfiguration):  # noqa: N803
        self.cors[Bucket] = CORSConfiguration


def test_buckets_are_created_and_existing_ones_kept() -> None:
    s3 = FakeS3(existing={"documents"})

    init_buckets(s3, ["documents", "artifacts"], [])

    assert s3.buckets == {"documents", "artifacts"}
    assert s3.cors == {}


def test_every_bucket_gets_the_origin_allowlist() -> None:
    s3 = FakeS3()

    init_buckets(s3, ["artifacts"], ["http://localhost:3000"])

    (rule,) = s3.cors["artifacts"]["CORSRules"]
    assert rule["AllowedOrigins"] == ["http://localhost:3000"]
    assert set(rule["AllowedMethods"]) == {"GET", "PUT", "HEAD"}


def test_a_real_create_failure_is_raised() -> None:
    class Broken(FakeS3):
        def create_bucket(self, *, Bucket):  # noqa: N803
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "CreateBucket")

    with pytest.raises(ClientError):
        init_buckets(Broken(), ["artifacts"], [])


def test_wildcard_origin_is_refused() -> None:
    with pytest.raises(ValueError, match="explicit"):
        init_buckets(FakeS3(), ["artifacts"], ["*"])


def test_lists_are_comma_separated_and_trimmed() -> None:
    assert parse_list(" a, b ,,c ") == ["a", "b", "c"]
    assert parse_list("") == []
