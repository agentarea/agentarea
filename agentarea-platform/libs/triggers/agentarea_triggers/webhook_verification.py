"""Webhook signature verification framework.

Provides pluggable signature verification for incoming webhook requests.
Each channel type has its own verification strategy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from .channels.secret_reader import SecretReader

logger = logging.getLogger(__name__)


class SignatureVerifier(ABC):
    """Abstract base class for webhook signature verification."""

    @abstractmethod
    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        """Verify the webhook signature.

        Args:
            headers: HTTP request headers (lowercase keys)
            body: Raw request body
            secret: The signing secret for this channel

        Returns:
            True if signature is valid, False otherwise
        """
        pass

    @abstractmethod
    def get_required_headers(self) -> list[str]:
        """Return list of headers required for verification."""
        pass


class SlackSignatureVerifier(SignatureVerifier):
    """Verify Slack webhook signatures using HMAC-SHA256.

    Slack signs requests with:
    - X-Slack-Signature: v0=<hex_digest>
    - X-Slack-Request-Timestamp: <unix_timestamp>

    The signature is computed as:
    HMAC-SHA256(signing_secret, "v0:{timestamp}:{body}")
    """

    TIMESTAMP_MAX_AGE_SECONDS = 300  # 5 minutes

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            signature = headers.get("x-slack-signature", "")
            timestamp = headers.get("x-slack-request-timestamp", "")

            if not signature or not timestamp:
                logger.warning("Missing Slack signature headers")
                return False

            # Check timestamp freshness to prevent replay attacks
            try:
                ts = int(timestamp)
                if abs(time.time() - ts) > self.TIMESTAMP_MAX_AGE_SECONDS:
                    logger.warning("Slack request timestamp too old")
                    return False
            except ValueError:
                logger.warning("Invalid Slack timestamp format", exc_info=True)
                return False

            # Compute expected signature
            body_str = body if isinstance(body, str) else body.decode("utf-8")
            sig_basestring = f"v0:{timestamp}:{body_str}"
            expected = (
                "v0="
                + hmac.new(
                    secret.encode("utf-8"),
                    sig_basestring.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
            )

            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.exception(f"Slack signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["x-slack-signature", "x-slack-request-timestamp"]


class GitHubSignatureVerifier(SignatureVerifier):
    """Verify GitHub webhook signatures using HMAC-SHA256.

    GitHub signs requests with:
    - X-Hub-Signature-256: sha256=<hex_digest>

    The signature is computed as:
    HMAC-SHA256(webhook_secret, body)
    """

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            signature = headers.get("x-hub-signature-256", "")

            if not signature:
                logger.warning("Missing GitHub signature header")
                return False

            body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
            expected = (
                "sha256="
                + hmac.new(
                    secret.encode("utf-8"),
                    body_bytes,
                    hashlib.sha256,
                ).hexdigest()
            )

            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.exception(f"GitHub signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["x-hub-signature-256"]


class DiscordSignatureVerifier(SignatureVerifier):
    """Verify Discord webhook signatures using Ed25519.

    Discord signs requests with:
    - X-Signature-Ed25519: <hex_signature>
    - X-Signature-Timestamp: <timestamp>

    The message to verify is: timestamp + body
    The public key is the Discord application's public key.
    """

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            from importlib import import_module

            bad_signature_error_cls = import_module("nacl.exceptions").BadSignatureError
            verify_key_cls = import_module("nacl.signing").VerifyKey
        except ImportError:
            logger.exception(
                "PyNaCl not installed, Discord signature verification will reject all requests. Install with: pip install PyNaCl"
            )
            return False

        try:
            signature = headers.get("x-signature-ed25519", "")
            timestamp = headers.get("x-signature-timestamp", "")

            if not signature or not timestamp:
                logger.warning("Missing Discord signature headers")
                return False

            body_str = body if isinstance(body, str) else body.decode("utf-8")
            message = f"{timestamp}{body_str}".encode()

            verify_key = verify_key_cls(bytes.fromhex(secret))
            verify_key.verify(message, bytes.fromhex(signature))
            return True
        except bad_signature_error_cls:
            logger.warning("Discord signature verification failed", exc_info=True)
            return False
        except Exception as e:
            logger.exception(f"Discord signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["x-signature-ed25519", "x-signature-timestamp"]


class GenericHMACVerifier(SignatureVerifier):
    """Generic HMAC signature verifier.

    Configurable header name and HMAC algorithm.
    Default: X-Webhook-Signature with SHA-256.
    """

    def __init__(
        self, header_name: str = "x-webhook-signature", algorithm: str = "sha256", prefix: str = ""
    ):
        self.header_name = header_name.lower()
        self.algorithm = algorithm
        self.prefix = prefix  # e.g., "sha256=" for some providers

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            signature = headers.get(self.header_name, "")
            if not signature:
                logger.warning("Missing expected webhook signature header")
                return False

            body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")

            hash_func = getattr(hashlib, self.algorithm, None)
            if not hash_func:
                logger.error("Unsupported webhook hash algorithm configured")
                return False

            expected = (
                self.prefix
                + hmac.new(
                    secret.encode("utf-8"),
                    body_bytes,
                    hash_func,
                ).hexdigest()
            )

            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.exception(f"Generic HMAC verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return [self.header_name]


class LinearSignatureVerifier(SignatureVerifier):
    """Verify Linear webhook signatures using HMAC-SHA256.

    Linear uses the same pattern as GitHub:
    - Linear-Signature header (or custom configured header)
    """

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            signature = headers.get("linear-signature", "")
            if not signature:
                logger.warning("Missing Linear signature header")
                return False

            body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
            expected = hmac.new(
                secret.encode("utf-8"),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.exception(f"Linear signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["linear-signature"]


class StripeSignatureVerifier(SignatureVerifier):
    """Verify Stripe webhook signatures using HMAC-SHA256.

    Stripe signs requests with:
    - Stripe-Signature: t=<unix_timestamp>,v1=<hex_digest>[,v1=<hex_digest>...]

    The signature is computed as:
    HMAC-SHA256(signing_secret, "{timestamp}.{body}")
    """

    TIMESTAMP_MAX_AGE_SECONDS = 300  # Stripe's recommended tolerance

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        try:
            header = headers.get("stripe-signature", "")
            if not header:
                logger.warning("Missing Stripe signature header")
                return False

            timestamp = ""
            candidates: list[str] = []
            for element in header.split(","):
                key, _, value = element.strip().partition("=")
                if key == "t":
                    timestamp = value
                elif key == "v1":
                    candidates.append(value)

            if not timestamp or not candidates:
                logger.warning("Malformed Stripe signature header")
                return False

            try:
                ts = int(timestamp)
                if abs(time.time() - ts) > self.TIMESTAMP_MAX_AGE_SECONDS:
                    logger.warning("Stripe request timestamp too old")
                    return False
            except ValueError:
                logger.warning("Invalid Stripe timestamp format", exc_info=True)
                return False

            body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
            expected = hmac.new(
                secret.encode("utf-8"),
                f"{timestamp}.".encode() + body_bytes,
                hashlib.sha256,
            ).hexdigest()

            return any(hmac.compare_digest(expected, sig) for sig in candidates)
        except Exception as e:
            logger.exception(f"Stripe signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["stripe-signature"]


class TelegramSecretTokenVerifier(SignatureVerifier):
    """Telegram echoes the ``secret_token`` given to ``setWebhook`` in a header.

    Telegram does not sign the body; the token it repeats on every update is
    the only proof a request came from Telegram for this bot.
    """

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        token = headers.get("x-telegram-bot-api-secret-token", "")
        if not token:
            logger.warning("Missing Telegram secret token header")
            return False
        return hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))

    def get_required_headers(self) -> list[str]:
        return ["x-telegram-bot-api-secret-token"]


class SentrySignatureVerifier(SignatureVerifier):
    """Sentry signs with ``Sentry-Hook-Signature: hex(HMAC-SHA256(client_secret, body))``."""

    def verify(self, headers: dict[str, str], body: bytes | str, secret: str) -> bool:
        signature = headers.get("sentry-hook-signature", "")
        if not signature:
            logger.warning("Missing Sentry signature header")
            return False
        body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def get_required_headers(self) -> list[str]:
        return ["sentry-hook-signature"]


YOOKASSA_API_URL = "https://api.yookassa.ru/v3"
_YOOKASSA_COLLECTIONS = {
    "payment": "payments",
    "refund": "refunds",
    "payout": "payouts",
    "deal": "deals",
    "payment_method": "payment_methods",
}
_YOOKASSA_OBJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class YooKassaNotificationVerifier:
    """YooKassa does not sign notifications, so the notified object is read back.

    ``{"event": "payment.succeeded", "object": {"id": ...}}`` is believed only
    when ``GET /payments/{id}`` with the shop's own key answers that object in
    status ``succeeded``. Anyone can post to the URL; only YooKassa holds the
    object in that state.
    """

    TIMEOUT_SECONDS = 10.0

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def verify(self, body: bytes | str, shop_id: str, secret_key: str) -> bool:
        try:
            notification = json.loads(body)
        except ValueError:
            logger.warning("YooKassa notification is not JSON", exc_info=True)
            return False
        if not isinstance(notification, dict) or not isinstance(notification.get("object"), dict):
            logger.warning("YooKassa notification carries no object")
            return False
        resource, _, status = str(notification.get("event") or "").partition(".")
        collection = _YOOKASSA_COLLECTIONS.get(resource)
        object_id = str(notification["object"].get("id") or "")
        if not collection or not status or not _YOOKASSA_OBJECT_ID.fullmatch(object_id):
            logger.warning(
                "YooKassa notification event=%r cannot be checked against the API",
                notification.get("event"),
            )
            return False
        try:
            async with httpx.AsyncClient(
                base_url=YOOKASSA_API_URL,
                auth=(shop_id, secret_key),
                timeout=self.TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = await client.get(f"/{collection}/{object_id}")
        except httpx.HTTPError:
            logger.warning(
                "YooKassa API unreachable while checking %s %s", resource, object_id, exc_info=True
            )
            return False
        if response.status_code != 200:
            logger.warning(
                "YooKassa API answered %s for %s %s", response.status_code, resource, object_id
            )
            return False
        try:
            fetched = response.json()
        except ValueError:
            logger.warning("YooKassa API answered a body that is not JSON", exc_info=True)
            return False
        return (
            isinstance(fetched, dict)
            and fetched.get("id") == object_id
            and fetched.get("status") == status
        )


def yookassa_verifier() -> YooKassaNotificationVerifier:
    return YooKassaNotificationVerifier()


# Registry mapping WebhookType to its signature verifier
VERIFIER_REGISTRY: dict[str, type[SignatureVerifier]] = {
    "slack": SlackSignatureVerifier,
    "github": GitHubSignatureVerifier,
    "discord": DiscordSignatureVerifier,
    "linear": LinearSignatureVerifier,
    "stripe": StripeSignatureVerifier,
    "telegram": TelegramSecretTokenVerifier,
    "sentry": SentrySignatureVerifier,
    # generic uses configurable HMAC
}

#: Types verified by reading the notified object back from the provider's API.
FETCH_VERIFIED_TYPES: frozenset[str] = frozenset({"yookassa"})

#: Types refused outright while no secret resolves.
SECRET_REQUIRED_TYPES: frozenset[str] = frozenset(VERIFIER_REGISTRY) | FETCH_VERIFIED_TYPES

#: Types whose triggers created before verification existed carry no secret.
#: They keep being accepted (with a warning) instead of going dark on upgrade;
#: every trigger created or re-registered now has one and is verified.
LEGACY_UNSIGNED_TYPES: frozenset[str] = frozenset({"telegram"})

# Credential key names used for each channel's signing secret
SIGNING_SECRET_KEYS: dict[str, str] = {
    "slack": "signing_secret",
    "github": "webhook_secret",
    "discord": "public_key",
    "linear": "signing_secret",
    "stripe": "signing_secret",
    "generic": "signing_secret",
    "email": "signing_secret",
    "telegram": "secret_token",
    "sentry": "client_secret",
    "yookassa": "secret_key",
}


#: Keys of a trigger's ``validation_rules`` / ``webhook_config`` whose values are
#: credentials: every signing key above, plus the channel credentials a member
#: may have put inline (``credential_fields`` in the trigger catalog). They are
#: write-only: responses carry ``REDACTED_SECRET`` in their place, and an update
#: that omits them or sends that placeholder back keeps the stored value.
SECRET_CONFIG_FIELDS: frozenset[str] = frozenset(
    {*SIGNING_SECRET_KEYS.values(), "bot_token", "password"}
)
REDACTED_SECRET = "********"  # noqa: S105


def redact_secret_fields(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy of ``config`` with every configured credential value masked."""
    if not config:
        return config
    return {
        key: REDACTED_SECRET if key in SECRET_CONFIG_FIELDS and value else value
        for key, value in config.items()
    }


