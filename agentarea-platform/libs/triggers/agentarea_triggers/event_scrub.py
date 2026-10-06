"""What of an inbound event may reach the journal or an agent: no credentials.

A header or query parameter whose name says it carries a credential (or a
signature over one) is dropped. Webhook intake applies this before journaling;
the trigger paths that fire without a journal apply the same rule to the events
they carry before an agent sees them.
"""

from typing import Any

_SECRET_NAME_PARTS = (
    "auth",
    "cookie",
    "token",
    "secret",
    "password",
    "passwd",
    "signature",
    "api-key",
    "api_key",
    "apikey",
)
_SECRET_NAMES = frozenset({"key", "sig", "code"})


def is_secret_name(name: str) -> bool:
    lowered = str(name).lower()
    return lowered in _SECRET_NAMES or any(part in lowered for part in _SECRET_NAME_PARTS)


def without_secrets(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if not is_secret_name(k)}


def journal_data(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        **parsed,
        "headers": without_secrets(parsed.get("headers") or {}),
        "query_params": without_secrets(parsed.get("query_params") or {}),
    }


def scrub_carried_event(event: dict[str, Any]) -> dict[str, Any]:
    """The journal rule on an event that never went through the journal."""
    scrubbed = dict(event)
    for key in ("headers", "query_params"):
        if isinstance(scrubbed.get(key), dict):
            scrubbed[key] = without_secrets(scrubbed[key])
    return scrubbed
