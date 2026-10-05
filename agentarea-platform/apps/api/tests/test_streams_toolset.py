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
