"""Tests for the EVENT_BUS_BACKEND factory."""

from __future__ import annotations

import pytest
from agentarea_common.config.broker import KafkaSettings, RedisSettings
from agentarea_common.events.factory import create_event_broker
from agentarea_common.events.redis_event_broker import RedisEventBroker


def test_default_backend_is_redis():
    settings = RedisSettings()
    broker = create_event_broker(settings)
    assert isinstance(broker, RedisEventBroker)


def test_kafka_backend_raises_not_implemented():
    settings = KafkaSettings(EVENT_BUS_BACKEND="kafka")
    with pytest.raises(NotImplementedError):
        create_event_broker(settings)


def test_nats_backend_raises_not_implemented():
    settings = RedisSettings(EVENT_BUS_BACKEND="nats")
    with pytest.raises(NotImplementedError):
        create_event_broker(settings)
