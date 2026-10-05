from enum import StrEnum


class StreamKind(StrEnum):
    CUSTOM = "custom"
    PLATFORM = "platform"
    PROCESSOR_OUTPUT = "processor_output"


class SourceKind(StrEnum):
    WEBHOOK = "webhook"


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
