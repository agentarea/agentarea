"""Prometheus metrics for the API process.

They live on the default registry, which the API serves on its own port (see
``start_metrics_server``) so that ``/metrics`` never shares a listener with the
public API.
"""

from __future__ import annotations

import logging
from wsgiref.simple_server import WSGIServer

from prometheus_client import Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

HTTP_REQUEST_DURATION = Histogram(
    "agentarea_http_request_duration_seconds",
    "HTTP request latency by route template and status class.",
    ["method", "route", "status"],
    buckets=LATENCY_BUCKETS,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "agentarea_http_requests_in_progress",
    "HTTP requests currently being served, by route template.",
    ["method", "route"],
)

AUTHZ_DURATION = Histogram(
    "agentarea_authz_duration_seconds",
    "Time spent answering authorization questions, by operation.",
    ["operation"],
    buckets=LATENCY_BUCKETS,
)


def start_metrics_server(port: int) -> WSGIServer:
    """Serve the default registry on ``port``. Raises if the port is taken.

    Returns the server so the caller can ``shutdown()`` it on exit.
    """
    server, _thread = start_http_server(port)
    logger.info("Prometheus metrics served on :%s/metrics", port)
    return server
