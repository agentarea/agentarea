"""Unit tests for the OpenFGA rebac client adapter."""

import json

import httpx
import pytest
from agentarea_common.rebac import (
    OpenFGAClient,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationQuery,
    RelationTuple,
    SubjectSet,
)


def _client(handler) -> OpenFGAClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return OpenFGAClient(
        api_url="http://openfga:8080",
        store_id="store-1",
        authorization_model_id="model-1",
        client=http,
    )


@pytest.mark.asyncio
async def test_check_posts_openfga_tuple_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"allowed": True})

    client = _client(handler)
    result = await client.check(
        namespace="Skill",
        object="copywriting",
        relation="use",
        subject_id="User:u1",
    )

    assert result.allowed is True
    assert seen["url"] == "http://openfga:8080/stores/store-1/check"
    assert seen["body"] == {
        "authorization_model_id": "model-1",
        "tuple_key": {
            "user": "User:u1",
            "relation": "use",
            "object": "Skill:copywriting",
        },
    }


@pytest.mark.asyncio
async def test_check_posts_contextual_tuples():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"allowed": True})

    client = _client(handler)
    await client.check(
        namespace="ToolResource",
        object="github_create_issue~args~abc",
        relation="can_call",
        subject_id="User:u1",
        contextual_tuples=[
            RelationTuple(
                namespace="ToolResource",
                object="github_create_issue~args~abc",
                relation="tool",
                subject_id="Tool:github_create_issue",
            )
        ],
    )

    assert seen["body"]["contextual_tuples"] == {
        "tuple_keys": [
            {
                "user": "Tool:github_create_issue",
                "relation": "tool",
                "object": "ToolResource:github_create_issue~args~abc",
            }
        ]
    }


@pytest.mark.asyncio
async def test_write_tuple_posts_writes_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.write_tuple(
        RelationTuple(
            namespace="SkillCollection",
            object="content-pack",
            relation="editors",
            subject_id="Agent:writer",
        )
    )

    assert seen["url"] == "http://openfga:8080/stores/store-1/write"
    assert seen["body"] == {
        "writes": {
            "tuple_keys": [
                {
                    "user": "Agent:writer",
                    "relation": "editors",
                    "object": "SkillCollection:content-pack",
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_write_tuple_serializes_subject_set_user():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.write_tuple(
        RelationTuple(
            namespace="Skill",
            object="copywriting",
            relation="viewers",
            subject_set=SubjectSet(namespace="Workspace", object="default", relation="members"),
        )
    )

    assert seen["body"]["writes"]["tuple_keys"][0]["user"] == "Workspace:default#members"


@pytest.mark.asyncio
async def test_query_tuples_roundtrips_and_filters_namespace():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "tuples": [
                    {
                        "key": {
                            "user": "Agent:writer",
                            "relation": "editors",
                            "object": "SkillCollection:content-pack",
                        }
                    },
                    {
                        "key": {
                            "user": "User:u1",
                            "relation": "owners",
                            "object": "Agent:a1",
                        }
                    },
                ],
                "continuation_token": "",
            },
        )

    client = _client(handler)
    tuples, token = await client.query_tuples(RelationQuery(namespace="SkillCollection"))

    assert token is None
    assert seen["body"] == {"page_size": 100}
    assert len(tuples) == 1
    assert tuples[0].namespace == "SkillCollection"
    assert tuples[0].object == "content-pack"
    assert tuples[0].subject_id == "Agent:writer"


@pytest.mark.asyncio
async def test_check_raises_on_error_status():
    client = _client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(OpenFGAError):
        await client.check(namespace="Skill", object="x", relation="use", subject_id="User:u1")


@pytest.mark.asyncio
async def test_unreachable_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(handler)
    with pytest.raises(OpenFGAUnavailableError):
        await client.write_tuple(
            RelationTuple(namespace="Skill", object="x", relation="use", subject_id="User:u1")
        )
