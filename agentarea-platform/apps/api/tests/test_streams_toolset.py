import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_api.tools import get_platform_tools
from agentarea_api.tools.streams_toolset import StreamsToolset


def test_the_streams_toolset_is_served():
    assert "agentarea/streams" in {t.metadata.namespace for t in get_platform_tools() if t.metadata}


async def test_create_forward_refuses_its_own_input(monkeypatch):
    from agentarea_streams.domain import ForwardLoopError

    service = AsyncMock()
    service.create_forward.side_effect = ForwardLoopError(
        "A forward may not write into its own input stream"
    )

    @asynccontextmanager
    async def ctx():
        yield (AsyncMock(), SimpleNamespace(user_id="u", workspace_id="w"), object(), None, None)

    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_context", ctx)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.require_permission", AsyncMock())
    stream = str(uuid4())
    result = json.loads(
        await StreamsToolset().create_forward.__wrapped__(
            StreamsToolset(), stream_id=stream, output_stream_ids=[stream]
        )
    )
    assert "own input" in result["error"]


async def test_create_forward_refuses_an_output_the_caller_may_not_edit(monkeypatch):
    from fastapi import HTTPException

    service = AsyncMock()

    @asynccontextmanager
    async def ctx():
        yield (AsyncMock(), SimpleNamespace(user_id="u", workspace_id="w"), object(), None, None)

    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_context", ctx)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.require_permission",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="forbidden")),
    )
    result = json.loads(
        await StreamsToolset().create_forward.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), output_stream_ids=[str(uuid4())]
        )
    )
    assert result == {"error": "forbidden"}
    service.create_forward.assert_not_called()


async def test_create_reports_a_taken_name_instead_of_failing(monkeypatch):
    from agentarea_streams.domain import StreamNameTakenError

    service = AsyncMock()
    service.create_stream.side_effect = StreamNameTakenError("orders")

    @asynccontextmanager
    async def ctx():
        yield (AsyncMock(), SimpleNamespace(user_id="u", workspace_id="w"), object(), None, None)

    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_context", ctx)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    result = json.loads(await StreamsToolset().create(name="orders"))
    assert result == {"error": "A stream named 'orders' already exists in this workspace"}


def test_the_streams_toolset_is_declared_where_its_writes_belong():
    (meta,) = [
        t.metadata
        for t in get_platform_tools()
        if t.metadata and t.metadata.namespace == "agentarea/streams"
    ]
    assert meta.plane == "build"


async def test_list_refuses_a_limit_past_the_rest_bound():
    result = json.loads(await StreamsToolset().list(limit=1001))
    assert "limit must be between 1 and 1000" in result["error"]


async def test_list_events_refuses_a_limit_past_the_rest_bound():
    result = json.loads(
        await StreamsToolset().list_events.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), limit=201
        )
    )
    assert "limit must be between 1 and 200" in result["error"]


def _write_ctx(session):
    @asynccontextmanager
    async def ctx():
        yield (session, SimpleNamespace(user_id="u", workspace_id="w"), object(), None, object())

    return ctx


async def test_create_webhook_source_refuses_a_verifier_without_its_secret(monkeypatch):
    service = AsyncMock()
    session = AsyncMock()
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_context", _write_ctx(session))
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset._secret_ports",
        lambda *_a: {
            "secret_manager": AsyncMock(),
            "secret_catalog": AsyncMock(),
            "webhook_service": AsyncMock(),
        },
    )
    result = json.loads(
        await StreamsToolset().create_webhook_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), webhook_type="sentry"
        )
    )
    assert "needs client_secret" in result["error"]
    service.add_webhook_source.assert_not_called()
    session.rollback.assert_awaited_once()


async def test_delete_webhook_source_refuses_a_source_a_live_trigger_owns(monkeypatch):
    from agentarea_streams.domain import SourceFedByTriggerError

    trigger_id = uuid4()
    service = AsyncMock()
    service.delete_source.side_effect = SourceFedByTriggerError("Source s", [trigger_id])
    released = AsyncMock()
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.release_webhook_source", released)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._secret_ports", lambda *_a: {})
    result = json.loads(
        await StreamsToolset().delete_webhook_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), source_id=str(uuid4())
        )
    )
    assert str(trigger_id) in result["error"]
    released.assert_not_called()


async def test_source_types_are_served_to_mcp_callers_too():
    types = json.loads(await StreamsToolset().list_source_types())
    assert {"sentry", "yookassa", "github"} <= {t["webhook_type"] for t in types}
