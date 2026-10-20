"""The five verification schemes, driven by entries, refuse what they should and pass the rest."""

import base64
import hashlib
import hmac
import time

import pytest
from agentarea_streams.domain.source_types import Verification
from agentarea_streams.domain.verification import VerificationError, configured, verify_request
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BODY = b'{"action":"opened"}'


async def _no_lookup(method, url, auth):
    raise AssertionError("no lookup expected")


async def _verify(
    scheme, headers, credentials, *, body=BODY, parsed=None, config=None, lookup=None
):
    await verify_request(
        scheme,
        headers=headers,
        raw_body=body,
        body=parsed,
        credentials=credentials,
        config=config or {},
        lookup=lookup or _no_lookup,
    )


def _hex(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


GITHUB = Verification(
    scheme="hmac", secret="webhook_secret", header="X-Hub-Signature-256", prefix="sha256="
)


async def test_hmac_passes_the_providers_signature_and_refuses_another():
    good = {"x-hub-signature-256": "sha256=" + _hex("s3cret", BODY)}
    await _verify(GITHUB, good, {"webhook_secret": "s3cret"})
    with pytest.raises(VerificationError):
        await _verify(GITHUB, good, {"webhook_secret": "other"})
    with pytest.raises(VerificationError, match="missing header"):
        await _verify(GITHUB, {}, {"webhook_secret": "s3cret"})


async def test_a_source_without_its_secret_is_refused_not_waved_through():
    with pytest.raises(VerificationError, match="no webhook_secret"):
        await _verify(GITHUB, {"x-hub-signature-256": "sha256=x"}, {})


SLACK = Verification(
    scheme="hmac_timestamped",
    secret="signing_secret",
    header="X-Slack-Signature",
    timestamp_header="X-Slack-Request-Timestamp",
    payload="v0:{timestamp}:{body}",
    prefix="v0=",
)


async def test_slack_signs_version_timestamp_and_body_within_the_replay_window():
    now = str(int(time.time()))
    signature = "v0=" + _hex("sec", f"v0:{now}:".encode() + BODY)
    headers = {"X-Slack-Signature": signature, "X-Slack-Request-Timestamp": now}
    await _verify(SLACK, headers, {"signing_secret": "sec"})
    stale = str(int(time.time()) - 3600)
    stale_sig = "v0=" + _hex("sec", f"v0:{stale}:".encode() + BODY)
    with pytest.raises(VerificationError, match="replay window"):
        await _verify(
            SLACK,
            {"X-Slack-Signature": stale_sig, "X-Slack-Request-Timestamp": stale},
            {"signing_secret": "sec"},
        )


async def test_stripe_carries_timestamp_and_signatures_in_one_header():
    stripe = Verification(
        scheme="hmac_timestamped",
        secret="signing_secret",
        header="Stripe-Signature",
        signature_format="kv",
        payload="{timestamp}.{body}",
    )
    now = str(int(time.time()))
    signature = _hex("whsec_x", f"{now}.".encode() + BODY)
    header = {"Stripe-Signature": f"t={now},v1=bogus,v1={signature}"}
    await _verify(stripe, header, {"signing_secret": "whsec_x"})


async def test_standard_webhooks_signs_id_timestamp_and_body_with_a_whsec_secret():
    scheme = Verification(
        scheme="hmac_timestamped",
        secret="signing_secret",
        header="webhook-signature",
        timestamp_header="webhook-timestamp",
        id_header="webhook-id",
        payload="{id}.{timestamp}.{body}",
        signature_format="list",
        encoding="base64",
        secret_format="whsec",
    )
    key = b"0123456789abcdef"
    now = str(int(time.time()))
    raw = hmac.new(key, f"msg_1.{now}.".encode() + BODY, hashlib.sha256).digest()
    headers = {
        "webhook-id": "msg_1",
        "webhook-timestamp": now,
        "webhook-signature": "v1,AAAA v1," + base64.b64encode(raw).decode(),
    }
    await _verify(scheme, headers, {"signing_secret": "whsec_" + base64.b64encode(key).decode()})


async def test_ed25519_checks_the_providers_key_over_timestamp_and_body():
    scheme = Verification(
        scheme="ed25519",
        secret="public_key",
        header="X-Signature-Ed25519",
        timestamp_header="X-Signature-Timestamp",
        payload="{timestamp}{body}",
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw().hex()
    signature = private.sign(b"1700000000" + BODY).hex()
    headers = {"X-Signature-Ed25519": signature, "X-Signature-Timestamp": "1700000000"}
    await _verify(scheme, headers, {"public_key": public})
    with pytest.raises(VerificationError):
        await _verify(scheme, {**headers, "X-Signature-Timestamp": "1"}, {"public_key": public})


async def test_a_shared_token_must_be_repeated_exactly():
    scheme = Verification(
        scheme="shared_token", secret="secret_token", header="X-Telegram-Bot-Api-Secret-Token"
    )
    await _verify(scheme, {"x-telegram-bot-api-secret-token": "t"}, {"secret_token": "t"})
    with pytest.raises(VerificationError):
        await _verify(scheme, {"x-telegram-bot-api-secret-token": "u"}, {"secret_token": "t"})


EXAMPLE_PAY = Verification(
    scheme="api_lookup",
    request={
        "method": "GET",
        "url": "https://api.payments.example/v3/{collection}/{body:object.id}",
        "auth": {"username": "{config.shop_id}", "password": "{credentials.secret_key}"},
    },
    collection_from="{body:event}",
    collections={"payment": "payments"},
    expect={"id": "{body:object.id}", "status": "{body:object.status}"},
    later={"waiting_for_capture": ["succeeded", "canceled"]},
)


async def test_api_lookup_believes_a_notification_the_providers_api_confirms():
    calls = []

    async def lookup(method, url, auth):
        calls.append((method, url, auth))
        return 200, {"id": "p1", "status": "succeeded"}

    notification = {"event": "payment.succeeded", "object": {"id": "p1", "status": "succeeded"}}
    await _verify(
        EXAMPLE_PAY,
        {},
        {"secret_key": "live_x"},
        parsed=notification,
        config={"shop_id": "42"},
        lookup=lookup,
    )
    assert calls == [("GET", "https://api.payments.example/v3/payments/p1", ("42", "live_x"))]


async def test_api_lookup_accepts_a_state_the_object_has_moved_on_to_and_refuses_others():
    async def captured(method, url, auth):
        return 200, {"id": "p1", "status": "succeeded"}

    async def canceled_elsewhere(method, url, auth):
        return 200, {"id": "p1", "status": "pending"}

    waiting = {
        "event": "payment.waiting_for_capture",
        "object": {"id": "p1", "status": "waiting_for_capture"},
    }
    kwargs = {"parsed": waiting, "config": {"shop_id": "42"}}
    await _verify(EXAMPLE_PAY, {}, {"secret_key": "k"}, lookup=captured, **kwargs)
    with pytest.raises(VerificationError):
        await _verify(EXAMPLE_PAY, {}, {"secret_key": "k"}, lookup=canceled_elsewhere, **kwargs)


async def test_no_verification_passes_everything():
    await _verify(Verification(scheme="none"), {}, {})


def test_a_source_overrides_only_the_settings_its_entry_makes_configurable():
    generic = Verification(
        scheme="hmac",
        secret="signing_secret",
        header="X-Webhook-Signature",
        configurable=["header", "algorithm", "prefix"],
    )
    mine = configured(generic, {"header": "X-Hasura-Sig", "algorithm": "sha1", "secret": "x"})
    assert (mine.header, mine.algorithm, mine.secret) == ("X-Hasura-Sig", "sha1", "signing_secret")
    with pytest.raises(ValueError):
        configured(generic, {"algorithm": "md5"})


@pytest.mark.parametrize("scheme", ["none", "api_lookup", "ed25519"])
def test_a_source_cannot_switch_itself_to_a_scheme_that_signs_nothing_of_its_own(scheme):
    generic = Verification(
        scheme="hmac", secret="signing_secret", header="X-Webhook-Signature", configurable=["scheme"]
    )
    with pytest.raises(VerificationError):
        configured(generic, {"scheme": scheme})
    for signing in ("hmac", "hmac_timestamped", "shared_token"):
        assert configured(generic, {"scheme": signing}).scheme == signing


def _standard_webhooks(secret: str, msg_id: str, ts: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    mac = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


MCP_EVENTS = Verification(
    scheme="hmac_timestamped",
    secret="signing_secret",
    header="webhook-signature",
    timestamp_header="webhook-timestamp",
    id_header="webhook-id",
    payload="{id}.{timestamp}.{body}",
    signature_format="list",
    encoding="base64",
    secret_format="whsec",
    required_headers=["X-MCP-Subscription-Id"],
)
WHSEC = "whsec_" + base64.b64encode(b"k" * 32).decode()


def _mcp_headers(**extra) -> dict[str, str]:
    ts = int(time.time())
    headers = {
        "webhook-id": "evt_1",
        "webhook-timestamp": str(ts),
        "webhook-signature": _standard_webhooks(WHSEC, "evt_1", ts, BODY),
    }
    headers.update(extra)
    return headers


async def test_a_required_header_must_be_present_even_when_the_signature_holds():
    await _verify(
        MCP_EVENTS, _mcp_headers(**{"X-MCP-Subscription-Id": "sub_1"}), {"signing_secret": WHSEC}
    )
    with pytest.raises(VerificationError, match="X-MCP-Subscription-Id"):
        await _verify(MCP_EVENTS, _mcp_headers(), {"signing_secret": WHSEC})
