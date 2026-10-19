"""The five ways a webhook request proves where it came from, driven by the catalog entry.

``hmac``: a header carries HMAC(secret, body). ``hmac_timestamped``: HMAC over a
text built from a timestamp, a delivery id and the body, with a replay window
(Stripe, Slack, Standard Webhooks). ``ed25519``: a signature by the provider's
key over timestamp and body. ``shared_token``: the provider repeats a token it
was given. ``api_lookup``: the notified object is read back from the provider's
API with the member's key. No scheme knows a provider; the entry says which
headers, texts and keys apply.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .source_types import Verification
from .templates import TemplateContext, render, render_value

logger = logging.getLogger(__name__)

#: Reads the provider's API for ``api_lookup``: (method, url, auth) -> (status, json).
ApiLookup = Callable[[str, str, tuple[str, str] | None], Awaitable[tuple[int, Any]]]


class VerificationError(ValueError):
    """The request does not prove where it came from."""


def _header(headers: Mapping[str, str], name: str | None) -> str:
    if not name:
        raise VerificationError("the entry names no header to verify")
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    raise VerificationError(f"missing header {name}")


def _secret_bytes(secret: str, scheme: Verification) -> bytes:
    if scheme.secret_format == "whsec":  # noqa: S105 - a format name, not a secret
        try:
            return base64.b64decode(secret.removeprefix("whsec_"))
        except (binascii.Error, ValueError) as error:
            raise VerificationError("the stored secret is not whsec_<base64>") from error
    return secret.encode("utf-8")


def _digest(scheme: Verification, key: bytes, payload: bytes) -> str:
    raw = hmac.new(key, payload, getattr(hashlib, scheme.algorithm)).digest()
    return raw.hex() if scheme.encoding == "hex" else base64.b64encode(raw).decode()


def _fresh(timestamp: str, tolerance: int) -> None:
    try:
        sent = int(timestamp)
    except ValueError as error:
        raise VerificationError(f"timestamp {timestamp!r} is not unix seconds") from error
    if abs(time.time() - sent) > tolerance:
        raise VerificationError("timestamp outside the replay window")


def verify_hmac(scheme: Verification, headers: Mapping[str, str], body: bytes, secret: str) -> None:
    signature = _header(headers, scheme.header)
    expected = scheme.prefix + _digest(scheme, _secret_bytes(secret, scheme), body)
    if not hmac.compare_digest(expected, signature.strip()):
        raise VerificationError("signature does not match")


def _signature_parts(scheme: Verification, value: str) -> tuple[str | None, list[str]]:
    """(timestamp from the header or None, candidate signatures) of a signature header."""
    if scheme.signature_format == "kv":
        timestamp: str | None = None
        candidates: list[str] = []
        for element in value.split(","):
            key, _, part = element.strip().partition("=")
            if key == scheme.timestamp_key:
                timestamp = part
            elif key == scheme.signature_key:
                candidates.append(part)
        return timestamp, candidates
    if scheme.signature_format == "list":
        return None, [
            part.partition(",")[2]
            for part in value.split()
            if part.partition(",")[0] == scheme.signature_key
        ]
    return None, [value.strip().removeprefix(scheme.prefix)]


def verify_hmac_timestamped(
    scheme: Verification, headers: Mapping[str, str], body: bytes, secret: str
) -> None:
    timestamp, candidates = _signature_parts(scheme, _header(headers, scheme.header))
    if timestamp is None:
        timestamp = _header(headers, scheme.timestamp_header)
    if not candidates:
        raise VerificationError("the signature header carries no signature")
    _fresh(timestamp, scheme.tolerance_seconds)
    delivery_id = _header(headers, scheme.id_header) if "{id}" in scheme.payload else ""
    payload = (
        scheme.payload.replace("{timestamp}", timestamp)
        .replace("{id}", delivery_id)
        .encode("utf-8")
    )
    signed = payload.replace(b"{body}", body)
    expected = _digest(scheme, _secret_bytes(secret, scheme), signed)
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise VerificationError("signature does not match")


def verify_ed25519(
    scheme: Verification, headers: Mapping[str, str], body: bytes, public_key: str
) -> None:
    signature = _header(headers, scheme.header)
    timestamp = _header(headers, scheme.timestamp_header) if scheme.timestamp_header else ""
    payload = scheme.payload.replace("{timestamp}", timestamp).encode("utf-8")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            bytes.fromhex(signature), payload.replace(b"{body}", body)
        )
    except (InvalidSignature, ValueError) as error:
        raise VerificationError("signature does not match") from error


def verify_shared_token(scheme: Verification, headers: Mapping[str, str], secret: str) -> None:
    if not hmac.compare_digest(_header(headers, scheme.header).encode(), secret.encode()):
        raise VerificationError("token does not match")


async def verify_api_lookup(
    scheme: Verification,
    body: Any,
    *,
    credentials: Mapping[str, Any],
    config: Mapping[str, Any],
    lookup: ApiLookup,
) -> None:
    """Believe the notification only when the provider's API holds the object in that state."""
    if scheme.request is None:
        raise VerificationError("an api_lookup entry names no request")
    values: dict[str, Any] = {"credentials": credentials, "config": config}
    context = TemplateContext(body=body, values=values)
    if scheme.collection_from is not None:
        notified = render(scheme.collection_from, context) or ""
        collection = scheme.collections.get(notified.partition(".")[0])
        if collection is None:
            raise VerificationError(f"{notified!r} names no object the API can be asked about")
        values["collection"] = collection
    request = render_value(scheme.request, TemplateContext(body=body, values=values))
    url = request.get("url")
    if not isinstance(url, str):
        raise VerificationError("the lookup URL could not be filled in from this notification")
    auth = request.get("auth")
    basic = (str(auth["username"]), str(auth["password"])) if isinstance(auth, dict) else None
    status, fetched = await lookup(str(request.get("method") or "GET"), url, basic)
    if status != 200 or not isinstance(fetched, Mapping):
        raise VerificationError(f"the provider's API answered {status}")
    for field, template in scheme.expect.items():
        wanted = render(template, TemplateContext(body=body, values=values))
        current = fetched.get(field)
        if current == wanted:
            continue
        if wanted is not None and current in scheme.later.get(wanted, []):
            continue
        raise VerificationError(f"the API holds {field}={current!r}, not {wanted!r}")


