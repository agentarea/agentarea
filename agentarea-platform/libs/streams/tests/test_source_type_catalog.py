"""The shipped catalog: every entry is valid, and reads each provider's events as the code used to."""

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from agentarea_streams.domain.envelope import read_event
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_streams.domain.templates import TemplateContext, render

EXAMPLE_PAY = SourceTypeEntry.model_validate(
    json.loads((Path(__file__).parent / "example_pay.json").read_text())
)

CATALOG = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_EVENT_KINDS = {"body", "header", "first_key"}


def _entries() -> dict[str, SourceTypeEntry]:
    raw = json.loads(CATALOG.read_text())["source_types"]
    return {entry["slug"]: SourceTypeEntry.model_validate(entry) for entry in raw}


ENTRIES = _entries()


def _event(slug: str, body, headers=None):
    return read_event(ENTRIES[slug], None, source_id=uuid4(), headers=headers or {}, body=body)


def test_every_provider_the_code_knew_has_an_entry():
    assert set(ENTRIES) >= {
        "generic_webhook",
        "github",
        "slack",
        "telegram",
        "linear",
        "discord",
        "stripe",
        "sentry",
        "gmail",
        "teams",
        "email",
        "imap",
        "rss",
        "mcp_events",
    }


@pytest.mark.parametrize("slug", sorted(ENTRIES))
def test_event_templates_use_only_event_placeholders(slug):
    event = ENTRIES[slug].event
    for field in (event.kind, event.key, event.session_key, event.sender, event.occurred_at):
        for template in [field] if isinstance(field, str) else field or []:
            for expression in _PLACEHOLDER.findall(template):
                kind, sep, _ = expression.partition(":")
                assert sep and kind in _EVENT_KINDS, f"{slug}: {{{expression}}}"


@pytest.mark.parametrize(
    "slug", sorted(slug for slug, entry in ENTRIES.items() if entry.delivery != "platform")
)
def test_a_source_can_be_made_of_every_entry(slug):
    entry = ENTRIES[slug]
    assert entry.accepts("webhook") or entry.accepts("poll")
    if entry.accepts("webhook"):
        assert entry.verification is not None, f"{slug} takes webhooks but verifies none"
    if entry.accepts("poll"):
        assert entry.poll is not None, f"{slug} is polled but says not how"
    if entry.verification and entry.verification.secret:
        assert entry.verification.secret in entry.secret_keys()


