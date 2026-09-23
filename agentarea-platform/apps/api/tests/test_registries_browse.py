"""Contract for the catalog browse endpoint that backs /explore.

The gallery needs several things from one call, over one consistent filter: the
page, how many items match in total, and the facets (categories, plus the
MCP/API split for connections). Splitting them across calls is what let the old
client show "No matches" while the catalog still had pages left, and let the
sidebar counts drift as scrolling appended.

Driven through the real ASGI app so query defaults and validation are covered
rather than bypassed.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import registries
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _Item:
    """Minimal stand-in for a RegistryItem row."""

    def __init__(self, name, category=None, featured=False):
        self.id = uuid4()
        self.registry_id = uuid4()
        self.external_id = name
        self.name = name
        self.description = None
        self.version = "1.0.0"
        self.spec = {}
        self.tags = []
        self.installed_entity_id = None
        self.update_available = False
        self.installed_version = None
        self.category = category
        self.featured = featured
        self.created_at = datetime(2026, 1, 1)
        self.updated_at = datetime(2026, 1, 1)


class _Service:
    def __init__(self, items=None, total=0, categories=None, protocols=None):
        self._result = (items or [], total, categories or [], protocols or [])
        self.calls = []

    async def browse_catalog(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


def _client_for(service: _Service) -> AsyncClient:
    app = FastAPI()
    app.include_router(registries.router, prefix="/v1")
    app.dependency_overrides[registries.get_registry_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="u1", workspace_id="ws-1"
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _browse(service, **params):
    async with _client_for(service) as client:
        return await client.get("/v1/registries/catalog/browse", params=params)


class TestResponseShape:
    async def test_returns_items_total_and_categories_together(self):
        service = _Service(
            items=[_Item("apple", category="data"), _Item("banana")],
            total=57,
            categories=[("data", 40), ("other", 17)],
        )
        body = (await _browse(service, registry_type="skills")).json()

        assert [i["name"] for i in body["items"]] == ["apple", "banana"]
        assert body["total"] == 57
        assert body["categories"] == [
            {"value": "data", "count": 40},
            {"value": "other", "count": 17},
        ]

    async def test_total_survives_a_page_that_matches_nothing_visible(self):
        # The signal the client needs to keep paging instead of giving up.
        service = _Service(items=[], total=310, categories=[("other", 12)])
        body = (await _browse(service, registry_type="skills", category="other")).json()
        assert body["items"] == []
        assert body["total"] == 310

    async def test_items_carry_the_server_derived_facets(self):
        service = _Service(items=[_Item("x", category="data", featured=True)], total=1)
        body = (await _browse(service, registry_type="skills")).json()
        assert body["items"][0]["category"] == "data"
        assert body["items"][0]["featured"] is True

    async def test_connections_report_the_mcp_api_split(self):
        # "Connections" is not a synonym for MCP: the sidebar has to say how
        # many of each there are before you can filter to one.
        service = _Service(items=[_Item("GitHub")], total=2, protocols=[("mcp", 4247), ("api", 12)])
        body = (await _browse(service, registry_type="mcp_servers")).json()
        assert body["protocols"] == [
            {"value": "mcp", "count": 4247},
            {"value": "api", "count": 12},
        ]

    async def test_types_without_a_protocol_dimension_report_none(self):
        body = (await _browse(_Service(), registry_type="skills")).json()
        assert body["protocols"] == []


class TestParameterPassThrough:
    async def test_forwards_every_browse_dimension(self):
        service = _Service()
        await _browse(
            service,
            registry_type="mcp_servers",
            q="pdf",
            category="other",
            protocol="api",
            sort="name",
            limit=24,
            offset=48,
        )
        assert service.calls == [
            {
                "registry_type": "mcp_servers",
                "query": "pdf",
                "category": "other",
                "protocol": "api",
                "sort": "name",
                "limit": 24,
                "offset": 48,
            }
        ]

    async def test_defaults_leave_filters_unset(self):
        service = _Service()
        await _browse(service, registry_type="skills")
        call = service.calls[0]
        assert call["query"] is None
        assert call["category"] is None
        assert call["sort"] is None
        assert call["protocol"] is None
        assert call["offset"] == 0


class TestValidation:
    async def test_rejects_an_unknown_registry_type(self):
        assert (await _browse(_Service(), registry_type="not_a_type")).status_code == 400

    async def test_rejects_an_unknown_sort(self):
        # A silently-ignored bad sort would page the catalog in one order while
        # the UI claims another.
        resp = await _browse(_Service(), registry_type="skills", sort="by_vibes")
        assert resp.status_code == 400

    async def test_rejects_an_unknown_protocol(self):
        # A closed vocabulary declared on the route, so FastAPI rejects it
        # before the handler runs.
        resp = await _browse(_Service(), registry_type="mcp_servers", protocol="carrier-pigeon")
        assert resp.status_code == 422

    async def test_rejects_a_protocol_filter_on_a_type_that_has_none(self):
        # Answering 200 here would page the whole skills catalog while the
        # caller believes it asked for HTTP APIs.
        resp = await _browse(_Service(), registry_type="skills", protocol="api")
        assert resp.status_code == 400

    async def test_requires_a_registry_type(self):
        assert (await _browse(_Service())).status_code == 422

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 9999}, {"offset": -1}])
    async def test_rejects_out_of_range_paging(self, params):
        resp = await _browse(_Service(), registry_type="skills", **params)
        assert resp.status_code == 422
