"""Temporal configuration."""

import os
from datetime import timedelta

from dotenv import dotenv_values
from pydantic_settings import SettingsConfigDict
from temporalio.envconfig import ClientConfig, ClientConnectConfig

from .base import BaseAppSettings
from .duration import Duration


class TemporalSettings(BaseAppSettings):
    """How AgentArea uses Temporal: its task queue and its worker's limits.

    Where Temporal is — TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY,
    TEMPORAL_TLS_* — is Temporal's own client contract, read by the SDK through
    :func:`temporal_connect_config`, not by this class.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_TEMPORAL_")

    QUEUE: str = ""
    MAX_ACTIVITIES: int = 10
    MAX_WORKFLOWS: int = 5
    # Workflows kept in memory between their tasks; each holds its conversation.
    MAX_CACHED: int = 200
    # How long a stopping worker lets in-flight activities finish before
    # cancelling them.
    SHUTDOWN_GRACE: Duration = timedelta(seconds=120)


def temporal_connect_config() -> ClientConnectConfig:
    """Keyword arguments for ``Client.connect`` from Temporal's environment contract.

    Reads the same ``.env`` our settings classes do, with the process
    environment taking precedence, so local runs behave like deployed ones.
    """
    env = {k: v for k, v in dotenv_values(".env").items() if v is not None}
    env.update(os.environ)
    config = ClientConfig.load_client_connect_config(override_env_vars=env)
    missing = [
        name
        for name, key in (("TEMPORAL_ADDRESS", "target_host"), ("TEMPORAL_NAMESPACE", "namespace"))
        if not config.get(key)
    ]
    if missing:
        raise RuntimeError(f"Temporal client is not configured: set {', '.join(missing)}")
    return config
