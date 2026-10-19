import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import get_platform_tools
from agentarea_api.tools.streams_toolset import StreamsToolset
from agentarea_streams.domain.source_types import SourceTypeEntry

CATALOG = Path(__file__).resolve().parents[4] / "data" / "catalog" / "source-types.json"


class _Catalog:
    """The shipped catalog, as the registry sync writes it to registry_items."""

    def __init__(self, _session):
        raw = json.loads(CATALOG.read_text())["source_types"]
        self.entries = {e["slug"]: SourceTypeEntry.model_validate(e) for e in raw}

    async def get(self, slug):
        return self.entries.get(slug)

    async def list_entries(self):
        return sorted(self.entries.values(), key=lambda e: e.name.lower())


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
    with pytest.raises(ToolError, match="own input"):
        await StreamsToolset().create_forward.__wrapped__(
            StreamsToolset(), stream_id=stream, output_stream_ids=[stream]
        )


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
    with pytest.raises(ToolError, match=r"^forbidden$"):
        await StreamsToolset().create_forward.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), output_stream_ids=[str(uuid4())]
        )
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
    with pytest.raises(
        ToolError, match=re.escape("A stream named 'orders' already exists in this workspace")
    ):
        await StreamsToolset().create(name="orders")


def test_the_streams_toolset_is_declared_where_its_writes_belong():
    (meta,) = [
        t.metadata
        for t in get_platform_tools()
        if t.metadata and t.metadata.namespace == "agentarea/streams"
    ]
    assert meta.plane == "build"


async def test_list_refuses_a_limit_past_the_rest_bound():
    with pytest.raises(ToolError, match="limit must be between 1 and 1000"):
        await StreamsToolset().list(limit=1001)


async def test_list_events_refuses_a_limit_past_the_rest_bound():
    with pytest.raises(ToolError, match="limit must be between 1 and 200"):
        await StreamsToolset().list_events.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), limit=201
        )


def _write_ctx(session):
    @asynccontextmanager
    async def ctx():
        yield (session, SimpleNamespace(user_id="u", workspace_id="w"), object(), None, object())

    return ctx


async def test_create_source_refuses_a_verifier_without_its_secret(monkeypatch):
    service = AsyncMock()
    session = AsyncMock()
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_context", _write_ctx(session))
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.api.v1._stream_sources.CatalogSourceTypeRepository", _Catalog)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset._secret_ports",
        lambda *_a: {"secret_manager": AsyncMock(), "secret_catalog": AsyncMock()},
    )
    with pytest.raises(ToolError, match="needs client_secret"):
        await StreamsToolset().create_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), source_type="sentry"
        )
    service.add_source.assert_not_called()
    session.rollback.assert_awaited_once()


async def test_create_source_refuses_a_type_the_catalog_lacks(monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.api.v1._stream_sources.CatalogSourceTypeRepository", _Catalog)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset._secret_ports",
        lambda *_a: {"secret_manager": AsyncMock(), "secret_catalog": AsyncMock()},
    )
    with pytest.raises(ToolError, match="Unknown source type 'gitlab'"):
        await StreamsToolset().create_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), source_type="gitlab"
        )
    service.add_source.assert_not_called()


async def test_delete_source_of_an_unknown_source_releases_nothing(monkeypatch):
    from agentarea_streams.domain import StreamSourceNotFoundError

    source_id = uuid4()
    service = AsyncMock()
    service.delete_source.side_effect = StreamSourceNotFoundError(source_id)
    released = AsyncMock()
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.release_source", released)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._secret_ports", lambda *_a: {})
    with pytest.raises(ToolError, match=str(source_id)):
        await StreamsToolset().delete_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), source_id=str(source_id)
        )
    released.assert_not_called()


async def test_delete_source_releases_its_credentials(monkeypatch):
    source = SimpleNamespace(id=uuid4())
    service = AsyncMock()
    service.delete_source.return_value = source
    released = AsyncMock()
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.release_source", released)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._secret_ports", lambda *_a: {})
    result = json.loads(
        await StreamsToolset().delete_source.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), source_id=str(source.id)
        )
    )
    assert result == {"deleted": True}
    released.assert_awaited_once_with(source)


async def test_delete_refuses_a_stream_a_forward_writes_into(monkeypatch):
    from agentarea_streams.domain import StreamInUseError

    stream, forward, source = uuid4(), uuid4(), uuid4()
    service = AsyncMock()
    service.ensure_deletable.side_effect = StreamInUseError(stream, [], [(forward, source)])
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset._secret_ports",
        lambda *_a: {"secret_manager": AsyncMock(), "secret_catalog": AsyncMock()},
    )
    with pytest.raises(ToolError, match=str(forward)):
        await StreamsToolset().delete.__wrapped__(StreamsToolset(), stream_id=str(stream))
    service.delete_stream.assert_not_called()


async def test_delete_forward_checks_every_output_then_removes_it(monkeypatch):
    stream, output, forward = uuid4(), uuid4(), uuid4()
    service = AsyncMock()
    service.existing_outputs.return_value = [output]
    allowed = AsyncMock()
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    monkeypatch.setattr("agentarea_api.tools.streams_toolset.require_permission", allowed)
    result = json.loads(
        await StreamsToolset().delete_forward.__wrapped__(
            StreamsToolset(), stream_id=str(stream), subscription_id=str(forward)
        )
    )
    assert result == {"deleted": True}
    allowed.assert_awaited_once_with("edit", "stream", str(output), "u")
    service.delete_forward.assert_awaited_once_with(stream, forward)


async def test_delete_forward_refuses_a_triggers_subscription(monkeypatch):
    from agentarea_streams.domain import NotAForwardError

    subscription, trigger = uuid4(), uuid4()
    service = AsyncMock()
    service.get_forward.side_effect = NotAForwardError(subscription, trigger)
    monkeypatch.setattr(
        "agentarea_api.tools.streams_toolset.platform_context", _write_ctx(AsyncMock())
    )
    monkeypatch.setattr("agentarea_api.tools.streams_toolset._service", lambda _f: service)
    with pytest.raises(ToolError, match=str(trigger)):
        await StreamsToolset().delete_forward.__wrapped__(
            StreamsToolset(), stream_id=str(uuid4()), subscription_id=str(subscription)
        )
    service.delete_forward.assert_not_called()


async def test_source_types_are_served_to_mcp_callers_too(monkeypatch):
    @asynccontextmanager
    async def ctx():
        yield (AsyncMock(), SimpleNamespace(user_id="u", workspace_id="w"), AsyncMock(), None, None)

    monkeypatch.setattr("agentarea_api.tools.streams_toolset.platform_read_context", ctx)
    monkeypatch.setattr("agentarea_api.api.v1.streams.CatalogSourceTypeRepository", _Catalog)
    types = json.loads(await StreamsToolset().list_source_types())
    assert {"sentry", "stripe", "github", "generic_webhook"} <= {t["slug"] for t in types}
