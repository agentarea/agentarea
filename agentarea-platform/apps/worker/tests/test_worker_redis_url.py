"""The channel machinery reads the Redis URL the environment actually set.

``settings.broker.REDIS_URL`` is populated from ``AGENTAREA_REDIS_URL``: the
field name and the variable name differ, and the worker used to reach for it
with ``getattr(settings.broker, ..., "redis://localhost:6379")``. A wrong
attribute name there is invisible -- the default answers instead -- so the
worker started happily in compose and then failed connecting to localhost
while it had been handed ``redis://valkey:6379``. Only a live stack noticed.
"""

import pytest
from agentarea_common.config import get_settings
from agentarea_worker.main import _redis_url


@pytest.fixture
def broker_env(monkeypatch):
    def _set(**env):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        return get_settings()

    get_settings.cache_clear()
    yield _set
    get_settings.cache_clear()


def test_the_configured_url_is_what_comes_back(broker_env):
    settings = broker_env(AGENTAREA_BROKER="redis", AGENTAREA_REDIS_URL="redis://valkey:6379")

    assert _redis_url(settings) == "redis://valkey:6379"


def test_a_non_redis_broker_is_refused_rather_than_defaulted(broker_env):
    settings = broker_env(AGENTAREA_BROKER="kafka")

    with pytest.raises(RuntimeError, match="AGENTAREA_BROKER=redis"):
        _redis_url(settings)