def keep_stored_secret_fields(
    sent: dict[str, Any], stored: dict[str, Any] | None
) -> dict[str, Any]:
    """``sent`` with each credential it omits, or echoes masked, taken from ``stored``.

    A credential sent as a real value replaces the stored one; sent as null or
    empty it is cleared. The mask sent for a credential that has no stored value
    raises ``ValueError``: it stands for a value, and there is none to keep.
    """
    merged = dict(sent)
    stored_keys = (stored or {}).keys()
    for key in SECRET_CONFIG_FIELDS & merged.keys():
        if merged[key] == REDACTED_SECRET and key not in stored_keys:
            raise ValueError(f"{key} has no stored value to keep; send the value itself")
    for key in SECRET_CONFIG_FIELDS & stored_keys:
        if key not in merged or merged[key] == REDACTED_SECRET:
            merged[key] = (stored or {})[key]
    return merged


class SigningSecretUnavailableError(Exception):
    """A trigger's stored channel credentials exist but could not be read.

    Distinct from "no secret configured": that one means verification is not
    enabled, this one means it is and the secret cannot be checked against, so
    the request must be refused rather than waved through unsigned.
    """


@dataclass(frozen=True)
class GenericSignatureScheme:
    """How a sender signs a generic webhook: ``header: prefix + hex(HMAC(secret, raw body))``."""

    header: str
    algorithm: str
    prefix: str