def test_github_kind_is_the_event_and_action_and_the_delivery_id_is_the_key():
    fields = _event(
        "github",
        {"action": "opened", "sender": {"login": "octo"}},
        {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1"},
    )
    assert (fields.kind, fields.key, fields.sender) == ("pull_request.opened", "d-1", "github:octo")
    push = _event("github", {"ref": "main"}, {"X-GitHub-Event": "push", "X-GitHub-Delivery": "d"})
    assert push.kind == "push"


def test_telegram_names_the_update_type_keys_the_update_and_joins_the_chat():
    source_id = uuid4()
    body = {
        "update_id": 81234,
        "message": {"chat": {"id": 555}, "from": {"id": 42}, "date": 1700000000, "text": "hi"},
    }
    fields = read_event(ENTRIES["telegram"], None, source_id=source_id, headers={}, body=body)
    assert fields.kind == "message"
    assert fields.key == "update:81234"
    assert fields.session_key == f"{source_id}:555"
    assert fields.sender == "tg:42"
    assert fields.occurred_at is not None and fields.occurred_at.year == 2023
    callback = _event(
        "telegram",
        {"update_id": 1, "callback_query": {"from": {"id": 7}, "message": {"chat": {"id": 9}}}},
    )
    assert callback.kind == "callback_query"
    assert callback.session_key.endswith(":9")


def test_slack_events_api_kind_key_and_thread():
    fields = _event(
        "slack",
        {
            "event_id": "Ev1",
            "event_time": 1700000000,
            "event": {"type": "app_mention", "channel": "C1", "ts": "1.2", "user": "U1"},
        },
    )
    assert (fields.kind, fields.key, fields.sender) == ("app_mention", "Ev1", "slack:U1")
    assert fields.session_key.endswith(":C1:1.2")


def test_slack_url_verification_is_answered_not_recorded():
    handshake = ENTRIES["slack"].handshake[0]
    context = TemplateContext(body={"type": "url_verification", "challenge": "abc"})
    assert render(handshake.when, context) == handshake.equals


def test_sentry_kind_joins_resource_and_action_and_request_id_keys_it():
    fields = _event(
        "sentry",
        {"action": "created"},
        {"Sentry-Hook-Resource": "issue", "Request-ID": "req-9"},
    )
    assert (fields.kind, fields.key) == ("issue.created", "req-9")


def test_an_api_lookup_key_is_one_object_reaching_one_state():
    body = {"event": "payment.succeeded", "object": {"id": "p1", "status": "succeeded"}}
    fields = read_event(EXAMPLE_PAY, None, source_id=uuid4(), headers={}, body=body)
    assert (fields.kind, fields.key) == ("payment.succeeded", "payment.succeeded:p1")


def test_stripe_linear_discord_gmail_teams():
    assert _event("stripe", {"id": "evt_1", "type": "invoice.paid"}).key == "evt_1"
    linear = _event("linear", {"type": "Issue", "action": "create"}, {"Linear-Delivery": "l1"})
    assert (linear.kind, linear.key) == ("Issue.create", "l1")
    discord = _event("discord", {"type": 2, "id": "i1", "channel_id": "c1"})
    assert (discord.kind, discord.key) == ("interaction.2", "i1")
    gmail = _event("gmail", {"message": {"messageId": "m1"}})
    assert (gmail.kind, gmail.key) == ("message_received", "m1")
    teams = _event("teams", {"type": "message", "id": "a1", "conversation": {"id": "conv"}})
    assert teams.kind == "message" and teams.session_key.endswith(":conv")


def test_mail_threads_on_the_first_reference():
    fields = _event(
        "imap",
        {"message_id": "<b@x>", "references": ["<a@x>", "<b@x>"], "from": "Ann <ann@x>"},
    )
    assert fields.key == "<b@x>"
    assert fields.session_key.endswith(":<a@x>")
    first = _event("email", {"message_id": "<a@x>", "from": "ann@x"})
    assert first.session_key.endswith(":<a@x>")


def test_a_generic_webhook_without_a_delivery_id_has_no_key():
    assert _event("generic_webhook", {"x": 1}).key is None
    assert _event("generic_webhook", {}, {"Idempotency-Key": "k"}).key == "k"
    assert _event("generic_webhook", {}).kind == "webhook"


def test_mcp_events_is_one_generic_entry_by_standard_webhooks_or_poll():
    entry = ENTRIES["mcp_events"]
    assert entry.delivery == "both"
    scheme = entry.verification
    assert scheme is not None
    assert (scheme.scheme, scheme.payload, scheme.secret_format) == (
        "hmac_timestamped",
        "{id}.{timestamp}.{body}",
        "whsec",
    )
    assert (scheme.header, scheme.timestamp_header, scheme.id_header) == (
        "webhook-signature",
        "webhook-timestamp",
        "webhook-id",
    )
    assert scheme.tolerance_seconds == 300
    assert [h.lower() for h in scheme.required_headers] == ["x-mcp-subscription-id"]
    secret = next(f for f in entry.credentials if f.key == scheme.secret)
    assert secret.issued and secret.format == "whsec"
    assert {f.key for f in entry.config} == {"mcp_instance_id", "event", "arguments"}
    assert entry.poll is not None and entry.poll.transport == "mcp_events"
    assert entry.registration is not None and entry.registration.transport == "mcp_events"
    fields = _event(
        "mcp_events",
        {"eventId": "evt_7", "name": "ticket.created", "timestamp": "2026-10-19T10:00:00Z"},
    )
    assert (fields.kind, fields.key) == ("ticket.created", "evt_7")
    assert fields.occurred_at is not None
    assert (fields.depth, fields.correlation_id, fields.causation_id) == (None, None, None)


def test_mcp_events_reads_the_chain_of_an_event_our_own_server_sends():
    from datetime import UTC, datetime

    from agentarea_streams.domain import StreamEvent
    from agentarea_streams.domain.mcp_events import occurrence

    origin = StreamEvent(
        id=uuid4(),
        type="order.paid",
        source="test",
        data={"body": {}},
        stream_id=uuid4(),
        workspace_id="ws",
        created_by="u",
        event_key="k",
        received_at=datetime.now(UTC),
        depth=2,
        correlation_id=str(uuid4()),
    )
    body = json.loads(json.dumps(occurrence(origin, f"ws/{origin.stream_id}")))
    fields = _event("mcp_events", body)
    assert (fields.depth, fields.correlation_id, fields.causation_id) == (
        "2",
        origin.correlation_id,
        str(origin.id),
    )
    assert fields.kind == "order.paid"
    assert body["name"] == f"ws/{origin.stream_id}"


def test_mcp_events_names_an_event_by_its_type_when_the_payload_carries_no_kind():
    body = {
        "eventId": "evt_8",
        "name": "ticket.created",
        "timestamp": "2026-10-19T10:00:00Z",
        "data": {"ticket": {"id": "T-1"}},
    }
    assert _event("mcp_events", body).kind == "ticket.created"


def test_no_member_source_can_be_made_of_the_platform_entry():
    entry = ENTRIES["platform"]
    assert not entry.accepts("webhook")
    assert not entry.accepts("poll")
