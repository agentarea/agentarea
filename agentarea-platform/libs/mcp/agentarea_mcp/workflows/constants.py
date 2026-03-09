"""Constants for MCP instance lifecycle workflows."""

from datetime import timedelta

# ── Timeout configurations ───────────────────────────────────────────────

CONTAINER_START_TIMEOUT: timedelta = timedelta(minutes=5)
TOOL_DISCOVERY_TIMEOUT: timedelta = timedelta(seconds=30)
CONTAINER_STOP_TIMEOUT: timedelta = timedelta(minutes=2)
DB_UPDATE_TIMEOUT: timedelta = timedelta(seconds=10)
EVENT_PUBLISH_TIMEOUT: timedelta = timedelta(seconds=5)
HEALTH_POLL_TIMEOUT: timedelta = timedelta(seconds=15)
ENV_RESOLVE_TIMEOUT: timedelta = timedelta(seconds=10)

# ── Health polling ───────────────────────────────────────────────────────

HEALTH_POLL_INTERVAL_SECONDS: int = 3
HEALTH_POLL_MAX_ATTEMPTS: int = 60  # 60 * 3s = 3 min max polling

# ── Retry policies ───────────────────────────────────────────────────────

DEFAULT_RETRY_ATTEMPTS: int = 3
CONTAINER_CREATE_RETRY_ATTEMPTS: int = 2
EVENT_PUBLISH_RETRY_ATTEMPTS: int = 1  # fire and forget
