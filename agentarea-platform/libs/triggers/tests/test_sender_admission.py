"""Who gets through a Telegram bot to its agent, and how an account gets linked."""

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agentarea_common.identity import ExternalIdentityTakenError
from agentarea_triggers.channels.sender_admission import (
    Admitted,
    Refused,
    TelegramSender,
    TelegramSenderAdmission,
    is_telegram_trigger,
)

ALICE_TG = "111"
STRANGER_TG = "999"


class _Identities:
    def __init__(self, links: dict[str, str] | None = None, taken: bool = False):
        self.links = dict(links or {})
        self.taken = taken

    async def holder(self, provider: str, external_id: str) -> str | None:
        assert provider == "telegram"
        return self.links.get(external_id)

    async def link(self, *, user_id: str, provider: str, external_id: str, method: str):
        if self.taken:
            raise ExternalIdentityTakenError("taken")
        self.links[external_id] = user_id


class _Codes:
    def __init__(self, codes: dict[str, str] | None = None):
        self.codes = dict(codes or {})
        self.pending: dict[str, str] = {}

    async def redeem(self, code: str, *, provider: str, external_id: str) -> str | None:
        user_id = self.codes.pop(code, None)
        if user_id:
            self.pending[external_id] = user_id
        return user_id

    async def confirm(self, *, provider: str, external_id: str) -> str | None:
        return self.pending.pop(external_id, None)


class _Notices:
    def __init__(self):
        self.seen: set[str] = set()

    async def claim(self, key: str) -> bool:
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


class _Secrets:
    async def get_secret(self, name: str) -> str | None:
        return json.dumps({"bot_token": "tok"})


class _Bot:
    sent: list[tuple[str, str]]

    def __init__(self, sent: list[tuple[str, str]]):
        self.sent = sent

    async def username(self) -> str:
        return "acme_bot"

    async def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def _admission(*, may_run=True, identities=None, codes=None):
    sent: list[tuple[str, str]] = []
    calls: list[dict[str, Any]] = []

    async def _may_run(_session, **kwargs):
        calls.append(kwargs)
        return may_run

    admission = TelegramSenderAdmission(
        may_run=_may_run,
        link_codes=codes or _Codes(),
        notices=_Notices(),
        secret_reader=_Secrets(),
        app_url="https://app.example.com/",
        bot_client_factory=lambda _token: _Bot(sent),
        identities=lambda _session: identities or _Identities(),
    )
    return admission, sent, calls


def _trigger():
    return SimpleNamespace(id=uuid4(), workspace_id="w", agent_id=uuid4())


def _message(from_id: str, text: str = "hi", *, chat_type="private", is_bot=False):
    chat_id = from_id if chat_type == "private" else "-100"
    return {
        "user_id": int(from_id),
        "chat_id": int(chat_id),
        "chat_type": chat_type,
        "text": text,
        "raw_data": {"message": {"from": {"id": int(from_id), "is_bot": is_bot}}},
    }


async def test_a_linked_sender_who_may_run_the_agent_is_admitted_as_themselves():
    trigger = _trigger()
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: "alice"}))
    result = await admission.admit(object(), trigger, _message(ALICE_TG))
    assert result == Admitted("alice")
    assert calls == [{"user_id": "alice", "workspace_id": "w", "agent_id": trigger.agent_id}]
    assert sent == []


async def test_a_linked_sender_the_graph_refuses_is_told_once_and_kept_out():
    trigger = _trigger()
    admission, sent, _ = _admission(may_run=False, identities=_Identities({ALICE_TG: "alice"}))
    first = await admission.admit(object(), trigger, _message(ALICE_TG))
    second = await admission.admit(object(), trigger, _message(ALICE_TG))
    assert isinstance(first, Refused) and isinstance(second, Refused)
    assert len(sent) == 1
    assert "doesn't have access" in sent[0][1]


async def test_an_unlinked_sender_is_refused_and_pointed_at_the_link_page_once():
    admission, sent, calls = _admission()
    trigger = _trigger()
    assert isinstance(await admission.admit(object(), trigger, _message(STRANGER_TG)), Refused)
    assert isinstance(await admission.admit(object(), trigger, _message(STRANGER_TG)), Refused)
    assert calls == []
    assert len(sent) == 1
    assert "https://app.example.com/link/telegram?bot=acme_bot" in sent[0][1]


async def test_group_chats_and_bots_never_reach_the_agent():
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: "alice"}))
    trigger = _trigger()
    group = await admission.admit(object(), trigger, _message(ALICE_TG, chat_type="group"))
    bot = await admission.admit(object(), trigger, _message(ALICE_TG, is_bot=True))
    assert isinstance(group, Refused) and isinstance(bot, Refused)
    assert (sent, calls) == ([], [])


async def test_a_code_then_confirm_links_the_account_that_redeemed_it():
    identities = _Identities()
    codes = _Codes({"c0de": "alice"})
    admission, sent, _ = _admission(identities=identities, codes=codes)
    trigger = _trigger()

    redeemed = await admission.admit(object(), trigger, _message(STRANGER_TG, "/start link_c0de"))
    assert isinstance(redeemed, Refused)
    assert identities.links == {}
    assert "/confirm" in sent[-1][1]

    confirmed = await admission.admit(object(), trigger, _message(STRANGER_TG, "/confirm"))
    assert isinstance(confirmed, Refused)
    assert identities.links == {STRANGER_TG: "alice"}
    assert sent[-1][1].startswith("Done")


async def test_a_spent_or_unknown_code_links_nothing():
    identities = _Identities()
    admission, sent, _ = _admission(identities=identities, codes=_Codes())
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/start link_nope"))
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/confirm"))
    assert identities.links == {}
    assert "expired" in sent[0][1]
    assert sent[1][1] == "There is nothing to confirm."


async def test_confirming_from_another_account_than_the_one_that_redeemed_does_nothing():
    identities = _Identities()
    codes = _Codes({"c0de": "alice"})
    admission, _, _ = _admission(identities=identities, codes=codes)
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/start link_c0de"))
    await admission.admit(object(), trigger, _message(ALICE_TG, "/confirm"))
    assert identities.links == {}


async def test_an_account_linked_to_someone_else_is_not_moved():
    codes = _Codes({"c0de": "bob"})
    admission, sent, _ = _admission(identities=_Identities(taken=True), codes=codes)
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(ALICE_TG, "/start link_c0de"))
    await admission.admit(object(), trigger, _message(ALICE_TG, "/confirm"))
    assert "already linked to another" in sent[-1][1]


def test_a_polled_update_without_a_chat_type_is_private_only_in_the_senders_own_chat():
    private = TelegramSender.from_event({"user_id": 5, "chat_id": 5, "text": "x"})
    group = TelegramSender.from_event({"user_id": 5, "chat_id": -42, "text": "x"})
    assert private is not None and private.private
    assert group is not None and not group.private
    assert TelegramSender.from_event({"text": "no sender"}) is None


def test_telegram_triggers_are_recognised_by_webhook_type_or_poller():
    assert is_telegram_trigger(SimpleNamespace(webhook_type="telegram"))
    assert is_telegram_trigger(SimpleNamespace(data_extractor="telegram_polling"))
    assert not is_telegram_trigger(SimpleNamespace(webhook_type="github"))
