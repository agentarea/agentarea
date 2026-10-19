"""A stream firing's delivery address and session, from the event and its catalog entry."""

from uuid import uuid4

import pytest
from agentarea_common.reserved_task_parameters import reject_reserved_parameters
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_triggers.delivery_address import (
    FiringDelivery,
    build_delivery_address,
    event_body,
    task_session,
)
from agentarea_triggers.domain.models import TriggerSession

SOURCE_ID = uuid4()
CREDENTIAL_KEY = uuid4()
TRIGGER_ID = uuid4()


def _entry(**overrides) -> SourceTypeEntry:
    spec = {
        "slug": "chat",
        "name": "Chat",
        "delivery": "both",
        "event": {"kind": "message", "session_key": "{body:message.chat.id}"},
        "reply": {
            "sender": "telegram_live",
            "target": {
                "chat_id": "{body:message.chat.id}",
                "message_id": "{body:message.message_id}",
            },
            "presentation": "concise",
            "markup": "telegram",
        },
    }
    spec.update(overrides)
    return SourceTypeEntry.model_validate(spec)


def _address(entry, body, session_key="s:1"):
    return build_delivery_address(
        entry,
        source_id=SOURCE_ID,
        credential_key=CREDENTIAL_KEY,
        trigger_id=TRIGGER_ID,
        session_key=session_key,
        body=body,
        headers={},
    )


def test_the_address_names_the_sender_target_and_credentials():
    address = _address(_entry(), {"message": {"chat": {"id": 42}, "message_id": 7}})
    assert address == {
        "type": "chat",
        "sender": "telegram_live",
        "source_id": str(SOURCE_ID),
        "credential_type": "chat",
        "credential_key": str(CREDENTIAL_KEY),
        "trigger_id": str(TRIGGER_ID),
        "session_key": "s:1",
        "target": {"chat_id": 42, "message_id": 7},
        "presentation": "concise",
    }


def test_a_target_field_the_event_lacks_is_left_out():
    address = _address(_entry(), {"message": {"chat": {"id": 42}}})
    assert address is not None
    assert address["target"] == {"chat_id": 42}


def test_an_event_with_nothing_to_reply_to_gets_no_address():
    assert _address(_entry(), {"callback": {}}) is None


def test_an_entry_without_a_reply_gets_no_address():
    assert _address(_entry(reply=None), {"message": {"chat": {"id": 42}}}) is None


def test_a_session_continues_by_default_when_the_entry_names_sessions():
    session = task_session(None, _entry(), "s:1")
    assert session == {"key": "s:1", "continue": True, "idle_timeout_seconds": 1800}


def test_the_trigger_setting_wins_over_the_entry_default():
    session = task_session(
        TriggerSession.model_validate({"continue": False, "idle_timeout": "5m"}), _entry(), "s:1"
    )
    assert session == {"key": "s:1", "continue": False, "idle_timeout_seconds": 300}


def test_an_entry_without_sessions_does_not_continue_by_default():
    entry = _entry(event={"kind": "push"})
    assert task_session(None, entry, "s:1")["continue"] is False


def test_an_event_without_a_session_key_has_no_session():
    assert task_session(TriggerSession(continue_=True), _entry(), None) is None


def test_a_firing_stamps_what_it_has():
    parameters = FiringDelivery(
        source_type="chat",
        stream_event_id="e-1",
        address={"type": "chat"},
        session={"key": "s:1", "continue": True, "idle_timeout_seconds": 60},
    ).stamp({"trigger_id": "t"})
    assert parameters == {
        "trigger_id": "t",
        "source_type": "chat",
        "stream_event_id": "e-1",
        "delivery_address": {"type": "chat"},
        "session": {"key": "s:1", "continue": True, "idle_timeout_seconds": 60},
    }
    assert FiringDelivery().stamp({}) == {}


@pytest.mark.parametrize("key", ["delivery_address", "session"])
def test_callers_cannot_set_where_a_task_replies_or_its_session(key):
    with pytest.raises(ValueError, match=key):
        reject_reserved_parameters({key: {}})


async def test_an_offloaded_body_is_read_back_for_the_address():
    reads: list[tuple[str, str]] = []

    async def read(workspace_id: str, path: str) -> bytes:
        reads.append((workspace_id, path))
        return b'{"message": {"chat": {"id": 42}, "message_id": 7}}'

    data = {"headers": {}, "body": None, "body_ref": "events/s/e/body.json"}
    assert await event_body(data, "ws-1", read) == {
        "message": {"chat": {"id": 42}, "message_id": 7}
    }
    assert reads == [("ws-1", "events/s/e/body.json")]


async def test_an_inline_body_is_not_read_from_files():
    async def read(workspace_id: str, path: str) -> bytes:
        raise AssertionError("read")

    assert await event_body({"body": {"a": 1}, "body_ref": None}, "ws-1", read) == {"a": 1}


async def test_a_forwarded_copy_neither_replies_nor_joins_a_session():
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from agentarea_streams.domain import StreamEvent
    from agentarea_triggers.delivery_address import firing_delivery

    copy = StreamEvent(
        type="message_received",
        source="/sources/x",
        data={"body": {"from": "a@b.c"}},
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        event_key="k",
        received_at=datetime.now(UTC),
        source_id=SOURCE_ID,
        session_key="s:1",
        depth=1,
    )
    session = AsyncMock()
    delivery = await firing_delivery(
        session, copy, trigger_id=TRIGGER_ID, session_setting=None, body=copy.data["body"]
    )
    assert delivery == FiringDelivery(stream_event_id=str(copy.id))
    session.get.assert_not_awaited()
