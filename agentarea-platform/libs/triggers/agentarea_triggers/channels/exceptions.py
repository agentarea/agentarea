"""Typed errors raised by `ChannelAdapter.send`.

The delivery consumer uses these to choose its action: `RetryableError`
means leave the message un-ACKed so the broker redelivers after the PEL
idle timeout; `FatalError` means ACK and move to the DLQ; anything else
unhandled is treated as `RetryableError` (we'd rather over-retry than
silently drop).

Adapters classify their own wire errors (5xx → retryable, 4xx → fatal,
429 → retryable with hint to honor Retry-After if present).
"""

from __future__ import annotations


class ChannelDeliveryError(Exception):
    """Base class for adapter delivery errors."""


class RetryableError(ChannelDeliveryError):
    """Transient failure — broker should redeliver after PEL idle timeout.

    `retry_after` is an optional hint (seconds) the consumer may use to
    decide whether to bump attempts or back off.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FatalError(ChannelDeliveryError):
    """Non-retryable failure — ACK and DLQ. Includes 4xx (auth, blocked,
    malformed) and adapter contract violations (unknown channel type)."""


class UnsupportedPayloadError(FatalError):
    """The adapter can't render this payload kind. DLQ immediately."""
