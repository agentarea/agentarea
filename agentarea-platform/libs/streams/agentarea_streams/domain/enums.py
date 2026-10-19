from enum import StrEnum


class StreamKind(StrEnum):
    CUSTOM = "custom"
    PLATFORM = "platform"
    PROCESSOR_OUTPUT = "processor_output"


class SourceKind(StrEnum):
    WEBHOOK = "webhook"
    POLL = "poll"
    #: The platform group writing task outcomes; no member creates or removes one.
    PLATFORM = "platform"


class SubscriptionKind(StrEnum):
    TRIGGER = "trigger"
    FORWARD = "forward"
    #: A subscriber outside the platform, over MCP Events webhook delivery.
    EXTERNAL = "external"
    #: Code an agent wrote, run in the sandbox over each event; writes to its output streams.
    PROCESSOR = "processor"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"


class Verdict(StrEnum):
    REACTED = "reacted"
    SKIPPED = "skipped"
    ERROR = "error"
    #: Held in an open batch of a windowed trigger; the batch's firing settles it.
    BATCHED = "batched"


# The reason a reaction gets when the router dead-letters its event; a replay of
# the dead letter runs it again.
GAVE_UP_REASON = "gave up after the broker's delivery limit"

# A subscription starts at the end of its stream (ADR-0040 §1): an event received
# before it started, redelivered or replayed later, is skipped with this reason.
BEFORE_START_REASON = "received before the subscription started"
