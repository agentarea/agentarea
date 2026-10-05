"""Composition for event streams: the wake signal every writer publishes after commit."""

import logging

from agentarea_common.config import RedisSettings, Settings
from agentarea_common.di.container import register_singleton

from ..domain.ports import StreamWaker
from .waker import RedisStreamWaker

logger = logging.getLogger(__name__)


def setup_streams_di(settings: Settings) -> None:
    if not isinstance(settings.broker, RedisSettings):
        raise RuntimeError(
            "Event streams wake their dispatchers over Redis; set AGENTAREA_BROKER=redis "
            f"(current: {settings.broker.BROKER})"
        )
    register_singleton(StreamWaker, RedisStreamWaker(settings.broker.REDIS_URL))
    logger.info("StreamWaker=RedisStreamWaker")
