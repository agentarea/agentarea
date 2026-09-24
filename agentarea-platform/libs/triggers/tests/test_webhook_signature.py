"""Tests for webhook signature verification wiring (verify_webhook_signature)."""

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from agentarea_triggers.webhook_verification import (
    channel_credential_secret_name,
    resolve_signing_secret,
    verify_webhook_signature,
)

BODY = b'{"event":"push","ref":"refs/heads/main"}'


def _github_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _FakeSecretReader:
    """In-memory SecretReader stand-in, keyed by secret name."""

    def __init__(self, values: dict[str, str] | None = None):
        self._values = dict(values or {})

    async def get_secret(self, name: str) -> str | None:
        return self._values.get(name)


# secret_reader/trigger_id are required params, not `| None` — a security
# dependency that could be silently omitted is how the store went unread in
# the first place. These are the "nothing real to pass" stand-ins for tests
# below that resolve their secret from validation_rules/webhook_config (or
# deliberately resolve nothing anywhere) and never actually touch the store.
_EMPTY_READER = _FakeSecretReader()
_UNUSED_TRIGGER_ID = uuid4()


@pytest.mark.asyncio
async def test_github_no_secret_anywhere_fails_closed():
    # github has a registered signature scheme; no secret configured at all
    # => reject, never silently treated as "verification not enabled".
    result = await verify_webhook_signature(
        "github", {}, {}, {}, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is False


@pytest.mark.asyncio
async def test_github_valid_signature_passes():
    secret = "s3cr3t"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    result = await verify_webhook_signature(
        "github", {"webhook_secret": secret}, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_github_invalid_signature_fails():
    headers = {"X-Hub-Signature-256": "sha256=deadbeef"}
    result = await verify_webhook_signature(
        "github",
        {"webhook_secret": "s3cr3t"},
        {},
        headers,
        BODY,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )
    assert result is False


@pytest.mark.asyncio
async def test_github_tampered_body_fails():
    secret = "s3cr3t"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    tampered = BODY + b"x"
    result = await verify_webhook_signature(
        "github",
        {"webhook_secret": secret},
        {},
        headers,
        tampered,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )
    assert result is False


@pytest.mark.asyncio
async def test_secret_configured_but_no_raw_body_fails_closed():
    # Can't verify without the exact bytes -> reject, never silently accept.
    result = await verify_webhook_signature(
        "github",
        {"webhook_secret": "s3cr3t"},
        {},
        {"X-Hub-Signature-256": "x"},
        None,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )
    assert result is False


@pytest.mark.asyncio
async def test_secret_resolved_from_webhook_config_fallback():
    secret = "fromconfig"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    # validation_rules empty, secret lives in webhook_config instead.
    result = await verify_webhook_signature(
        "github", {}, {"webhook_secret": secret}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_generic_hmac_with_custom_header():
    secret = "gen-secret"  # noqa: S105
    sig = hmac.new(secret.encode(), BODY, hashlib.sha256).hexdigest()
    rules = {"signing_secret": secret, "signature_header": "x-acme-signature"}
    headers = {"X-Acme-Signature": sig}
    result = await verify_webhook_signature(
        "generic", rules, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_generic_without_a_secret_still_skips_verification():
    # generic has no registered scheme and the catalog offers it with zero
    # credential fields: it is legitimately unsigned unless configured.
    result = await verify_webhook_signature(
        "generic", {}, {}, {}, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is None


@pytest.mark.asyncio
async def test_telegram_has_no_signature_scheme_in_this_framework():
    # Telegram validates via its own secret_token header, handled elsewhere;
    # it carries no entry in SIGNING_SECRET_KEYS or VERIFIER_REGISTRY.
    result = await verify_webhook_signature(
        "telegram", {}, {}, {}, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is None


@pytest.mark.asyncio
async def test_resolve_signing_secret_unknown_type_returns_none():
    result = await resolve_signing_secret(
        "telegram", {"signing_secret": "x"}, {}, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is None


def _stripe_sig_header(secret: str, body: bytes, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


@pytest.mark.asyncio
async def test_stripe_valid_signature_passes():
    secret = "whsec_test"  # noqa: S105
    ts = int(time.time())
    headers = {"Stripe-Signature": _stripe_sig_header(secret, BODY, ts)}
    result = await verify_webhook_signature(
        "stripe", {"signing_secret": secret}, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_stripe_invalid_signature_fails():
    ts = int(time.time())
    headers = {"Stripe-Signature": f"t={ts},v1=deadbeef"}
    result = await verify_webhook_signature(
        "stripe",
        {"signing_secret": "whsec_test"},
        {},
        headers,
        BODY,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )
    assert result is False


@pytest.mark.asyncio
async def test_stripe_stale_timestamp_fails():
    secret = "whsec_test"  # noqa: S105
    ts = int(time.time()) - 3600
    headers = {"Stripe-Signature": _stripe_sig_header(secret, BODY, ts)}
    result = await verify_webhook_signature(
        "stripe", {"signing_secret": secret}, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is False


@pytest.mark.asyncio
async def test_stripe_missing_header_fails():
    result = await verify_webhook_signature(
        "stripe",
        {"signing_secret": "whsec_test"},
        {},
        {},
        BODY,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )
    assert result is False


# --- A configured secret must never be silently ignored --------------------
# A type with no dedicated verifier used to resolve to "not enabled", so a
# deployment could set a signing secret, see no error, and stay unprotected.


def _generic_sig(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_email_secret_is_actually_enforced():
    secret = "inbound-parse-secret"  # noqa: S105 — fixture credential
    headers = {"X-Webhook-Signature": _generic_sig(secret, BODY)}

    result = await verify_webhook_signature(
        "email", {"signing_secret": secret}, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )

    assert result is True


@pytest.mark.asyncio
async def test_email_bad_signature_is_rejected():
    result = await verify_webhook_signature(
        "email",
        {"signing_secret": "inbound-parse-secret"},
        {},
        {"X-Webhook-Signature": "nope"},
        BODY,
        _EMPTY_READER,
        _UNUSED_TRIGGER_ID,
    )

    assert result is False


@pytest.mark.asyncio
async def test_email_signature_header_and_prefix_are_configurable():
    """Providers sign with different header names; that is configuration."""
    secret = "inbound-parse-secret"  # noqa: S105 — fixture credential
    rules = {
        "signing_secret": secret,
        "signature_header": "x-provider-signature",
        "signature_prefix": "sha256=",
    }
    headers = {"X-Provider-Signature": "sha256=" + _generic_sig(secret, BODY)}

    result = await verify_webhook_signature(
        "email", rules, {}, headers, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is True


@pytest.mark.asyncio
async def test_email_without_a_secret_still_skips_verification():
    # email has no registered scheme (generic HMAC fallback only), so it too
    # is legitimately unsigned unless configured.
    result = await verify_webhook_signature(
        "email", {}, {}, {}, BODY, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result is None


@pytest.mark.asyncio
async def test_email_signing_secret_resolves():
    result = await resolve_signing_secret(
        "email", {"signing_secret": "x"}, {}, _EMPTY_READER, _UNUSED_TRIGGER_ID
    )
    assert result == "x"


# --- Secrets configured the way the UI stores them (secret store) ----------
# The trigger create/update endpoints write channel credentials as a JSON
# blob under `channel_cred:{webhook_type}:{trigger_id}`. The resolver must
# read that same key, not just validation_rules/webhook_config.


@pytest.mark.asyncio
async def test_secret_store_bad_signature_rejected():
    secret = "store-secret"  # noqa: S105
    trigger_id = uuid4()
    reader = _FakeSecretReader(
        {
            channel_credential_secret_name("github", trigger_id): json.dumps(
                {"webhook_secret": secret}
            )
        }
    )
    headers = {"X-Hub-Signature-256": "sha256=deadbeef"}

    result = await verify_webhook_signature(
        "github", {}, {}, headers, BODY, secret_reader=reader, trigger_id=trigger_id
    )

    assert result is False


@pytest.mark.asyncio
async def test_secret_store_good_signature_accepted():
    secret = "store-secret"  # noqa: S105
    trigger_id = uuid4()
    reader = _FakeSecretReader(
        {
            channel_credential_secret_name("github", trigger_id): json.dumps(
                {"webhook_secret": secret}
            )
        }
    )
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}

    result = await verify_webhook_signature(
        "github", {}, {}, headers, BODY, secret_reader=reader, trigger_id=trigger_id
    )

    assert result is True


@pytest.mark.asyncio
async def test_signed_type_with_no_resolvable_secret_in_store_is_rejected():
    trigger_id = uuid4()
    reader = _FakeSecretReader({})  # nothing stored for this trigger at all

    result = await verify_webhook_signature(
        "slack",
        {},
        {},
        {"x-slack-signature": "v0=x", "x-slack-request-timestamp": str(int(time.time()))},
        BODY,
        secret_reader=reader,
        trigger_id=trigger_id,
    )

    assert result is False


@pytest.mark.asyncio
async def test_resolve_signing_secret_reads_secret_store():
    secret = "abc123"  # noqa: S105
    trigger_id = uuid4()
    reader = _FakeSecretReader(
        {
            channel_credential_secret_name("slack", trigger_id): json.dumps(
                {"signing_secret": secret}
            )
        }
    )

    result = await resolve_signing_secret("slack", {}, {}, reader, trigger_id)

    assert result == secret


@pytest.mark.asyncio
async def test_resolve_signing_secret_ignores_other_triggers_credentials():
    trigger_id = uuid4()
    other_trigger_id = uuid4()
    reader = _FakeSecretReader(
        {
            channel_credential_secret_name("slack", other_trigger_id): json.dumps(
                {"signing_secret": "not-this-one"}
            )
        }
    )

    result = await resolve_signing_secret("slack", {}, {}, reader, trigger_id)

    assert result is None
