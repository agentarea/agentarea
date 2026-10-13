"""An OpenAPI operation is metered as its curated spec declares (wiki ADR-0038)."""

from types import SimpleNamespace

import pytest
from agentarea_common.tool_cost import CostSourceKind, Payer
from agentarea_openapi.application.metering import openapi_tool_connection
from agentarea_openapi.application.spec_parser import parse_openapi_operations

RATE = {"source": "rate", "rate": {"amount": "0.488", "currency": "RUB"}}
SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Search", "version": "1"},
    "x-agentarea-payers": ["workspace", "platform"],
    "x-agentarea-cost": {"source": "rate", "rate": {"amount": "0.02", "currency": "RUB"}},
    "paths": {
        "/v2/web/search": {
            "post": {
                "operationId": "web_search",
                "x-agentarea-cost": RATE,
                "x-agentarea-response-transform": [{"decode": "base64", "at": "$.rawData"}],
            }
        },
        "/v2/wordstat/topRequests": {"post": {"operationId": "wordstat_top"}},
    },
}


def _connection(managed_by=None, spec=SPEC):
    return SimpleNamespace(
        id="conn-1", spec_content=spec, custom_query_params=None, managed_by=managed_by
    )


def test_an_operation_declaration_wins_and_the_rest_take_the_default():
    search = openapi_tool_connection(_connection(), "ru.yandex/search-api/openapi", "web_search")
    top = openapi_tool_connection(_connection(), "ru.yandex/search-api/openapi", "wordstat_top")

    assert (search.cost_model.source, str(search.cost_model.rate_amount)) == (
        CostSourceKind.RATE,
        "0.488",
    )
    assert str(top.cost_model.rate_amount) == "0.02"
    assert search.resource_ref == "ru.yandex/search-api/openapi#web_search"


def test_a_platform_managed_connection_is_paid_by_the_platform():
    connection = openapi_tool_connection(_connection("platform"), "c", "web_search")

    assert connection.payer is Payer.PLATFORM


def test_parsed_operations_carry_their_cost_and_response_transform():
    by_name = {op["name"]: op for op in parse_openapi_operations(SPEC)}

    assert by_name["web_search"]["cost"] == RATE
    assert by_name["web_search"]["response_transform"] == [{"decode": "base64", "at": "$.rawData"}]
    assert by_name["wordstat_top"]["cost"] == SPEC["x-agentarea-cost"]


def test_a_malformed_declaration_is_the_spec_authors_error():
    bad = {**SPEC, "x-agentarea-cost": {"source": "rate"}}

    with pytest.raises(ValueError, match="rate"):
        parse_openapi_operations(bad)
