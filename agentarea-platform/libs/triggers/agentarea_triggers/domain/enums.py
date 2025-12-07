"""Trigger system enums and value objects."""

from enum import Enum


class TriggerType(str, Enum):
    """Types of triggers supported by the system."""

    CRON = "cron"
    WEBHOOK = "webhook"


class TriggerStatus(str, Enum):
    """Status of a trigger."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"
    FAILED = "failed"


class ExecutionStatus(str, Enum):
    """Status of a trigger execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class WebhookType(str, Enum):
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
    
    @classmethod
    def _missing_(cls, value):
        """Allow any string value for WebhookType to support dynamic configuration."""
        # This is a bit of a hack to allow Pydantic to accept any string
        # while still having an Enum for known constants.
        # Ideally we should switch models to use str instead of WebhookType,
        # but this maintains backward compatibility for now.
        return value