def generic_signature_scheme(validation_rules: dict | None) -> GenericSignatureScheme:
    """The HMAC scheme a generic webhook is verified with.

    Header name, digest and prefix are configurable through ``validation_rules``
    because providers that share plain HMAC still disagree on all three; this
    is the one place the defaults live, for the verifier and for the docs the
    UI shows next to the secret.
    """
    rules = validation_rules or {}
    return GenericSignatureScheme(
        header=rules.get("signature_header", "X-Webhook-Signature"),
        algorithm=rules.get("signature_algorithm", "sha256"),
        prefix=rules.get("signature_prefix", ""),
    )


def hmac_signature_scheme(
    webhook_type: str, validation_rules: dict | None
) -> GenericSignatureScheme | None:
    """The configurable HMAC scheme ``webhook_type`` is verified with; None if it has its own."""
    wt = webhook_type.lower()
    if wt not in SIGNING_SECRET_KEYS or wt in VERIFIER_REGISTRY or wt in FETCH_VERIFIED_TYPES:
        return None
    return generic_signature_scheme(validation_rules)


def get_verifier(webhook_type: str) -> SignatureVerifier | None:
    """Get the appropriate signature verifier for a webhook type.

    Returns None if no verifier is registered for the type.
    """
    verifier_cls = VERIFIER_REGISTRY.get(webhook_type)
    if verifier_cls:
        return verifier_cls()
    return None


