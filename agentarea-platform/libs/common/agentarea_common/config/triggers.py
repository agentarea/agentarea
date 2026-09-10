"""Trigger system configuration settings.

The class used to carry 21 knobs. ``env_prefix="TRIGGER_"`` on fields already
named ``TRIGGER_*`` meant their real env names were ``TRIGGER_TRIGGER_*``, so
none of them could be set as documented — and 16 of the 21 were never read by
any code either. Only the five that something actually consumes remain.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TriggerSettings(BaseSettings):
    """Configuration settings for the trigger system."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_TRIG_", extra="ignore")

    WEBHOOK_RATE: int = Field(
        default=100, description="Maximum webhook requests per minute per webhook URL"
    )

    WEBHOOK_URL: str = Field(
        default="/v1/webhooks", description="Base URL path for webhook endpoints"
    )

    NAMESPACE: str = Field(
        default="default", description="Temporal namespace for trigger schedules"
    )

    QUEUE: str = Field(
        default="trigger-schedules", description="Temporal task queue for trigger schedules"
    )

    LLM_ENABLED: bool = Field(default=True, description="Enable LLM-based condition evaluation")
