"""Who gets through a Telegram bot to its agent, and how an account gets linked."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from agentarea_common.identity import ExternalIdentityTakenError
from agentarea_streams.application import forward
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.domain import StreamEvent
from agentarea_streams.domain.source_types import (
    Admission,
    Senders,
    SendersRecord,
    SourceTypeEntry,
    senders_to_store,
)
from agentarea_triggers.channels import sender_admission
from agentarea_triggers.channels.sender_admission import (
    Admitted,
    EventAdmission,
    Refused,
    TelegramSenderAdmission,
    event_admission,
)

ALICE_TG = "111"
STRANGER_TG = "999"

TELEGRAM_ADMISSION = Admission(
    identity="telegram",
    external_id="{body:message.from.id}",
    chat="{body:message.chat.id}",
    text="{body:message.text}",
    private="{body:message.chat.type}",
    is_bot="{body:message.from.is_bot}",
)
DOOR = EventAdmission(admission=TELEGRAM_ADMISSION, credentials_secret="channel_cred:telegram:x")


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
    update = {
        "message": {
            "from": {"id": int(from_id), "is_bot": is_bot},
            "chat": {"id": int(chat_id), "type": chat_type},
            "text": text,
        }
    }
    return StreamEvent(
        type="message",
        source="telegram",
        data={"body": update, "headers": {}},
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        event_key=f"{from_id}:{text}",
        received_at=datetime.now(UTC),
        source_id=uuid4(),
        source_type="telegram",
    )


async def test_a_linked_sender_who_may_run_the_agent_is_admitted_as_themselves():
    trigger = _trigger()
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: "alice"}))
    result = await admission.admit(object(), trigger, _message(ALICE_TG), DOOR)
    assert result == Admitted("alice")
    assert calls == [{"user_id": "alice", "workspace_id": "w", "agent_id": trigger.agent_id}]
    assert sent == []


async def test_a_linked_sender_the_graph_refuses_is_told_once_and_kept_out():
    trigger = _trigger()
    admission, sent, _ = _admission(may_run=False, identities=_Identities({ALICE_TG: "alice"}))
    first = await admission.admit(object(), trigger, _message(ALICE_TG), DOOR)
    second = await admission.admit(object(), trigger, _message(ALICE_TG), DOOR)
    assert isinstance(first, Refused) and isinstance(second, Refused)
    assert len(sent) == 1
    assert "doesn't have access" in sent[0][1]


async def test_an_unlinked_sender_is_refused_and_pointed_at_the_link_page_once():
    admission, sent, calls = _admission()
    trigger = _trigger()
    assert isinstance(
        await admission.admit(object(), trigger, _message(STRANGER_TG), DOOR), Refused
    )
    assert isinstance(
        await admission.admit(object(), trigger, _message(STRANGER_TG), DOOR), Refused
    )
    assert calls == []
    assert len(sent) == 1
    assert "https://app.example.com/link/telegram?bot=acme_bot" in sent[0][1]


async def test_group_chats_and_bots_never_reach_the_agent():
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: "alice"}))
    trigger = _trigger()
    group = await admission.admit(object(), trigger, _message(ALICE_TG, chat_type="group"), DOOR)
    bot = await admission.admit(object(), trigger, _message(ALICE_TG, is_bot=True), DOOR)
    assert isinstance(group, Refused) and isinstance(bot, Refused)
    assert (sent, calls) == ([], [])


async def test_a_code_then_confirm_links_the_account_that_redeemed_it():
    identities = _Identities()
    codes = _Codes({"c0de": "alice"})
    admission, sent, _ = _admission(identities=identities, codes=codes)
    trigger = _trigger()

    redeemed = await admission.admit(
        object(), trigger, _message(STRANGER_TG, "/start link_c0de"), DOOR
    )
    assert isinstance(redeemed, Refused)
    assert identities.links == {}
    assert "/confirm" in sent[-1][1]

    confirmed = await admission.admit(object(), trigger, _message(STRANGER_TG, "/confirm"), DOOR)
    assert isinstance(confirmed, Refused)
    assert identities.links == {STRANGER_TG: "alice"}
    assert sent[-1][1].startswith("Done")


async def test_a_spent_or_unknown_code_links_nothing():
    identities = _Identities()
    admission, sent, _ = _admission(identities=identities, codes=_Codes())
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/start link_nope"), DOOR)
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/confirm"), DOOR)
    assert identities.links == {}
    assert "expired" in sent[0][1]
    assert sent[1][1] == "There is nothing to confirm."


async def test_confirming_from_another_account_than_the_one_that_redeemed_does_nothing():
    identities = _Identities()
    codes = _Codes({"c0de": "alice"})
    admission, _, _ = _admission(identities=identities, codes=codes)
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(STRANGER_TG, "/start link_c0de"), DOOR)
    await admission.admit(object(), trigger, _message(ALICE_TG, "/confirm"), DOOR)
    assert identities.links == {}


async def test_an_account_linked_to_someone_else_is_not_moved():
    codes = _Codes({"c0de": "bob"})
    admission, sent, _ = _admission(identities=_Identities(taken=True), codes=codes)
    trigger = _trigger()
    await admission.admit(object(), trigger, _message(ALICE_TG, "/start link_c0de"), DOOR)
    await admission.admit(object(), trigger, _message(ALICE_TG, "/confirm"), DOOR)
    assert "already linked to another" in sent[-1][1]


OWNER = "owner-user"


def _door(senders: Senders) -> EventAdmission:
    return EventAdmission(
        admission=TELEGRAM_ADMISSION,
        credentials_secret="channel_cred:telegram:x",
        senders=senders,
        owner_id=OWNER,
    )


ONLY_OWNER = _door(Senders(allow="owner"))
LISTED = _door(Senders(allow="ids", ids=[ALICE_TG]))


async def test_an_owner_only_bot_admits_its_owner_once_linked():
    trigger = _trigger()
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: OWNER}))
    result = await admission.admit(object(), trigger, _message(ALICE_TG), ONLY_OWNER)
    assert result == Admitted(OWNER)
    assert calls == [{"user_id": OWNER, "workspace_id": "w", "agent_id": trigger.agent_id}]
    assert sent == []


async def test_an_owner_only_bot_keeps_out_another_linked_member_who_may_run_the_agent():
    admission, sent, calls = _admission(identities=_Identities({ALICE_TG: "alice"}))
    trigger = _trigger()
    first = await admission.admit(object(), trigger, _message(ALICE_TG), ONLY_OWNER)
    second = await admission.admit(object(), trigger, _message(ALICE_TG), ONLY_OWNER)
    assert isinstance(first, Refused) and isinstance(second, Refused)
    assert calls == []
    assert len(sent) == 1
    assert "private" in sent[0][1]


async def test_an_owner_only_bot_points_an_unlinked_sender_at_the_link_page():
    admission, sent, _ = _admission()
    result = await admission.admit(object(), _trigger(), _message(STRANGER_TG), ONLY_OWNER)
    assert isinstance(result, Refused)
    assert "/link/telegram?bot=acme_bot" in sent[0][1]


async def test_a_listed_id_reaches_the_agent_unlinked_and_runs_as_the_owner():
    trigger = _trigger()
    admission, sent, calls = _admission()
    result = await admission.admit(object(), trigger, _message(ALICE_TG), LISTED)
    assert result == Admitted(OWNER, sender=f"telegram:{ALICE_TG}")
    assert calls == [{"user_id": OWNER, "workspace_id": "w", "agent_id": trigger.agent_id}]
    assert sent == []


async def test_an_id_off_the_list_is_kept_out_and_never_asked_to_link():
    admission, sent, calls = _admission(identities=_Identities({STRANGER_TG: "alice"}))
    trigger = _trigger()
    first = await admission.admit(object(), trigger, _message(STRANGER_TG), LISTED)
    second = await admission.admit(object(), trigger, _message(STRANGER_TG), LISTED)
    assert isinstance(first, Refused) and isinstance(second, Refused)
    assert calls == []
    assert len(sent) == 1
    assert "private" in sent[0][1]
    assert "link" not in sent[0][1]


async def test_a_listed_bot_stops_when_its_owner_may_no_longer_run_the_agent():
    admission, _, _ = _admission(may_run=False)
    result = await admission.admit(object(), _trigger(), _message(ALICE_TG), LISTED)
    assert isinstance(result, Refused)


def test_a_list_names_at_least_one_numeric_id_and_other_modes_name_none():
    with pytest.raises(ValueError):
        Senders(allow="ids", ids=[])
    with pytest.raises(ValueError):
        Senders(allow="ids", ids=["@alice"])
    with pytest.raises(ValueError):
        Senders(allow="owner", ids=[ALICE_TG])
    with pytest.raises(ValueError):
        Senders(allow="ids", ids=["\u0661\u0662\u0663"])
    with pytest.raises(ValueError):
        Senders.model_validate({"allow": "owner", "by": "someone-else"})
    assert Senders(allow="ids", ids=[" 111 ", "111", "222"]).ids == ("111", "222")


def test_a_bot_added_without_a_choice_answers_only_whoever_added_it():
    assert senders_to_store(True, None, "adder") == {"allow": "owner", "ids": [], "by": "adder"}
    assert senders_to_store(True, Senders(allow="ids", ids=["1"]), "editor") == {
        "allow": "ids",
        "ids": ["1"],
        "by": "editor",
    }
    assert senders_to_store(False, None, "adder") is None


async def test_the_one_who_chose_the_senders_is_the_owner_not_the_creator(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    event = _message(ALICE_TG)
    source = SimpleNamespace(
        id=event.source_id,
        workspace_id="w",
        webhook_type="telegram",
        credential_key="k",
        senders={"allow": "ids", "ids": [ALICE_TG], "by": "editor"},
        created_by=OWNER,
    )
    door = await event_admission(_Session(source), event)
    assert door is not None
    assert door.owner_id == "editor"
    assert door.senders == Senders(allow="ids", ids=[ALICE_TG])


async def test_a_source_that_never_chose_keeps_admitting_members_who_may_run(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    event = _message(ALICE_TG)
    source = SimpleNamespace(
        id=event.source_id,
        workspace_id="w",
        webhook_type="telegram",
        credential_key="k",
        senders=None,
        created_by=OWNER,
    )
    door = await event_admission(_Session(source), event)
    assert door is not None
    assert (door.senders, door.owner_id) == (Senders(allow="members"), None)


async def test_a_source_reads_its_own_choice_of_senders(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    event = _message(ALICE_TG)
    source = SimpleNamespace(
        id=event.source_id,
        workspace_id="w",
        webhook_type="telegram",
        credential_key="k",
        senders=SendersRecord(allow="ids", ids=[ALICE_TG], by=OWNER).model_dump(mode="json"),
        created_by=OWNER,
    )
    door = await event_admission(_Session(source), event)
    assert door is not None and door.senders == Senders(allow="ids", ids=[ALICE_TG])


# An event forwarded into another stream keeps its sender admission.

CATALOG = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"
ENTRIES = {
    raw["slug"]: SourceTypeEntry.model_validate(raw)
    for raw in json.loads(CATALOG.read_text())["source_types"]
}


class _Catalog:
    def __init__(self, _session):
        pass

    async def get(self, slug):
        return ENTRIES.get(slug)


class _Session:
    def __init__(self, *sources):
        self.sources = {source.id: source for source in sources}

    async def get(self, _model, source_id):
        return self.sources.get(source_id)


class _Ingest:
    appended: list[StreamEvent] = []

    def __init__(self, _session, user_context, _settings, _bus):
        self.user_context = user_context

    async def append(self, stream_id, event, *, event_key, depth, event_id, **stream_fields):
        _Ingest.appended.append(
            StreamEvent(
                **event.model_dump(exclude={"id"}),
                id=event_id,
                stream_id=stream_id,
                workspace_id=self.user_context.workspace_id,
                created_by=self.user_context.user_id,
                event_key=event_key,
                received_at=datetime.now(UTC),
                depth=depth,
                **stream_fields,
            )
        )


async def _forwarded(original: StreamEvent, monkeypatch) -> StreamEvent:
    _Ingest.appended = []
    monkeypatch.setattr(forward, "StreamIngest", _Ingest)
    subscription = SimpleNamespace(
        id=uuid4(), workspace_id="w", created_by="member", output_stream_ids=[uuid4()]
    )
    await ForwardHandler(SimpleNamespace(FORWARD_DEPTH=5), bus=None).handle(
        subscription, original, session=None
    )
    [copy] = _Ingest.appended
    return copy


async def test_a_forwarded_telegram_message_from_an_unlinked_sender_is_refused(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    original = _message(STRANGER_TG)
    source = SimpleNamespace(
        id=original.source_id,
        workspace_id="w",
        webhook_type="telegram",
        credential_key="k",
        senders=None,
        created_by="member",
    )
    copy = await _forwarded(original, monkeypatch)
    assert (copy.source_id, copy.source_type) == (original.source_id, "telegram")

    door = await event_admission(_Session(source), copy)
    assert door is not None
    admission, _, calls = _admission()
    assert isinstance(await admission.admit(object(), _trigger(), copy, door), Refused)
    assert calls == []


async def test_an_event_of_an_admitting_type_without_its_source_is_refused(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    sourceless = _message(STRANGER_TG).model_copy(update={"source_id": None})
    with pytest.raises(LookupError):
        await event_admission(_Session(), sourceless)


async def test_an_event_from_no_source_type_admits_anyone(monkeypatch):
    monkeypatch.setattr(sender_admission, "CatalogSourceTypeRepository", _Catalog)
    published = _message(STRANGER_TG).model_copy(update={"source_id": None, "source_type": None})
    assert await event_admission(_Session(), published) is None
