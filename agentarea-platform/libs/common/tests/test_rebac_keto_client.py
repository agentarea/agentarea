"""Unit tests for the Keto rebac client and tuple models (mocked transport)."""

import httpx
import pytest
from agentarea_common.rebac import (
    KetoClient,
    KetoError,
    KetoUnavailableError,
    RelationQuery,
    RelationTuple,
    SubjectSet,
)


def _client(handler) -> KetoClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return KetoClient(
        read_url="http://keto:4466",
        write_url="http://keto:4467",
        client=http,
    )


# -- models ---------------------------------------------------------------


def test_relation_tuple_requires_exactly_one_subject():
    with pytest.raises(ValueError, match="exactly one"):
        RelationTuple(namespace="Skill", object="x", relation="use")
    with pytest.raises(ValueError, match="exactly one"):
        RelationTuple(
            namespace="Skill",
            object="x",
            relation="use",
            subject_id="Agent:a",
            subject_set=SubjectSet(namespace="Workspace", object="w", relation="members"),
        )


def test_relation_tuple_to_keto_subject_id():
    t = RelationTuple(namespace="SkillCollection", object="content-pack", relation="editors", subject_id="Agent:writer-1")
    assert t.to_keto() == {
        "namespace": "SkillCollection",
        "object": "content-pack",
        "relation": "editors",
        "subject_id": "Agent:writer-1",
    }
    assert str(t) == "SkillCollection:content-pack#editors@Agent:writer-1"


def test_relation_tuple_to_keto_subject_set():
    t = RelationTuple(
        namespace="Skill",
        object="copywriting",
        relation="viewers",
        subject_set=SubjectSet(namespace="Workspace", object="default", relation="members"),
    )
    assert t.to_keto()["subject_set"] == {
        "namespace": "Workspace",
        "object": "default",
        "relation": "members",
    }
    assert str(t) == "Skill:copywriting#viewers@Workspace:default#members"


def test_relation_tuple_roundtrip_from_keto():
    data = {
        "namespace": "Skill",
        "object": "copywriting",
        "relation": "viewers",
        "subject_set": {"namespace": "Workspace", "object": "default", "relation": "members"},
    }
    t = RelationTuple.from_keto(data)
    assert t.subject_set is not None
    assert t.subject_set.object == "default"


# -- write API ------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tuple_puts_to_write_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(201, json={})

    client = _client(handler)
    await client.write_tuple(
        RelationTuple(namespace="SkillCollection", object="cp", relation="editors", subject_id="Agent:w")
    )
    assert seen["method"] == "PUT"
    assert seen["url"] == "http://keto:4467/admin/relation-tuples"


@pytest.mark.asyncio
async def test_write_tuple_raises_on_error_status():
    client = _client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(KetoError):
        await client.write_tuple(
            RelationTuple(namespace="Skill", object="x", relation="use", subject_id="Agent:a")
        )


@pytest.mark.asyncio
async def test_delete_tuple_tolerates_404():
    client = _client(lambda r: httpx.Response(404))
    # Should not raise.
    await client.delete_tuple(
        RelationTuple(namespace="Skill", object="x", relation="use", subject_id="Agent:a")
    )


@pytest.mark.asyncio
async def test_write_tuple_unreachable_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(handler)
    with pytest.raises(KetoUnavailableError):
        await client.write_tuple(
            RelationTuple(namespace="Skill", object="x", relation="use", subject_id="Agent:a")
        )


# -- read API -------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tuples_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["namespace"] == "Skill"
        return httpx.Response(
            200,
            json={
                "relation_tuples": [
                    {"namespace": "Skill", "object": "a", "relation": "use", "subject_id": "Agent:x"}
                ],
                "next_page_token": "",
            },
        )

    client = _client(handler)
    tuples, token = await client.query_tuples(RelationQuery(namespace="Skill"))
    assert len(tuples) == 1
    assert tuples[0].subject_id == "Agent:x"
    assert token is None


@pytest.mark.asyncio
async def test_query_all_tuples_follows_pagination():
    pages = [
        {"relation_tuples": [{"namespace": "S", "object": "1", "relation": "use", "subject_id": "Agent:a"}], "next_page_token": "p2"},
        {"relation_tuples": [{"namespace": "S", "object": "2", "relation": "use", "subject_id": "Agent:b"}], "next_page_token": ""},
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    client = _client(handler)
    tuples = await client.query_all_tuples(RelationQuery(namespace="S"))
    assert [t.object for t in tuples] == ["1", "2"]
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_check_allowed_true():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/relation-tuples/check" in str(request.url)
        return httpx.Response(200, json={"allowed": True})

    client = _client(handler)
    result = await client.check("Skill", "copywriting", "use", "Agent:writer-1")
    assert result.allowed is True


@pytest.mark.asyncio
async def test_check_denied_returns_false_on_403():
    client = _client(lambda r: httpx.Response(403, json={"allowed": False}))
    result = await client.check("Skill", "x", "use", "Agent:none")
    assert result.allowed is False


@pytest.mark.asyncio
async def test_expand_parses_tree():
    tree = {
        "type": "union",
        "children": [
            {"type": "leaf", "subject_id": "Agent:writer-1", "children": []},
        ],
    }
    client = _client(lambda r: httpx.Response(200, json=tree))
    node = await client.expand("Skill", "copywriting", "use")
    assert node is not None
    assert node.type == "union"
    assert node.children[0].subject_id == "Agent:writer-1"


@pytest.mark.asyncio
async def test_expand_returns_none_on_404():
    client = _client(lambda r: httpx.Response(404))
    assert await client.expand("Skill", "missing", "use") is None
