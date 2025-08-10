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
    """Types of webhook integrations supported."""

    GENERIC = "generic"
    TELEGRAM = "telegram"
    SLACK = "slack"
    GITHUB = "github"
    DISCORD = "discord"
    STRIPE = "stripe"