def channel_credential_secret_name(channel_type: str, trigger_id: Any) -> str:
    """Secret-store key holding a trigger's channel credentials.

    This is the one place that knows the format
    (``channel_cred:{channel_type}:{trigger_id}``); the trigger create/update
    endpoints (the writer) and this module's secret resolution (the reader)
    both call it, so the two can never drift apart.
    """
    return f"channel_cred:{channel_type}:{trigger_id}"


async def resolve_signing_secret(
    webhook_type: str,
    validation_rules: dict | None,
    webhook_config: dict | None,
    secret_reader: SecretReader,
    trigger_id: Any,
) -> str | None:
    """Resolve the configured signing secret for a webhook type.

    Looks up the type's secret key (e.g. ``signing_secret`` / ``webhook_secret``)
    in ``validation_rules`` first, then ``webhook_config``, then the secret
    store, under the same ``channel_cred:{type}:{trigger_id}`` key the trigger
    create/update endpoints write channel credentials to (see
    ``channel_credential_secret_name``). That entry is a JSON object of
    credential fields; only the signing key is read out of it.

    ``secret_reader`` is required, not optional: a security dependency that
    could silently be omitted is how the store went unread in the first
    place. Callers with nothing real to pass (tests) must construct a fake
    reader explicitly. Returns None when no secret is configured anywhere
    (signature verification not enabled for this trigger).

    Raises ``SigningSecretUnavailableError`` when the store cannot answer or
    holds something that is not a credentials object: that is not "no secret",
    and treating it as one would accept unsigned requests whenever the secret
    backend is degraded.
    """
    key = SIGNING_SECRET_KEYS.get(webhook_type)
    if not key:
        return None
    for source in (validation_rules, webhook_config):
        if source:
            value = source.get(key)
            if value:
                return str(value)

    secret_name = channel_credential_secret_name(webhook_type, trigger_id)
    try:
        raw = await secret_reader.get_secret(secret_name)
    except Exception:
        # Log only non-sensitive lookup facts: never the secret name (it
        # embeds the trigger id, but is also the exact string handed to the
        # secret backend) or anything derived from the credential itself.
        logger.exception(
            "Failed to read channel credentials for webhook_type=%s trigger_id=%s",
            webhook_type,
            trigger_id,
        )
        raise SigningSecretUnavailableError(webhook_type) from None
    if not raw:
        return None
    try:
        credentials = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Stored channel credentials for webhook_type=%s trigger_id=%s are not valid JSON",
            webhook_type,
            trigger_id,
            exc_info=True,
        )
        raise SigningSecretUnavailableError(webhook_type) from None
    if not isinstance(credentials, dict):
        logger.warning(
            "Stored channel credentials for webhook_type=%s trigger_id=%s are not an object",
            webhook_type,
            trigger_id,
        )
        raise SigningSecretUnavailableError(webhook_type)
    value = credentials.get(key)
    if isinstance(value, dict):
        return await _referenced_secret(value, webhook_type, secret_reader, trigger_id)
    return str(value) if value else None


