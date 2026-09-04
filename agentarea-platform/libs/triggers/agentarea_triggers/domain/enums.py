"""Trigger system enums and value objects."""

from enum import StrEnum


class TriggerType(StrEnum):
    """Types of triggers supported by the system."""

    CRON = "cron"
    WEBHOOK = "webhook"
    POLLING = "polling"


class TriggerStatus(StrEnum):
    """Status of a trigger."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    """Status of a trigger execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class WebhookType(StrEnum):
    """Types of webhook integrations supported.

    This Enum provides constants for known types but the system supports
    dynamic types defined in configuration.
    """

    GENERIC = "generic"
    TELEGRAM = "telegram"
    SLACK = "slack"
    GITHUB = "github"
    DISCORD = "discord"
    LINEAR = "linear"
    STRIPE = "stripe"
    GMAIL = "gmail"
    TEAMS = "teams"

    @classmethod
    def _missing_(cls, value):
        """Accept any string, so a webhook type can be configured dynamically.

        The named constants above are the ones the platform knows about; anything
        else is passed through rather than rejected.

        This returns a pseudo-member instead of the raw string on purpose.
        ``_missing_`` is contractually required to return ``None`` or a member,
        and returning the value itself only appeared to work: CPython validates
        the return inside ``Enum.__contains__``, so ``"x" in WebhookType`` raises
        ``TypeError: error in WebhookType._missing_`` on 3.12.14 while passing on
        3.12.9. Since this is a StrEnum the pseudo-member still compares equal to
        the string and is still a ``str``, so callers see no difference.
        """
        if not isinstance(value, str):
            return None
        member = str.__new__(cls, value)
        member._name_ = value
        member._value_ = value
        return member
