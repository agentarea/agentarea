"""Sender admission reads the sender off the event by its catalog entry's ``admission`` templates."""

import json
from pathlib import Path

from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_triggers.channels.sender_admission import TelegramSender

CATALOG = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"


def _admission():
    entries = json.loads(CATALOG.read_text())["source_types"]
    telegram = next(e for e in entries if e["slug"] == "telegram")
    return SourceTypeEntry.model_validate(telegram).admission


def test_a_private_message_names_its_sender_chat_and_text():
    body = {
        "update_id": 1,
        "message": {
            "chat": {"id": 555, "type": "private"},
            "from": {"id": 42, "is_bot": False},
            "text": " /start link_abc ",
        },
    }
    sender = TelegramSender.from_event(_admission(), body, {})
    assert sender == TelegramSender(
        external_id="42", chat_id="555", private=True, is_bot=False, text="/start link_abc"
    )


def test_a_group_message_and_a_bot_are_told_apart():
    body = {
        "message": {
            "chat": {"id": -100, "type": "group"},
            "from": {"id": 7, "is_bot": True},
            "text": "hi",
        }
    }
    sender = TelegramSender.from_event(_admission(), body, {})
    assert sender is not None
    assert sender.private is False
    assert sender.is_bot is True


def test_an_update_that_names_no_sender_has_none():
    assert TelegramSender.from_event(_admission(), {"update_id": 2, "poll": {}}, {}) is None
    assert TelegramSender.from_event(_admission(), None, {}) is None
