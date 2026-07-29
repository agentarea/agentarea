"""Tests for webhook signature verification wiring (verify_webhook_signature)."""

import hashlib
import hmac
import time

from agentarea_triggers.webhook_verification import (
    resolve_signing_secret,
    verify_webhook_signature,
)

BODY = b'{"event":"push","ref":"refs/heads/main"}'


def _github_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_no_secret_configured_returns_none_skip():
    # No signing secret => verification not enabled => caller proceeds.
    result = verify_webhook_signature("github", {}, {}, {}, BODY)
    assert result is None


def test_github_valid_signature_passes():
    secret = "s3cr3t"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    result = verify_webhook_signature(
        "github", {"webhook_secret": secret}, {}, headers, BODY
    )
    assert result is True


def test_github_invalid_signature_fails():
    headers = {"X-Hub-Signature-256": "sha256=deadbeef"}
    result = verify_webhook_signature(
        "github", {"webhook_secret": "s3cr3t"}, {}, headers, BODY
    )
    assert result is False


def test_github_tampered_body_fails():
    secret = "s3cr3t"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    tampered = BODY + b"x"
    result = verify_webhook_signature(
        "github", {"webhook_secret": secret}, {}, headers, tampered
    )
    assert result is False


def test_secret_configured_but_no_raw_body_fails_closed():
    # Can't verify without the exact bytes -> reject, never silently accept.
    result = verify_webhook_signature(
        "github", {"webhook_secret": "s3cr3t"}, {}, {"X-Hub-Signature-256": "x"}, None
    )
    assert result is False


def test_secret_resolved_from_webhook_config_fallback():
    secret = "fromconfig"  # noqa: S105
    headers = {"X-Hub-Signature-256": _github_sig(secret, BODY)}
    # validation_rules empty, secret lives in webhook_config instead.
    result = verify_webhook_signature(
        "github", {}, {"webhook_secret": secret}, headers, BODY
    )
    assert result is True


def test_generic_hmac_with_custom_header():
    secret = "gen-secret"  # noqa: S105
    sig = hmac.new(secret.encode(), BODY, hashlib.sha256).hexdigest()
    rules = {"signing_secret": secret, "signature_header": "x-acme-signature"}
    headers = {"X-Acme-Signature": sig}
    result = verify_webhook_signature("generic", rules, {}, headers, BODY)
    assert result is True


def test_resolve_signing_secret_unknown_type_returns_none():
    assert resolve_signing_secret("telegram", {"signing_secret": "x"}, {}) is None


def _stripe_sig_header(secret: str, body: bytes, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


def test_stripe_valid_signature_passes():
    secret = "whsec_test"  # noqa: S105
    ts = int(time.time())
    headers = {"Stripe-Signature": _stripe_sig_header(secret, BODY, ts)}
    result = verify_webhook_signature(
        "stripe", {"signing_secret": secret}, {}, headers, BODY
    )
    assert result is True


def test_stripe_invalid_signature_fails():
    ts = int(time.time())
    headers = {"Stripe-Signature": f"t={ts},v1=deadbeef"}
    result = verify_webhook_signature(
        "stripe", {"signing_secret": "whsec_test"}, {}, headers, BODY
    )
    assert result is False


def test_stripe_stale_timestamp_fails():
    secret = "whsec_test"  # noqa: S105
    ts = int(time.time()) - 3600
    headers = {"Stripe-Signature": _stripe_sig_header(secret, BODY, ts)}
    result = verify_webhook_signature(
        "stripe", {"signing_secret": secret}, {}, headers, BODY
    )
    assert result is False


def test_stripe_missing_header_fails():
    result = verify_webhook_signature(
        "stripe", {"signing_secret": "whsec_test"}, {}, {}, BODY
    )
    assert result is False
