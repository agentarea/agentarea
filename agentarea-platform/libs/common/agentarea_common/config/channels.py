"""Consumer settings the broker consumers share: task-event delivery and polled-item ingest.

Replies go out through the ``delivery`` group on ``tasks.events``; polled items
come in through the ``ingest`` group on ``streams.ingest``
(``agentarea_common.broker.topics``). The timings, batch size and attempt cap
here apply to both.
"""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .duration import Duration


class ChannelDeliverySettings(BaseSettings):
    """Configuration for the broker consumers: task-event delivery and polled-item ingest."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_CHANNEL_", extra="ignore")

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