async def _referenced_secret(
    reference: dict[str, Any], webhook_type: str, secret_reader: SecretReader, owner_id: Any
) -> str:
    """The value of the workspace secret a credential names instead of holding.

    The platform writes ``{"secret_name": ...}`` here when a member picked a
    workspace secret; the value stays in that secret and is read at use. A
    reference that no longer resolves is not "no secret": the owner chose one.
    """
    name = reference.get("secret_name")
    if not isinstance(name, str) or not name:
        logger.warning(
            "Stored credential reference for webhook_type=%s owner=%s names no secret",
            webhook_type,
            owner_id,
        )
        raise SigningSecretUnavailableError(webhook_type)
    try:
        value = await secret_reader.get_secret(name)
    except Exception:
        logger.exception(
            "Failed to read the referenced secret for webhook_type=%s owner=%s",
            webhook_type,
            owner_id,
        )
        raise SigningSecretUnavailableError(webhook_type) from None
    if not value:
        logger.warning(
            "The secret referenced by webhook_type=%s owner=%s has no value",
            webhook_type,
            owner_id,
        )
        raise SigningSecretUnavailableError(webhook_type)
    return value


#: What stands between a trigger's public webhook URL and anyone who learns it.
#: ``signed`` -- every request must carry a valid signature or token (a type
#: with a registered scheme is refused outright while its secret is missing).
#: ``unsigned`` -- the type can be signed but this trigger has no secret, so
#: any request is accepted. ``unsupported`` -- the platform implements no
#: verification for this provider (Gmail Pub/Sub push, Teams Bot Framework);
#: any request is accepted and no setting changes that.
WebhookSigning = Literal["signed", "unsigned", "unsupported"]


