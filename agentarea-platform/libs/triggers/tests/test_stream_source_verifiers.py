"""Sentry, YooKassa and GitHub as stream sources: who may post, what the event is called."""

import base64
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from agentarea_streams.domain import WebhookSourceSpec
from agentarea_triggers import webhook_verification
from agentarea_triggers.webhook_intake import webhook_event_key, webhook_event_kind
from agentarea_triggers.webhook_manager import DefaultWebhookManager, WebhookExecutionCallback
from agentarea_triggers.webhook_verification import (
    SigningSecretUnavailableError,
    YooKassaNotificationVerifier,
    channel_credential_secret_name,
    resolve_signing_secret,
    verify_webhook_signature,
    webhook_signing_status,
)

SENTRY_SECRET = "sentry-client-secret"  # noqa: S105
SENTRY_BODY = json.dumps({"action": "created", "data": {"issue": {"id": "42"}}}).encode()


class _Reader:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    async def get_secret(self, name: str) -> str | None:
        return self.values.get(name)


class _Capture(WebhookExecutionCallback):
    def __init__(self):
        self.parsed: dict | None = None

    async def execute_webhook_trigger(self, webhook_id: str, request_data: dict) -> object:
        self.parsed = request_data
        return {"status": "accepted"}


def _sentry_signature(body: bytes, secret: str = SENTRY_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _spec(webhook_type: str, validation_rules: dict | None = None) -> WebhookSourceSpec:
    source_id = uuid4()
    return WebhookSourceSpec(
        id=source_id,
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        webhook_id=f"wh-{webhook_type}",
        webhook_type=webhook_type,
        allowed_methods=["POST"],
        validation_rules=validation_rules or {},
        webhook_config=None,
        credential_key=source_id,
    )


async def _deliver(spec: WebhookSourceSpec, reader: _Reader, headers: dict, body: bytes):
    capture = _Capture()
    manager = DefaultWebhookManager(execution_callback=capture, secret_reader=reader)
    await manager.register_webhook(spec)
    result = await manager.handle_webhook_request(
        spec.webhook_id, "POST", headers, json.loads(body), {}, raw_body=body
    )
    return result, capture.parsed


def _stored(webhook_type: str, key, credentials: dict) -> dict[str, str]:
    return {channel_credential_secret_name(webhook_type, key): json.dumps(credentials)}


# -- Sentry ----------------------------------------------------------------


async def test_sentry_accepts_the_hmac_of_the_raw_body():
    headers = {"sentry-hook-signature": _sentry_signature(SENTRY_BODY)}
    result = await verify_webhook_signature(
        "sentry", {"client_secret": SENTRY_SECRET}, None, headers, SENTRY_BODY, _Reader(), uuid4()
    )
    assert result is True


@pytest.mark.parametrize(
    "headers",
    [
        {"sentry-hook-signature": _sentry_signature(SENTRY_BODY, "another secret")},
        {"sentry-hook-signature": "sha256=" + _sentry_signature(SENTRY_BODY)},
        {},
    ],
    ids=["wrong secret", "prefixed", "no header"],
)
async def test_sentry_refuses_anything_but_its_own_signature(headers):
    result = await verify_webhook_signature(
        "sentry", {"client_secret": SENTRY_SECRET}, None, headers, SENTRY_BODY, _Reader(), uuid4()
    )
    assert result is False


async def test_sentry_without_a_client_secret_fails_closed():
    headers = {"sentry-hook-signature": _sentry_signature(SENTRY_BODY)}
    assert (
        await verify_webhook_signature("sentry", {}, None, headers, SENTRY_BODY, _Reader(), uuid4())
        is False
    )
    assert await webhook_signing_status("sentry", {}, None, _Reader(), uuid4()) == "signed"


async def test_a_sentry_delivery_is_named_by_resource_and_action():
    spec = _spec("sentry")
    reader = _Reader(_stored("sentry", spec.credential_key, {"client_secret": SENTRY_SECRET}))
    headers = {
        "content-type": "application/json",
        "sentry-hook-resource": "issue",
        "sentry-hook-signature": _sentry_signature(SENTRY_BODY),
        "request-id": "req-7",
    }
    result, parsed = await _deliver(spec, reader, headers, SENTRY_BODY)
    assert result["status_code"] == 200, result
    assert parsed is not None
    assert webhook_event_kind("sentry", parsed) == "issue.created"
    assert webhook_event_key("sentry", parsed) == "request-id:req-7"


async def test_a_sentry_resource_without_an_action_is_the_resource_alone():
    spec = _spec("sentry")
    body = json.dumps({"data": {"event": {"id": "e"}}}).encode()
    reader = _Reader(_stored("sentry", spec.credential_key, {"client_secret": SENTRY_SECRET}))
    headers = {
        "sentry-hook-resource": "event_alert",
        "sentry-hook-signature": _sentry_signature(body),
    }
    _, parsed = await _deliver(spec, reader, headers, body)
    assert parsed is not None
    assert webhook_event_kind("sentry", parsed) == "event_alert"


def test_request_id_names_only_a_sentry_delivery():
    parsed = {"headers": {"Request-ID": "r1"}, "raw_data": {}}
    assert webhook_event_key("sentry", parsed) == "request-id:r1"
    assert webhook_event_key("generic", parsed).startswith("recv:")


# -- GitHub ----------------------------------------------------------------


async def test_a_github_delivery_is_keyed_by_its_delivery_id_and_named_by_event_and_action():
    secret = "gh"  # noqa: S105
    spec = _spec("github")
    body = json.dumps({"action": "opened", "pull_request": {"number": 1}}).encode()
    reader = _Reader(_stored("github", spec.credential_key, {"webhook_secret": secret}))
    headers = {
        "x-github-event": "pull_request",
        "x-github-delivery": "72d3162e",
        "x-hub-signature-256": "sha256="
        + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
    }
    result, parsed = await _deliver(spec, reader, headers, body)
    assert result["status_code"] == 200, result
    assert parsed is not None
    assert webhook_event_kind("github", parsed) == "pull_request.opened"
    assert webhook_event_key("github", parsed) == "x-github-delivery:72d3162e"


# -- YooKassa --------------------------------------------------------------

PAYMENT_ID = "2d4f5a8e-000f-5000-9000-1b3c5d7e9f00"
YK_BODY = json.dumps(
    {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {"id": PAYMENT_ID, "status": "succeeded", "amount": {"value": "10.00"}},
    }
).encode()


def _yookassa(handler) -> YooKassaNotificationVerifier:
    return YooKassaNotificationVerifier(transport=httpx.MockTransport(handler))


def _payment(status: str, object_id: str = PAYMENT_ID):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.requests.append(request)
        return httpx.Response(200, json={"id": object_id, "status": status})

    handler.requests = []
    return handler


async def test_yookassa_is_trusted_when_the_api_returns_the_object_in_the_notified_state():
    handler = _payment("succeeded")
    assert await _yookassa(handler).verify(YK_BODY, "shop-1", "live_key") is True
    (request,) = handler.requests
    assert str(request.url) == f"https://api.yookassa.ru/v3/payments/{PAYMENT_ID}"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"shop-1:live_key").decode()


