"""One way in: the envelope a source's event gets, and what moves to workspace files."""

import base64
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application import source_intake
from agentarea_streams.application.source_intake import SourceIntake
from agentarea_streams.domain.envelope import provider_time, without_credentials
from agentarea_streams.domain.keys import MAX_INLINE_BODY_BYTES, event_id_for
from agentarea_streams.domain.models import AppendResult
from agentarea_streams.domain.source_types import SourceTypeEntry, Verification

RECEIVED = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FakeFiles:
    def __init__(self):
        self.stored: dict[str, tuple[bytes, str | None]] = {}

    async def put(self, workspace_id, path, data, content_type=None):
        self.stored[path] = (data, content_type)


class RecordingIngest:
    calls: list = []

    def __init__(self, session, context, settings, bus, clock):
        self.context = context
        self.clock = clock

    async def append(self, stream_id, event, **kwargs):
        RecordingIngest.calls.append(
            {"stream_id": stream_id, "event": event, "received_at": self.clock(), **kwargs}
        )
        return AppendResult(event_id=kwargs["event_id"], appended=True)


@pytest.fixture
def ingest(monkeypatch):
    RecordingIngest.calls = []
    monkeypatch.setattr(source_intake, "StreamIngest", RecordingIngest)
    return RecordingIngest


def _source(**over):
    fields = {
        "id": uuid4(),
        "stream_id": uuid4(),
        "workspace_id": "ws-1",
        "created_by": "user-1",
        "event_templates": None,
        "webhook_config": None,
    }
    return SimpleNamespace(**{**fields, **over})


ENTRY = SourceTypeEntry.model_validate(
    {
        "slug": "chat",
        "name": "Chat",
        "delivery": "webhook",
        "verification": {"scheme": "hmac", "secret": "s", "header": "X-Chat-Signature"},
        "credentials": [{"key": "s", "label": "S"}],
        "event": {
            "kind": "{body:type}",
            "key": "{body:id}",
            "session_key": "{body:chat}",
            "sender": "chat:{body:from}",
            "occurred_at": "{body:ts}",
            "attachments": {"path": "files", "fetch": "inline"},
        },
    }
)


async def _ingest(source, body, headers=None, entry=ENTRY, files=None, **kwargs):
    intake = SourceIntake(bus=object(), files=files or FakeFiles(), settings=EventStreamSettings())
    return await intake.ingest(
        None, source, entry, body=body, headers=headers or {}, received_at=RECEIVED, **kwargs
    )


async def test_the_envelope_carries_what_the_entry_reads(ingest):
    source = _source()
    body = {"type": "message", "id": "m1", "chat": "c7", "from": "u9", "ts": 1700000000}
    receipt = await _ingest(
        source, body, {"X-Chat-Signature": "sig", "Authorization": "Bearer t", "X-Trace": "1"}
    )
    (call,) = ingest.calls
    assert receipt.event_id == event_id_for(source.stream_id, "m1")
    assert call["event_key"] == "m1"
    assert call["source_type"] == "chat"
    assert call["session_key"] == f"{source.id}:c7"
    assert call["sender"] == "chat:u9"
    assert call["source_id"] == source.id
    assert call["received_at"] == RECEIVED
    event = call["event"]
    assert event.type == "message"
    assert event.subject == f"{source.id}:c7"
    assert event.time.year == 2023
    assert event.data == {"headers": {"X-Trace": "1"}, "body": body, "body_ref": None}


async def test_the_header_a_source_configured_is_kept_out_of_the_event(ingest):
    entry = SourceTypeEntry.model_validate(
        {
            **ENTRY.model_dump(),
            "verification": {
                "scheme": "hmac",
                "secret": "s",
                "header": "X-Chat-Signature",
                "configurable": ["scheme", "header"],
            },
        }
    )
    source = _source(webhook_config={"scheme": "shared_token", "header": "X-Hasura-Auth"})
    await _ingest(source, {"id": "m1"}, {"X-Hasura-Auth": "the-token", "X-Trace": "1"}, entry)
    (call,) = ingest.calls
    assert call["event"].data["headers"] == {"X-Trace": "1"}


async def test_an_event_without_a_key_is_never_a_repeat(ingest):
    source = _source()
    await _ingest(source, {"type": "message"})
    await _ingest(source, {"type": "message"})
    first, second = ingest.calls
    assert first["event_key"].startswith("recv:")
    assert first["event_id"] != second["event_id"]


async def test_a_sources_own_templates_replace_the_entrys(ingest):
    source = _source(event_templates={"kind": "{body:op}", "key": "{body:uid}"})
    await _ingest(source, {"op": "INSERT", "uid": "row-1", "id": "ignored"})
    (call,) = ingest.calls
    assert (call["event"].type, call["event_key"]) == ("INSERT", "row-1")


async def test_a_gap_names_its_own_kind_and_key(ingest):
    await _ingest(
        _source(), {"reason": "cursor reset"}, kind_override="source.gap", key_override="gap:1"
    )
    (call,) = ingest.calls
    assert (call["event"].type, call["event_key"]) == ("source.gap", "gap:1")


async def test_a_large_body_moves_to_files_and_is_referenced(ingest):
    files = FakeFiles()
    source = _source()
    body = {"id": "big", "text": "x" * (MAX_INLINE_BODY_BYTES + 10)}
    await _ingest(source, body, files=files)
    (call,) = ingest.calls
    data = call["event"].data
    assert data["body"] is None
    event_id = event_id_for(source.stream_id, "big")
    assert data["body_ref"] == f"events/{source.stream_id}/{event_id}/body.json"
    assert files.stored[data["body_ref"]][1] == "application/json"


