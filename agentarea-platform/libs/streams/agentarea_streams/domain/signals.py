"""Webhook requests that report on a source rather than carry its events (an entry's ``signals``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .source_types import SourceTypeEntry
from .templates import TemplateContext, render


@dataclass(frozen=True)
class SourceSignal:
    signal: str
    key: str
    reason: str


def source_signal(
    entry: SourceTypeEntry, headers: dict[str, str], body: Any
) -> SourceSignal | None:
    """The signal this request is, or None when it is an event (or a handshake)."""
    context = TemplateContext(body=body, headers=headers)
    for signal in entry.signals:
        if render(signal.when, context) != signal.equals:
            continue
        key = render(signal.key, context)
        if not key:
            raise ValueError(f"the {signal.signal} signal of {entry.slug} renders no key")
        return SourceSignal(
            signal=signal.signal, key=key, reason=render(signal.reason, context) or ""
        )
    return None
