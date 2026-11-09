"""An OpenAPI operation is metered as its curated spec declares (wiki ADR-0038)."""

from types import SimpleNamespace

import pytest
from agentarea_common.tool_cost import CostSourceKind, Payer
from agentarea_openapi.application.metering import openapi_tool_connection
from agentarea_openapi.application.spec_parser import parse_openapi_operations

RATE = {"source": "rate", "rate": {"amount": "0.488", "currency": "EUR"}}
SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Search", "version": "1"},
    "x-agentarea-payers": ["workspace", "platform"],
    "x-agentarea-cost": {"source": "rate", "rate": {"amount": "0.02", "currency": "EUR"}},
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
    search = openapi_tool_connection(
        _connection(), "example.com/search-api/openapi", "web_search", catalog_spec=None
    )
    top = openapi_tool_connection(
        _connection(), "example.com/search-api/openapi", "wordstat_top", catalog_spec=None
    )

    assert (search.cost_model.source, str(search.cost_model.rate_amount)) == (
        CostSourceKind.RATE,
        "0.488",
    )
    assert str(top.cost_model.rate_amount) == "0.02"
    assert search.resource_ref == "example.com/search-api/openapi#web_search"


def test_a_platform_managed_connection_is_paid_by_the_platform():
    connection = openapi_tool_connection(
        _connection("platform"), "c", "web_search", catalog_spec=SPEC
    )

    assert connection.payer is Payer.PLATFORM


def test_parsed_operations_carry_their_cost_and_response_transform():
    by_name = {op["name"]: op for op in parse_openapi_operations(SPEC)}

    assert by_name["web_search"]["cost"] == RATE
    assert by_name["web_search"]["response_transform"] == [{"decode": "base64", "at": "$.rawData"}]
    assert by_name["wordstat_top"]["cost"] == SPEC["x-agentarea-cost"]


def test_an_operation_error_path_wins_over_the_spec_default():
    spec = {
        **SPEC,
        "x-agentarea-error-path": "$.response.error",
        "paths": {
            **SPEC["paths"],
            "/v2/wordstat/topRequests": {
                "post": {"operationId": "wordstat_top", "x-agentarea-error-path": "$.fault"}
            },
        },
    }

    by_name = {op["name"]: op for op in parse_openapi_operations(spec)}

    assert by_name["web_search"]["error_path"] == "$.response.error"
    assert by_name["wordstat_top"]["error_path"] == "$.fault"
    assert all(op["error_path"] is None for op in parse_openapi_operations(SPEC))


@pytest.mark.parametrize("path", ["response.error", "$", 3])
def test_an_error_path_must_name_a_field(path):
    with pytest.raises(ValueError, match="x-agentarea-error-path"):
        parse_openapi_operations({**SPEC, "x-agentarea-error-path": path})


def test_a_malformed_declaration_is_the_spec_authors_error():
    bad = {**SPEC, "x-agentarea-cost": {"source": "rate"}}

    with pytest.raises(ValueError, match="rate"):
        parse_openapi_operations(bad)
