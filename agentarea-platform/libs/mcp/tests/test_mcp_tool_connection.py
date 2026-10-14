"""An MCP connection's tool is metered as the catalog entry it was made from declares."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from agentarea_common.tool_cost import CostSourceKind, Payer, ToolCostError
from agentarea_mcp.domain.metering import mcp_tool_connection

ENTRY = {
    "name": "com.apify/mcp",
    "metadata": {
        "agentarea:payers": ["workspace", "platform"],
        "agentarea:cost": {
            "default": {"source": "reported", "reported": {"meta": "cost_usd", "currency": "USD"}},
            "tools": {"search-actors": {"source": "free"}},
        },
    },
}


def _instance(managed_by=None):
    return SimpleNamespace(id="inst-1", managed_by=managed_by)


def test_a_tool_takes_its_own_declaration_over_the_default():
    free = mcp_tool_connection(_instance(), ENTRY, "search-actors")
    run = mcp_tool_connection(_instance(), ENTRY, "call-actor")

    assert free.cost_model.source is CostSourceKind.FREE
    assert (run.cost_model.source, run.cost_model.reported_meta) == (
        CostSourceKind.REPORTED,
        "cost_usd",
    )
    assert (run.connection_id, run.connector, run.tool, run.payer) == (
        "inst-1",
        "com.apify/mcp",
        "call-actor",
        Payer.WORKSPACE,
    )


def test_a_platform_managed_connection_is_paid_by_the_platform():
    assert mcp_tool_connection(_instance("platform"), ENTRY, "call-actor").payer is Payer.PLATFORM


def test_a_connection_with_no_catalog_entry_has_an_unknown_cost_and_its_own_connector():
    connection = mcp_tool_connection(_instance(), None, "anything")

    assert connection.cost_model.source is CostSourceKind.UNKNOWN
    assert connection.connector == "connection:inst-1"


def test_a_platform_connection_the_connector_does_not_allow_is_refused():
    with pytest.raises(ToolCostError, match="platform"):
        mcp_tool_connection(_instance("platform"), {"name": "x", "metadata": {}}, "t")


def test_a_rate_declaration_keeps_its_amount():
    entry = {
        "name": "x",
        "metadata": {
            "agentarea:cost": {
                "default": {"source": "rate", "rate": {"amount": "0.1", "currency": "USD"}}
            }
        },
    }

    assert mcp_tool_connection(_instance(), entry, "t").cost_model.rate_amount == Decimal("0.1")
