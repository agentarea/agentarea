"""Every template of the shipped catalog renders against what its provider really sends.

One or more sample deliveries per entry, shaped as the provider documents them
(or, for a polled entry, as the Go event-service hands its items over). Each
event field an entry templates renders for at least one sample, a provider time
parses, the files an entry points at are found, and the reply, admission and
handshake templates fill in completely.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from agentarea_streams.domain.envelope import (
    FALLBACK_KIND,
    attachment_items,
    attachment_path,
    read_event,
)
from agentarea_streams.domain.source_types import SourceTypeEntry
from agentarea_streams.domain.templates import (
    TemplateContext,
    render,
    render_first,
    render_value,
)

CATALOG = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"
ENTRIES = {
    raw["slug"]: SourceTypeEntry.model_validate(raw)
    for raw in json.loads(CATALOG.read_text())["source_types"]
}


@dataclass(frozen=True)
class Sample:
    body: Any
    headers: dict[str, str] = field(default_factory=dict)


MAIL = {
    "message_id": "<CAF=2b@mail.example.com>",
    "from": "Ann Lee <ann@example.com>",
    "reply_to": "",
    "to": "agent@your-domain.example",
    "cc": "",
    "subject": "Re: Invoice 1003",
    "date": "2026-10-19T10:00:00Z",
    "in_reply_to": "<CAF=2a@mail.example.com>",
    "references": ["<CAF=2a@mail.example.com>"],
    "text": "Please resend the invoice.",
    "html": "",
    "attachments": [
        {"name": "invoice.pdf", "mime": "application/pdf", "size": 3, "content_base64": "JVBE"}
    ],
}

SAMPLES: dict[str, list[Sample]] = {
    "generic_webhook": [
        Sample({"order": {"id": "A-1003"}}, {"webhook-id": "msg_2KWPBgLlAfxdpx2AI54pPJ85f4W"}),
        Sample({"order": {"id": "A-1004"}}, {"Idempotency-Key": "8e03978e-40d5-43e8"}),
    ],
    "github": [
        Sample(
            {
                "action": "opened",
                "issue": {"number": 1347, "title": "Found a bug"},
                "repository": {"full_name": "octocat/Hello-World"},
                "sender": {"login": "octocat", "id": 1},
            },
            {
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
                "X-Hub-Signature-256": "sha256=d57c68ca",
            },
        ),
        Sample(
            {"ref": "refs/heads/main", "sender": {"login": "octocat"}},
            {"X-GitHub-Event": "push", "X-GitHub-Delivery": "8a3e7d12-cc78-11e3"},
        ),
    ],
    "slack": [
        Sample(
            {
                "token": "XXYYZZ",
                "team_id": "T123ABC456",
                "api_app_id": "A123ABC456",
                "event": {
                    "type": "app_mention",
                    "user": "U061F7AUR",
                    "text": "<@U0LAN0Z89> is it everything a river should be?",
                    "ts": "1515449522.000016",
                    "channel": "C123ABC456",
                    "event_ts": "1515449522000016",
                    "files": [
                        {
                            "id": "F0S43PZDF",
                            "name": "tedair.gif",
                            "mimetype": "image/gif",
                            "size": 137531,
                            "url_private": "https://files.slack.com/files-pri/T0/F0/tedair.gif",
                        }
                    ],
                },
                "type": "event_callback",
                "event_id": "Ev0LAN670R",
                "event_time": 1515449522,
            }
        ),
        Sample(
            {
                "command": "/ask",
                "text": "weekly numbers",
                "user_id": "U2147483697",
                "channel_id": "C2147483705",
                "trigger_id": "13345224609.738474920.8088930838d88f008e0",
            }
        ),
    ],
    "telegram": [
        Sample(
            {
                "update_id": 81234,
                "message": {
                    "message_id": 17,
                    "from": {"id": 42, "is_bot": False, "first_name": "Ann", "username": "ann"},
                    "chat": {"id": 42, "first_name": "Ann", "type": "private"},
                    "date": 1760868000,
                    "text": "what is on my calendar today?",
                    "document": {
                        "file_id": "BQACAgIAAxkBAAIBG2",
                        "file_unique_id": "AgADGQ",
                        "file_name": "agenda.pdf",
                        "mime_type": "application/pdf",
                        "file_size": 20480,
                    },
                },
            }
        ),
    ],
    "linear": [
        Sample(
            {
                "action": "create",
                "type": "Issue",
                "createdAt": "2026-10-19T10:00:00.000Z",
                "actor": {"id": "2e4c4f1b-9a3c-4f8e-8c2b-1d0f5e6a7b8c", "type": "user"},
                "data": {"id": "a1b2", "title": "Checkout fails"},
                "url": "https://linear.app/acme/issue/ENG-1",
                "webhookTimestamp": 1760868000000,
            },
            {"Linear-Delivery": "234d1a4e-b617-4388-90fe-adc3633d6b72", "Linear-Event": "Issue"},
        ),
    ],
    "discord": [
        Sample(
            {
                "id": "1288443946281791548",
                "application_id": "1288443000000000000",
                "type": 3,
                "token": "aW50ZXJhY3Rpb24",
                "version": 1,
                "channel_id": "1100000000000000001",
                "guild_id": "1000000000000000001",
                "member": {"user": {"id": "53908232506183680", "username": "ann"}},
                "message": {"id": "1288440000000000002", "channel_id": "1100000000000000001"},
                "data": {"custom_id": "approve", "component_type": 2},
            }
        ),
        Sample(
            {
                "id": "1288443946281791549",
                "type": 2,
                "channel_id": "1100000000000000001",
                "member": {"user": {"id": "53908232506183680"}},
                "data": {
                    "name": "ask",
                    "resolved": {
                        "attachments": {
                            "1100": {
                                "id": "1100",
                                "filename": "chart.png",
                                "content_type": "image/png",
                                "size": 2048,
                                "url": "https://cdn.discordapp.com/attachments/1/1100/chart.png",
                            }
                        }
                    },
                },
            }
        ),
        Sample(
            {
                "op": 0,
                "s": 42,
                "t": "MESSAGE_CREATE",
                "d": {
                    "id": "1288440000000000003",
                    "channel_id": "1100000000000000001",
                    "author": {"id": "53908232506183680"},
                    "content": "hello",
                    "timestamp": "2026-10-19T10:00:00.123000+00:00",
                    "attachments": [],
                },
            }
        ),
    ],
    "stripe": [
        Sample(
            {
                "id": "evt_1NG8Du2eZvKYlo2CUI79vXWy",
                "object": "event",
                "type": "invoice.paid",
                "created": 1686089970,
                "data": {"object": {"id": "in_1NG8Ds2eZvKYlo2C"}},
            },
            {"Stripe-Signature": "t=1686089970,v1=5257a869e7ec"},
        ),
    ],
    "sentry": [
        Sample(
            {
                "action": "created",
                "actor": {"type": "application", "id": "sentry", "name": "Sentry"},
                "data": {"issue": {"id": "1170820242", "title": "Error: boom"}},
                "installation": {"uuid": "a8e5d37a-696c-4c54-adb5-b3f28d64c7de"},
            },
            {"Sentry-Hook-Resource": "issue", "Request-ID": "9b6b1d5e-0b0d-4d6b-8b8a-2d0e5f6a7b8c"},
        ),
    ],
    "yookassa": [
        Sample(
            {
                "type": "notification",
                "event": "payment.succeeded",
                "object": {
                    "id": "22d6d597-000f-5000-9000-145f6df21d6f",
                    "status": "succeeded",
                    "amount": {"value": "2.00", "currency": "RUB"},
                    "created_at": "2026-10-19T10:00:00.000Z",
                    "paid": True,
                },
            }
        ),
    ],
    "gmail": [
        Sample(
            {
                "message": {
                    "data": "eyJlbWFpbEFkZHJlc3MiOiAidXNlckBleGFtcGxlLmNvbSJ9",
                    "messageId": "2070443601311540",
                    "message_id": "2070443601311540",
                    "publishTime": "2026-10-19T10:00:00.123Z",
                    "publish_time": "2026-10-19T10:00:00.123Z",
                },
                "subscription": "projects/myproject/subscriptions/mysubscription",
            }
        ),
    ],
    "teams": [
        Sample(
            {
                "type": "message",
                "id": "1485983408511",
                "timestamp": "2026-10-19T10:00:00.2891902Z",
                "serviceUrl": "https://smba.trafficmanager.net/emea/",
                "channelId": "msteams",
                "from": {"id": "29:1XJKJMvc5GBtc2JwZq0oj8tHZmzrQgFmB", "name": "Ann Lee"},
                "conversation": {"id": "a:17I0kl8EkpE1O9PH5TWrzrLNwnWWcfrU7QZjKR"},
                "recipient": {"id": "28:c9e8c047-2a74-40a2-b28a-b162d5f5327c"},
                "text": "hello",
            }
        ),
    ],
    "email": [Sample({**MAIL, "date": "Sun, 19 Oct 2026 10:00:00 +0000"})],
    "imap": [Sample(MAIL)],
    "rss": [
        Sample(
            {
                "id": "https://example.com/posts/1003",
                "title": "Release 1.3",
                "link": "https://example.com/posts/1003",
                "published": "Sun, 19 Oct 2026 10:00:00 GMT",
                "updated": "",
                "summary": "What changed",
                "content": "",
                "author": "ann@example.com (Ann Lee)",
            }
        ),
        Sample(
            {
                "id": "urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a",
                "title": "Atom entry",
                "link": "https://example.com/atom/1",
                "published": "",
                "updated": "2026-10-19T10:00:00Z",
                "summary": "",
                "content": "",
                "author": "Ann Lee",
            }
        ),
    ],
    "mcp_events": [
        Sample(
            {
                "eventId": "evt_01HZY3K8Q5",
                "name": "issues/created",
                "timestamp": "2026-10-19T10:00:00Z",
                "data": {"id": 7},
            },
            {"webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek", "webhook-timestamp": "1760868000"},
        ),
    ],
}

HANDSHAKES: dict[str, list[Sample]] = {
    "slack": [
        Sample(
            {
                "token": "Jhj5dZrVaK7ZwHHjRyZWjbDl",
                "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P",
                "type": "url_verification",
            }
        )
    ],
    "discord": [Sample({"id": "1", "application_id": "2", "type": 1, "token": "t", "version": 1})],
    "mcp_events": [Sample({"type": "challenge", "challenge": "c-8f2e"})],
}

_EVENT_FIELDS = ("kind", "key", "session_key", "sender", "occurred_at")


def _context(sample: Sample) -> TemplateContext:
    return TemplateContext(body=sample.body, headers=sample.headers)


def test_every_entry_has_samples():
    assert set(SAMPLES) == set(ENTRIES)
    assert {slug for slug, entry in ENTRIES.items() if entry.handshake} == set(HANDSHAKES)


@pytest.mark.parametrize("slug", sorted(ENTRIES))
def test_every_event_field_renders_for_some_sample(slug):
    entry = ENTRIES[slug]
    rendered: dict[str, list[str]] = {name: [] for name in _EVENT_FIELDS}
    for sample in SAMPLES[slug]:
        context = _context(sample)
        for name in _EVENT_FIELDS:
            value = render_first(getattr(entry.event, name), context)
            if value is not None:
                rendered[name].append(value)
        fields = read_event(
            entry, None, source_id=uuid4(), headers=sample.headers, body=sample.body
        )
        assert fields.kind != FALLBACK_KIND, f"{slug}: {sample.body}"
        if entry.event.key is not None:
            assert fields.key is not None, f"{slug}: no key for {sample.body}"
        if entry.event.occurred_at is not None and render_first(
            entry.event.occurred_at, context
        ):
            assert fields.occurred_at is not None, f"{slug}: provider time does not parse"
    for name in _EVENT_FIELDS:
        if getattr(entry.event, name) is not None:
            assert rendered[name], f"{slug}: {name} renders for no sample"


@pytest.mark.parametrize("slug", sorted(s for s, e in ENTRIES.items() if e.event.attachments))
def test_the_files_an_entry_points_at_are_found(slug):
    entry = ENTRIES[slug]
    found = []
    for sample in SAMPLES[slug]:
        path = attachment_path(entry, sample.body)
        if path is not None:
            found.extend(attachment_items(sample.body, path))
    assert found, f"{slug}: no sample's files are found"
    for item in found:
        assert any(k in item for k in ("name", "filename", "file_name")), f"{slug}: {item}"


@pytest.mark.parametrize("slug", sorted(s for s, e in ENTRIES.items() if e.reply))
def test_the_reply_fills_in_completely(slug):
    entry = ENTRIES[slug]
    reply = entry.reply
    assert reply is not None
    sample = SAMPLES[slug][0]
    target = render_value(reply.target, _context(sample))
    assert set(target) == set(reply.target), f"{slug}: target {target}"
    if reply.request is None:
        return
    credentials = {key: f"{key}-value" for key in entry.secret_keys()}
    context = TemplateContext(
        values={"credentials": credentials, "target": target, "message": "Done: invoice resent."}
    )
    assert render(reply.request.url, context), f"{slug}: url"
    headers = render_value(reply.request.headers, context) or {}
    assert set(headers) == set(reply.request.headers), f"{slug}: headers {headers}"
    body = render_value(reply.request.json_body, context)
    assert _same_shape(body, reply.request.json_body), f"{slug}: body {body}"


def _same_shape(rendered: Any, template: Any) -> bool:
    if isinstance(template, dict):
        return (
            isinstance(rendered, dict)
            and set(rendered) == set(template)
            and all(_same_shape(rendered[k], v) for k, v in template.items())
        )
    return rendered is not None


@pytest.mark.parametrize("slug", sorted(s for s, e in ENTRIES.items() if e.admission))
def test_admission_reads_the_sender_of_a_message(slug):
    admission = ENTRIES[slug].admission
    assert admission is not None
    context = _context(SAMPLES[slug][0])
    assert render_first(admission.external_id, context)
    assert render_first(admission.chat, context)
    for template in (admission.text, admission.is_bot):
        assert template is None or render_first(template, context) is not None
    if admission.private is not None:
        assert render_first(admission.private, context) == admission.private_value


@pytest.mark.parametrize("slug", sorted(HANDSHAKES))
def test_a_handshake_is_recognised_and_answered(slug):
    for handshake, sample in zip(ENTRIES[slug].handshake, HANDSHAKES[slug], strict=True):
        context = _context(sample)
        assert render(handshake.when, context) == handshake.equals
        answer = render_value(handshake.respond, context)
        assert _same_shape(answer, handshake.respond), f"{slug}: {answer}"
