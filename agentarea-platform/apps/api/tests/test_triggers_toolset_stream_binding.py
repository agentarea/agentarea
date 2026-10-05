"""The MCP trigger summary reads its stream from the subscription, as the REST response does."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.tools import triggers_toolset
from agentarea_api.tools.triggers_toolset import TriggersToolset
from agentarea_streams.domain.models import TriggerBinding
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import Trigger


def _stream_trigger(**kw) -> Trigger:
    return Trigger(
        name="on push",
        agent_id=uuid4(),
        trigger_type=TriggerType.STREAM,
        created_by="u",
        workspace_id="w",
        **kw,
    )


@pytest.fixture
def harness(monkeypatch):
    service = AsyncMock()

    @asynccontextmanager
    async def ctx():
        yield (AsyncMock(), SimpleNamespace(user_id="u", workspace_id="w"), object(), None, None)

    monkeypatch.setattr(triggers_toolset, "platform_context", ctx)
    monkeypatch.setattr(triggers_toolset, "platform_read_context", ctx)
    monkeypatch.setattr(triggers_toolset, "_build_trigger_service", AsyncMock(return_value=service))
    monkeypatch.setattr(
        triggers_toolset, "public_webhook_url", lambda wid: f"https://api.example/webhooks/{wid}"
    )
    return service


async def test_create_stream_then_get_and_list_report_the_bound_stream(harness):
    trigger = _stream_trigger()
    stream_id = uuid4()
    binding = TriggerBinding(
        stream_id=stream_id, event_filter={"kinds": ["push"]}, webhook_id=None, last_event_at=None
    )
    harness.create_trigger_from_payload.return_value = trigger
    harness.get_trigger.return_value = trigger
    harness.list_triggers.return_value = [trigger]
    harness.stream_service.trigger_bindings.return_value = {trigger.id: binding}
    tools = TriggersToolset()

    created = json.loads(
        await tools.create_stream(name="on push", agent_id=str(uuid4()), stream_id=str(stream_id))
    )
    got = json.loads(await tools.get(trigger_id=str(trigger.id)))
    (listed,) = json.loads(await tools.list())

    for summary in (created, got, listed):
        assert summary["stream_id"] == str(stream_id)
        assert summary["event_filter"] == {"kinds": ["push"]}
        assert summary["status"] == "active"
        assert summary["needs_new_owner"] is False


async def test_list_resolves_every_binding_in_one_call(harness):
    triggers = [_stream_trigger(), _stream_trigger()]
    harness.list_triggers.return_value = triggers
    harness.stream_service.trigger_bindings.return_value = {}

    summaries = json.loads(await TriggersToolset().list())

    harness.stream_service.trigger_bindings.assert_awaited_once_with([t.id for t in triggers])
    assert [s["stream_id"] for s in summaries] == [None, None]


async def test_a_webhook_trigger_reports_its_public_url_and_a_lost_owner(harness):
    trigger = _stream_trigger(
        is_active=False, needs_new_owner_at=datetime(2026, 10, 6, tzinfo=UTC).replace(tzinfo=None)
    )
    harness.get_trigger.return_value = trigger
    harness.stream_service.trigger_bindings.return_value = {
        trigger.id: TriggerBinding(
            stream_id=uuid4(), event_filter={}, webhook_id="abc123", last_event_at=None
        )
    }

    summary = json.loads(await TriggersToolset().get(trigger_id=str(trigger.id)))

    assert summary["webhook_url"] == "https://api.example/webhooks/abc123"
    assert summary["status"] == "needs_owner"
    assert summary["needs_new_owner"] is True