async def test_inline_file_bytes_move_to_files_and_leave_a_reference(ingest):
    files = FakeFiles()
    source = _source()
    content = b"%PDF-1.7 report"
    body = {
        "id": "mail-1",
        "files": [
            {
                "name": "report.pdf",
                "mime": "application/pdf",
                "content_base64": base64.b64encode(content).decode(),
            }
        ],
    }
    await _ingest(source, body, files=files)
    (call,) = ingest.calls
    (attachment,) = call["attachments"]
    assert attachment.name == "report.pdf"
    assert attachment.size == len(content)
    assert attachment.sha256 == hashlib.sha256(content).hexdigest()
    assert attachment.stored is True
    assert files.stored[attachment.ref] == (content, "application/pdf")
    stored_body = call["event"].data["body"]
    assert "content_base64" not in stored_body["files"][0]
    assert stored_body["files"][0]["ref"] == attachment.ref
    assert "content_base64" in body["files"][0], "the caller's body is not changed"


async def test_provider_files_keep_the_providers_reference(ingest):
    entry = ENTRY.model_copy(
        update={
            "event": ENTRY.event.model_copy(
                update={
                    "attachments": ENTRY.event.attachments.model_copy(
                        update={"fetch": "telegram.getFile"}
                    )
                }
            )
        }
    )
    files = FakeFiles()
    body = {"id": "u1", "files": {"file_id": "F1", "file_name": "a.png", "file_size": 5}}
    await _ingest(_source(), body, entry=entry, files=files)
    (attachment,) = ingest.calls[0]["attachments"]
    assert (attachment.name, attachment.size, attachment.stored) == ("a.png", 5, False)
    assert '"file_id":"F1"' in attachment.ref and "telegram.getFile" in attachment.ref
    assert files.stored == {}


def test_credential_headers_never_reach_an_event():
    kept = without_credentials(
        {
            "Authorization": "Bearer x",
            "Cookie": "a=b",
            "X-Hub-Signature-256": "sha256=..",
            "X-Telegram-Bot-Api-Secret-Token": "t",
            "X-Shopify-Secret": "s",
            "X-Api-Key": "k",
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
        },
        Verification(scheme="hmac", secret="s", header="X-Hub-Signature-256"),
    )
    assert kept == {"Content-Type": "application/json", "X-GitHub-Event": "push"}


def test_provider_time_reads_seconds_milliseconds_and_iso():
    assert provider_time("1700000000").year == 2023
    assert provider_time("1700000000000").year == 2023
    assert provider_time("2026-10-15T12:00:00Z") == RECEIVED
    assert provider_time("Tue, 15 Oct 2026") is None
    assert provider_time(None) is None


def test_an_issued_whsec_is_a_standard_webhooks_secret():
    import base64

    from agentarea_streams.application.source_credentials import issue_credential
    from agentarea_streams.domain.source_types import SourceField

    whsec = issue_credential(SourceField(key="s", label="S", issued=True, format="whsec"))
    assert whsec.startswith("whsec_")
    assert 24 <= len(base64.b64decode(whsec.removeprefix("whsec_"), validate=True)) <= 64
    token = issue_credential(SourceField(key="t", label="T", issued=True))
    assert not token.startswith("whsec_") and len(token) >= 32
    assert issue_credential(SourceField(key="t", label="T", issued=True)) != token


CHAINED = SourceTypeEntry.model_validate(
    {
        "slug": "relay",
        "name": "Relay",
        "delivery": "webhook",
        "event": {
            "kind": "{body:type}",
            "key": "{body:id}",
            "depth": "{body:hop}",
            "correlation_id": "{body:chain}",
            "causation_id": "{body:cause}",
        },
    }
)


async def test_a_carried_depth_correlation_and_causation_continue_the_chain(ingest):
    chain, cause = str(uuid4()), str(uuid4())
    await _ingest(
        _source(), {"type": "t", "id": "r1", "hop": 2, "chain": chain, "cause": cause}, entry=CHAINED
    )
    (call,) = ingest.calls
    assert call["depth"] == 3
    assert (call["event"].correlation_id, call["event"].causation_id) == (chain, cause)


async def test_an_event_that_carries_nothing_starts_a_chain(ingest):
    await _ingest(_source(), {"type": "t", "id": "r1"}, entry=CHAINED)
    (call,) = ingest.calls
    assert call.get("depth", 0) == 0
    assert (call["event"].correlation_id, call["event"].causation_id) == (None, None)


async def test_a_carried_depth_past_the_limit_lands_one_over_it(ingest):
    limit = EventStreamSettings().FORWARD_DEPTH
    await _ingest(_source(), {"type": "t", "id": "r1", "hop": 10**12}, entry=CHAINED)
    await _ingest(_source(), {"type": "t", "id": "r2", "hop": limit}, entry=CHAINED)
    assert [call["depth"] for call in ingest.calls] == [limit + 1, limit + 1]


@pytest.mark.parametrize("hop", [-1, "x", 2.5, "", True, "2e3"])
async def test_a_carried_depth_that_is_not_a_count_is_ignored_and_logged(ingest, caplog, hop):
    await _ingest(_source(), {"type": "t", "id": "r1", "hop": hop}, entry=CHAINED)
    (call,) = ingest.calls
    assert call.get("depth", 0) == 0
    if hop != "":
        assert "depth" in caplog.text


async def test_a_carried_correlation_or_causation_that_is_not_a_uuid_is_ignored_and_logged(
    ingest, caplog
):
    await _ingest(
        _source(),
        {"type": "t", "id": "r1", "chain": "ws-b/evt", "cause": "' or 1=1"},
        entry=CHAINED,
    )
    (call,) = ingest.calls
    assert (call["event"].correlation_id, call["event"].causation_id) == (None, None)
    assert "correlation_id" in caplog.text and "causation_id" in caplog.text
