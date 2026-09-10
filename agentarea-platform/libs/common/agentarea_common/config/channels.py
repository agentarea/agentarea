"""Channel delivery configuration.

The outbound stream / consumer group / DLQ names are config — not module
globals — so deployments can rename them per environment (e.g. dev vs
prod, sharded streams, tenant-isolated DLQs) without touching code.
"""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .duration import Duration


class ChannelDeliverySettings(BaseSettings):
    """Configuration for durable channel pipelines."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_CHAN_", extra="ignore")

    IN_STREAM: str = Field(
        default="agentarea.channel.inbound",
        description="Broker stream that carries normalized inbound channel events.",
    )

    IN_GROUP: str = Field(
        default="inbound",
        description="Consumer group on IN_STREAM. All worker replicas share one group.",
    )

    IN_DLQ: str = Field(
        default="agentarea.channel.inbound.dlq",
        description="Stream that catches inbound events that exhausted retries or are malformed.",
    )

    OUT_STREAM: str = Field(
        default="agentarea.channel.outbound",
        description="Broker stream that carries pending outbound channel jobs.",
    )

    OUT_GROUP: str = Field(
        default="delivery",
        description="Consumer group on OUT_STREAM. All worker replicas share one group.",
    )

    OUT_DLQ: str = Field(
        default="agentarea.channel.outbound.dlq",
        description="Stream that catches messages that exhausted retries or hit a fatal error.",
    )

    AUTOCLAIM_IDLE: Duration = Field(
        default=timedelta(minutes=1),
        description=(
            "Pending-entry age at which the autoclaimer reclaims an entry "
            "from a (presumed-dead) consumer."
        ),
    )

    AUTOCLAIM_EVERY: Duration = Field(
        default=timedelta(seconds=30),
        description="How often the autoclaimer loop runs.",
    )

    DEDUP_TTL: Duration = Field(
        default=timedelta(days=1),
        description=(
            "TTL on the consumer-side dedup SET key. Long enough to outlast "
            "any plausible broker redelivery, short enough to bound the key set."
        ),
    )

    BLOCK: Duration = Field(
        default=timedelta(seconds=5),
        description="XREADGROUP block timeout per fetch.",
    )

    BATCH_SIZE: int = Field(
        default=10,
        description="Maximum entries claimed per XREADGROUP fetch.",
    )

    MAX_ATTEMPTS: int = Field(
        default=20,
        description=(
            "Cap on how many times the broker may redeliver a message before "
            "it gets dead-lettered. Bounds both transient-failure retry loops "
            "(adapter outage) and poison messages (always-throwing code) so a "
            "single bad message can't burn a consumer indefinitely."
        ),
    )
