"""Anonymous usage analytics sent to AgentArea (wiki ADR-0041).

Analytics, not telemetry: OpenTelemetry and Prometheus go to the operator's own
monitoring, this goes to us. ``AGENTAREA_ANALYTICS_ENABLED=false`` turns it off.
"""

from .constants import COLLECTOR_KEY, COLLECTOR_URL, DOCS_URL, NOTICE
from .counters import count, count_run_refused
from .hashing import pseudonymize
from .models import Installation
from .pulse import InstallationPulse
from .repository import get_or_create_installation
from .runtime import current_sender, start_analytics, stop_analytics
from .sender import MAX_BATCH, AnalyticsSender

__all__ = [
    "COLLECTOR_KEY",
    "COLLECTOR_URL",
    "DOCS_URL",
    "MAX_BATCH",
    "NOTICE",
    "AnalyticsSender",
    "Installation",
    "InstallationPulse",
    "count",
    "count_run_refused",
    "current_sender",
    "get_or_create_installation",
    "pseudonymize",
    "start_analytics",
    "stop_analytics",
]
