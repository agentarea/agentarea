"""Ory Keto (ReBAC) configuration."""

from .base import BaseAppSettings


class KetoSettings(BaseAppSettings):
    """Ory Keto ReBAC connection settings.

    Powers the access explorer's relationship graph, tuple management and
    permission checks. When ``KETO_ENABLED`` is false the OSS default
    ``WorkspaceScopedPermissionService`` (allow-all) stays in place and the rebac API
    surfaces an empty/disabled graph.
    """

    KETO_ENABLED: bool = False
    KETO_READ_URL: str = "http://keto:4466"
    KETO_WRITE_URL: str = "http://keto:4467"
    KETO_TIMEOUT_SECONDS: float = 10.0
