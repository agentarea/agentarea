from enum import StrEnum


class StreamKind(StrEnum):
    CUSTOM = "custom"
    PLATFORM = "platform"
    PROCESSOR_OUTPUT = "processor_output"


class SourceKind(StrEnum):
    WEBHOOK = "webhook"
    POLL = "poll"


class SubscriptionKind(StrEnum):
    TRIGGER = "trigger"
    FORWARD = "forward"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"


class Verdict(StrEnum):
    REACTED = "reacted"
    SKIPPED = "skipped"
    ERROR = "error"


# The reason a reaction gets when the router dead-letters its event; a replay of
# the dead letter runs it again.
GAVE_UP_REASON = "gave up after the broker's delivery limit"
