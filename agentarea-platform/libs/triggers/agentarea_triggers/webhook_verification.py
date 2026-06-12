"""Webhook signature verification framework.

Provides pluggable signature verification for incoming webhook requests.
Each channel type has its own verification strategy.
"""

import hashlib
import hmac
import logging
import time
from abc import ABC, abstractmethod

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
                logger.warning("Invalid Slack timestamp format")
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
            logger.error(f"Slack signature verification error: {e}")
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
            logger.error(f"GitHub signature verification error: {e}")
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
            logger.error(
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
            logger.warning("Discord signature verification failed")
            return False
        except Exception as e:
            logger.error(f"Discord signature verification error: {e}")
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
            logger.error(f"Generic HMAC verification error: {e}")
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
            logger.error(f"Linear signature verification error: {e}")
            return False

    def get_required_headers(self) -> list[str]:
        return ["linear-signature"]


# Registry mapping WebhookType to its signature verifier
VERIFIER_REGISTRY: dict[str, type[SignatureVerifier]] = {
    "slack": SlackSignatureVerifier,
    "github": GitHubSignatureVerifier,
    "discord": DiscordSignatureVerifier,
    "linear": LinearSignatureVerifier,
    # telegram uses bot token validation at a different level
    # stripe has its own SDK for verification
    # generic uses configurable HMAC
}

# Credential key names used for each channel's signing secret
SIGNING_SECRET_KEYS: dict[str, str] = {
    "slack": "signing_secret",
    "github": "webhook_secret",
    "discord": "public_key",
    "linear": "signing_secret",
    "generic": "signing_secret",
}


def get_verifier(webhook_type: str) -> SignatureVerifier | None:
    """Get the appropriate signature verifier for a webhook type.

    Returns None if no verifier is registered for the type.
    """
    verifier_cls = VERIFIER_REGISTRY.get(webhook_type)
    if verifier_cls:
        return verifier_cls()
    return None


def resolve_signing_secret(
    webhook_type: str,
    validation_rules: dict | None,
    webhook_config: dict | None,
) -> str | None:
    """Resolve the configured signing secret for a webhook type.

    Looks up the type's secret key (e.g. ``signing_secret`` / ``webhook_secret``)
    in ``validation_rules`` first, then ``webhook_config``. Returns None when no
    secret is configured (signature verification not enabled for this trigger).
    """
    key = SIGNING_SECRET_KEYS.get(webhook_type)
    if not key:
        return None
    for source in (validation_rules, webhook_config):
        if source:
            value = source.get(key)
            if value:
                return str(value)
    return None


def verify_webhook_signature(
    webhook_type: str | None,
    validation_rules: dict | None,
    webhook_config: dict | None,
    headers: dict[str, str],
    body: bytes | str | None,
) -> bool | None:
    """Verify an incoming webhook's signature against the configured secret.

    Returns:
        True  -- a signing secret is configured and the signature is valid.
        False -- a signing secret is configured but verification failed
                 (bad signature, missing headers, or no raw body to verify).
        None  -- no signing secret configured / no verifier for this type:
                 signature verification is not enabled, caller may proceed.

    The signature MUST be computed over the exact raw request body. Callers
    must pass the unparsed bytes, never a re-serialized dict.
    """
    wt = (webhook_type or "generic").lower()
    secret = resolve_signing_secret(wt, validation_rules, webhook_config)
    if not secret:
        return None

    if body is None:
        logger.warning(
            "Signing secret configured for webhook_type=%s but no raw body to verify", wt
        )
        return False

    if wt == "generic":
        rules = validation_rules or {}
        verifier: SignatureVerifier = GenericHMACVerifier(
            header_name=rules.get("signature_header", "x-webhook-signature"),
            algorithm=rules.get("signature_algorithm", "sha256"),
            prefix=rules.get("signature_prefix", ""),
        )
    else:
        resolved = get_verifier(wt)
        if resolved is None:
            return None
        verifier = resolved

    headers_lower = {k.lower(): v for k, v in headers.items()}
    return verifier.verify(headers_lower, body, secret)
