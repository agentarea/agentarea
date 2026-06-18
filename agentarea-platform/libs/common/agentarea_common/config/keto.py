"""Ory Keto (ReBAC) configuration."""

from .base import BaseAppSettings


class KetoSettings(BaseAppSettings):
    """Ory Keto ReBAC connection settings.

    Powers the access explorer's relationship graph, tuple management and
    permission checks when ``ACCESS_CONTROL_BACKEND=keto``.
    """

    ACCESS_CONTROL_KETO_READ_URL: str = "http://keto:4466"
    ACCESS_CONTROL_KETO_WRITE_URL: str = "http://keto:4467"
    ACCESS_CONTROL_KETO_TIMEOUT_SECONDS: float = 10.0
