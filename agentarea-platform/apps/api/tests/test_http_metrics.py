"""Request metrics are labelled by route template, never by the raw path.

A raw path carries workspace slugs and ids, so every tenant and every object
would mint its own time series.
"""

from agentarea_api.main import app
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

DURATION = "agentarea_http_request_duration_seconds_count"


def _count(**labels: str) -> float:
    return REGISTRY.get_sample_value(DURATION, labels) or 0.0


def test_a_templated_route_is_recorded_under_its_template():
    template = "/v1/workspaces/{workspace}/mcp-servers/"
    raw = "/v1/workspaces/metrics-probe/mcp-servers/"
    before = _count(method="GET", route=template, status="4xx")

    response = TestClient(app, raise_server_exceptions=False).get(raw)

    assert response.status_code == 401
    assert _count(method="GET", route=template, status="4xx") == before + 1
    assert _count(method="GET", route=raw, status="4xx") == 0


def test_a_path_no_route_matches_is_recorded_as_unmatched():
    before = _count(method="GET", route="<unmatched>", status="4xx")

    response = TestClient(app, raise_server_exceptions=False).get("/no/such/route/for-metrics")

    assert response.status_code == 404
    assert _count(method="GET", route="<unmatched>", status="4xx") == before + 1
    assert _count(method="GET", route="/no/such/route/for-metrics", status="4xx") == 0