async def test_yookassa_refuses_a_notification_the_api_contradicts():
    assert await _yookassa(_payment("pending")).verify(YK_BODY, "shop-1", "k") is False


@pytest.mark.parametrize("current", ["succeeded", "canceled"])
async def test_a_late_waiting_for_capture_notification_is_believed_once_the_payment_moved_on(
    current,
):
    body = json.dumps(
        {"type": "notification", "event": "payment.waiting_for_capture", "object": {"id": PAYMENT_ID}}
    ).encode()
    assert await _yookassa(_payment(current)).verify(body, "shop-1", "k") is True


@pytest.mark.parametrize("current", ["pending", "waiting_for_capture", "canceled"])
async def test_a_terminal_notification_must_match_the_api_exactly(current):
    assert await _yookassa(_payment(current)).verify(YK_BODY, "shop-1", "k") is False


async def test_yookassa_refuses_an_object_the_api_does_not_know():
    def missing(_request):
        return httpx.Response(404, json={"type": "error", "code": "not_found"})

    assert await _yookassa(missing).verify(YK_BODY, "shop-1", "k") is False


async def test_yookassa_refuses_when_the_api_cannot_be_reached():
    def unreachable(request):
        raise httpx.ConnectError("no route", request=request)

    assert await _yookassa(unreachable).verify(YK_BODY, "shop-1", "k") is False


