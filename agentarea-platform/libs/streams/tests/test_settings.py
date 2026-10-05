from datetime import timedelta

import pytest
from agentarea_common.config import get_settings
from agentarea_common.config.streams import EventStreamSettings


def test_defaults_are_bounded():
    settings = EventStreamSettings()
    assert settings.WRITE_QUOTA == 600
    assert settings.RETENTION == timedelta(days=30)
    assert settings.PARTITIONS_AHEAD == 7
    assert settings.DISPATCH_EVERY == timedelta(seconds=2)
    assert settings.FORWARD_DEPTH == 8
    assert settings.MAX_ATTEMPTS == 10
    assert settings.LEASE == timedelta(minutes=5)


def test_env_names_carry_the_event_domain(monkeypatch):
    monkeypatch.setenv("AGENTAREA_EVENT_WRITE_QUOTA", "5")
    monkeypatch.setenv("AGENTAREA_EVENT_RETENTION", "7d")
    settings = EventStreamSettings()
    assert settings.WRITE_QUOTA == 5
    assert settings.RETENTION == timedelta(days=7)


def test_a_bare_number_is_not_a_duration(monkeypatch):
    monkeypatch.setenv("AGENTAREA_EVENT_RETENTION", "30")
    with pytest.raises(ValueError, match="duration must be"):
        EventStreamSettings()


def test_registered_on_the_settings_container():
    get_settings.cache_clear()
    assert isinstance(get_settings().streams, EventStreamSettings)