def configured(scheme: Verification, config: Mapping[str, Any]) -> Verification:
    """The entry's scheme with the settings this source may override taken from its config.

    Raises ``pydantic.ValidationError`` for a value the scheme cannot take (an
    unknown digest), so a source is refused when it is saved, not on every delivery.
    """
    overrides = {
        key: config[key] for key in scheme.configurable if config.get(key) not in (None, "")
    }
    if not overrides:
        return scheme
    return Verification.model_validate({**scheme.model_dump(), **overrides})


async def verify_request(
    scheme: Verification,
    *,
    headers: Mapping[str, str],
    raw_body: bytes,
    body: Any,
    credentials: Mapping[str, Any],
    config: Mapping[str, Any],
    lookup: ApiLookup,
) -> None:
    """Raise ``VerificationError`` unless the request proves it came from the provider."""
    if scheme.scheme == "none":
        return
    if scheme.scheme == "api_lookup":
        await verify_api_lookup(scheme, body, credentials=credentials, config=config, lookup=lookup)
        return
    secret = credentials.get(scheme.secret) if scheme.secret else None
    if not isinstance(secret, str) or not secret:
        raise VerificationError(f"the source has no {scheme.secret or 'secret'} to verify with")
    if scheme.scheme == "hmac":
        verify_hmac(scheme, headers, raw_body, secret)
    elif scheme.scheme == "hmac_timestamped":
        verify_hmac_timestamped(scheme, headers, raw_body, secret)
    elif scheme.scheme == "ed25519":
        verify_ed25519(scheme, headers, raw_body, secret)
    else:
        verify_shared_token(scheme, headers, secret)