async def webhook_signing_status(
    webhook_type: str | None,
    validation_rules: dict | None,
    webhook_config: dict | None,
    secret_reader: SecretReader,
    trigger_id: Any,
) -> WebhookSigning:
    """Whether ``verify_webhook_signature`` will demand proof for this trigger.

    Follows the same branches as the verifier, so the label shown to a person
    cannot drift from what the endpoint enforces. Raises
    ``SigningSecretUnavailableError`` like ``resolve_signing_secret``.
    """
    wt = (webhook_type or "generic").lower()
    if wt not in SIGNING_SECRET_KEYS:
        return "unsupported"
    if wt in SECRET_REQUIRED_TYPES and wt not in LEGACY_UNSIGNED_TYPES:
        return "signed"
    secret = await resolve_signing_secret(
        wt, validation_rules, webhook_config, secret_reader, trigger_id
    )
    return "signed" if secret else "unsigned"


async def verify_webhook_signature(
    webhook_type: str | None,
    validation_rules: dict | None,
    webhook_config: dict | None,
    headers: dict[str, str],
    body: bytes | str | None,
    secret_reader: SecretReader,
    trigger_id: Any,
) -> bool | None:
    """Verify an incoming webhook's signature against the configured secret.

    Returns:
        True  -- a signing secret is configured and the signature is valid.
        False -- a signing secret is configured but verification failed
                 (bad signature, missing headers, or no raw body to verify),
                 OR the webhook type has a registered signature scheme
                 (``SECRET_REQUIRED_TYPES``) and no secret resolves at all — such
                 a trigger is fail-closed rather than treated as unsigned —
                 OR the stored secret could not be read.
        None  -- no signing secret configured and no verification scheme is
                 expected for this type: signature verification is not
                 enabled, caller may proceed.

    ``secret_reader``/``trigger_id`` are required (see ``resolve_signing_secret``):
    there is no "no reader" branch here for the secret-store lookup to
    silently skip.

    The signature MUST be computed over the exact raw request body. Callers
    must pass the unparsed bytes, never a re-serialized dict.
    """
    wt = (webhook_type or "generic").lower()
    try:
        secret = await resolve_signing_secret(
            wt, validation_rules, webhook_config, secret_reader, trigger_id
        )
    except SigningSecretUnavailableError:
        logger.warning(
            "webhook_type=%s trigger_id=%s: signing secret could not be read; rejecting "
            "request (fail closed)",
            wt,
            trigger_id,
        )
        return False
    if not secret:
        if wt in LEGACY_UNSIGNED_TYPES:
            logger.warning(
                "webhook_type=%s trigger_id=%s has no secret token; accepting a legacy "
                "unsigned webhook. Re-save the trigger to register one.",
                wt,
                trigger_id,
            )
            return None
        if wt in SECRET_REQUIRED_TYPES:
            logger.warning(
                "webhook_type=%s has a registered signature scheme but no signing "
                "secret resolved; rejecting request (fail closed)",
                wt,
            )
            return False
        return None

    if body is None:
        logger.warning(
            "Signing secret configured for webhook_type=%s but no raw body to verify", wt
        )
        return False

    if wt in FETCH_VERIFIED_TYPES:
        shop_id = (validation_rules or {}).get("shop_id")
        if not shop_id:
            logger.warning("webhook_type=%s trigger_id=%s has no shop_id", wt, trigger_id)
            return False
        return await yookassa_verifier().verify(body, str(shop_id), secret)

    resolved = None if wt == "generic" else get_verifier(wt)
    if resolved is None:
        # No channel-specific scheme for this type. A secret was configured, so
        # verification is enabled and must actually run — skipping it here would
        # leave a deployment that believes it signed its webhooks unprotected.
        scheme = generic_signature_scheme(validation_rules)
        verifier: SignatureVerifier = GenericHMACVerifier(
            header_name=scheme.header, algorithm=scheme.algorithm, prefix=scheme.prefix
        )
    else:
        verifier = resolved

    headers_lower = {k.lower(): v for k, v in headers.items()}
    return verifier.verify(headers_lower, body, secret)