@pytest.mark.parametrize(
    "body",
    [
        {"type": "notification", "event": "invoice.paid", "object": {"id": PAYMENT_ID}},
        {"type": "notification", "event": "payment.succeeded", "object": {"id": "../refunds/x"}},
        {"type": "notification", "event": "payment", "object": {"id": PAYMENT_ID}},
        {"type": "notification", "event": "payment.succeeded"},
        ["not", "an", "object"],
    ],
    ids=["unknown resource", "path in id", "no status", "no object", "not an object"],
)
async def test_yookassa_refuses_a_notification_it_cannot_check_without_asking(body):
    handler = _payment("succeeded")
    raw = json.dumps(body).encode()
    assert await _yookassa(handler).verify(raw, "shop-1", "k") is False
    assert handler.requests == []


async def test_yookassa_refunds_are_checked_against_the_refunds_endpoint():
    handler = _payment("succeeded", "rf-1")
    body = json.dumps(
        {"type": "notification", "event": "refund.succeeded", "object": {"id": "rf-1"}}
    ).encode()
    assert await _yookassa(handler).verify(body, "shop-1", "k") is True
    assert handler.requests[0].url.path == "/v3/refunds/rf-1"


async def test_yookassa_needs_its_shop_id_and_secret_key(monkeypatch):
    handler = _payment("succeeded")
    monkeypatch.setattr(webhook_verification, "yookassa_verifier", lambda: _yookassa(handler))
    key = uuid4()
    no_shop = await verify_webhook_signature(
        "yookassa",
        {},
        None,
        {},
        YK_BODY,
        _Reader(_stored("yookassa", key, {"secret_key": "k"})),
        key,
    )
    no_key = await verify_webhook_signature(
        "yookassa", {"shop_id": "shop-1"}, None, {}, YK_BODY, _Reader(), key
    )
    assert (no_shop, no_key) == (False, False)
    assert handler.requests == []
    assert await webhook_signing_status("yookassa", {}, None, _Reader(), key) == "signed"


async def test_a_yookassa_delivery_is_keyed_by_event_and_object_and_named_by_event(monkeypatch):
    monkeypatch.setattr(
        webhook_verification, "yookassa_verifier", lambda: _yookassa(_payment("succeeded"))
    )
    spec = _spec("yookassa", {"shop_id": "shop-1"})
    reader = _Reader(_stored("yookassa", spec.credential_key, {"secret_key": "k"}))
    result, parsed = await _deliver(spec, reader, {"content-type": "application/json"}, YK_BODY)
    assert result["status_code"] == 200, result
    assert parsed is not None
    assert webhook_event_kind("yookassa", parsed) == "payment.succeeded"
    assert webhook_event_key("yookassa", parsed) == f"yookassa:payment.succeeded:{PAYMENT_ID}"


async def test_a_forged_yookassa_delivery_is_refused(monkeypatch):
    monkeypatch.setattr(
        webhook_verification, "yookassa_verifier", lambda: _yookassa(_payment("canceled"))
    )
    spec = _spec("yookassa", {"shop_id": "shop-1"})
    reader = _Reader(_stored("yookassa", spec.credential_key, {"secret_key": "k"}))
    result, parsed = await _deliver(spec, reader, {}, YK_BODY)
    assert result["status_code"] == 400
    assert parsed is None


# -- Secrets held by reference ----------------------------------------------


async def test_a_secret_held_by_reference_is_read_from_the_named_workspace_secret():
    key = uuid4()
    reader = _Reader(
        {
            **_stored("github", key, {"webhook_secret": {"secret_name": "gh-hook"}}),
            "gh-hook": "from-the-catalog",
        }
    )
    assert await resolve_signing_secret("github", {}, None, reader, key) == "from-the-catalog"


async def test_a_reference_to_a_secret_that_is_gone_fails_closed():
    key = uuid4()
    reader = _Reader(_stored("github", key, {"webhook_secret": {"secret_name": "deleted"}}))
    with pytest.raises(SigningSecretUnavailableError):
        await resolve_signing_secret("github", {}, None, reader, key)
    body = b"{}"
    headers = {"x-hub-signature-256": "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()}
    assert await verify_webhook_signature("github", {}, None, headers, body, reader, key) is False
