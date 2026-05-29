"""Channel delivery configuration.

The outbound stream / consumer group / DLQ names are config — not module
globals — so deployments can rename them per environment (e.g. dev vs
prod, sharded streams, tenant-isolated DLQs) without touching code.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class ChannelDeliverySettings(BaseSettings):
    """Configuration for durable channel pipelines."""

    INBOUND_STREAM: str = Field(
        default="agentarea.channel.inbound",
        description="Broker stream that carries normalized inbound channel events.",
    )

    INBOUND_GROUP: str = Field(
        default="inbound",
        description="Consumer group on INBOUND_STREAM. All worker replicas share one group.",
    )

    INBOUND_DLQ: str = Field(
        default="agentarea.channel.inbound.dlq",
        description="Stream that catches inbound events that exhausted retries or are malformed.",
    )

    OUTBOUND_STREAM: str = Field(
        default="agentarea.channel.outbound",
        description="Broker stream that carries pending outbound channel jobs.",
    )

    OUTBOUND_GROUP: str = Field(
        default="delivery",
        description="Consumer group on OUTBOUND_STREAM. All worker replicas share one group.",
    )

    OUTBOUND_DLQ: str = Field(
        default="agentarea.channel.outbound.dlq",
        description="Stream that catches messages that exhausted retries or hit a fatal error.",
    )

    AUTOCLAIM_MIN_IDLE_MS: int = Field(
        default=60_000,
        description=(
            "Pending-entry age (ms) at which the autoclaimer reclaims an entry "
            "from a (presumed-dead) consumer."
        ),
    )

    AUTOCLAIM_INTERVAL_SECONDS: float = Field(
        default=30.0,
        description="How often the autoclaimer loop runs.",
    )

    DEDUP_TTL_SECONDS: int = Field(
        default=86_400,
        description=(
            "TTL on the consumer-side dedup SET key. Long enough to outlast "
            "any plausible broker redelivery, short enough to bound the key set."
        ),
    )

    CONSUMER_BLOCK_MS: int = Field(
        default=5_000,
        description="XREADGROUP block timeout per fetch (ms).",
    )

    CONSUMER_BATCH_SIZE: int = Field(
        default=10,
        description="Maximum entries claimed per XREADGROUP fetch.",
    )

    MAX_DELIVERY_ATTEMPTS: int = Field(
        default=20,
        description=(
            "Cap on how many times the broker may redeliver a message before "
            "it gets dead-lettered. Bounds both transient-failure retry loops "
            "(adapter outage) and poison messages (always-throwing code) so a "
            "single bad message can't burn a consumer indefinitely."
        ),
    )

    model_config = {"env_prefix": "CHANNEL_DELIVERY_", "extra": "ignore"}
