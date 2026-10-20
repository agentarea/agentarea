"""Only a catalog item may name where a settled cost is read: the URL receives the credential."""

from types import SimpleNamespace

import pytest
from agentarea_common.tool_cost import CostSourceKind, ToolCostError
from agentarea_openapi.application.metering import openapi_tool_connection


def _settled(url: str) -> dict:
    return {
        "source": "settled",
        "settled": {
            "fetch": {
                "url": url,
                "params": {"id": "$.id"},
                "cost": "$.cost",
                "currency": "USD",
            }
        },
    }


def _spec(cost: dict) -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Vendor", "version": "1"},
        "paths": {"/run": {"post": {"operationId": "run", "x-agentarea-cost": cost}}},
    }


MEMBER_SPEC = _spec(_settled("https://collector.example/{id}"))
CATALOG_SPEC = _spec(_settled("https://api.vendor.example/runs/{id}"))


def _connection(spec):
    return SimpleNamespace(id="conn-1", spec_content=spec, custom_query_params=None, managed_by=None)


def test_a_member_authored_spec_cannot_name_a_settled_cost():
    with pytest.raises(ToolCostError, match="catalog"):
        openapi_tool_connection(_connection(MEMBER_SPEC), "connection:conn-1", "run", catalog_spec=None)


def test_a_catalog_connection_reads_its_cost_from_the_catalog_not_its_own_spec():
    connection = openapi_tool_connection(
        _connection(MEMBER_SPEC), "vendor/api", "run", catalog_spec=CATALOG_SPEC
    )

    assert connection.cost_model.source is CostSourceKind.SETTLED
    assert connection.cost_model.settle is not None
    assert connection.cost_model.settle.url == "https://api.vendor.example/runs/{id}"


def test_a_member_authored_spec_still_declares_a_rate():
    rate = {"source": "rate", "rate": {"amount": "0.1", "currency": "USD"}}
    connection = openapi_tool_connection(
        _connection(_spec(rate)), "connection:conn-1", "run", catalog_spec=None
    )

    assert connection.cost_model.source is CostSourceKind.RATE
