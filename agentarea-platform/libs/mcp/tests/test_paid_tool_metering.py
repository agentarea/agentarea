"""What a platform-funded connection's tools declare, and what its calls report.

The tool-gateway names, per tool, the resource a call is metered as
(``_meta["agentarea.ai/resource_ref"]`` in tools/list), and reports per call what it
used (``_meta["agentarea.ai/usage"]``). Only a platform-managed connection's
declarations are read: anyone can put ``_meta`` on a tool.
"""

from types import SimpleNamespace

from agentarea_mcp.domain.metering import platform_funded_resource, reported_quantity

TOOLS = [
    {"name": "yandex_search", "_meta": {"agentarea.ai/resource_ref": "yandex.search.web"}},
    {"name": "plain"},
]


def _instance(managed_by="platform", tools=TOOLS):
    return SimpleNamespace(
        managed_by=managed_by,
        platform_managed=managed_by == "platform",
        tools=tools,
        json_spec={},
        get_available_tools=lambda: tools,
    )


def test_a_platform_connections_tool_is_metered_as_it_declares():
    assert platform_funded_resource(_instance(), "yandex_search") == "yandex.search.web"


def test_a_workspaces_own_connection_is_never_platform_funded():
    assert platform_funded_resource(_instance(managed_by=None), "yandex_search") is None
    assert platform_funded_resource(None, "yandex_search") is None


def test_a_platform_tool_that_declares_nothing_has_an_empty_resource():
    """Present but unpriceable: the caller refuses it rather than run it free."""
    assert platform_funded_resource(_instance(), "plain") == ""
    assert platform_funded_resource(_instance(), "unknown") == ""


def test_the_reported_quantity_is_read_for_the_declared_resource():
    meta = {"agentarea.ai/usage": {"resource_ref": "yandex.search.web", "quantity": 1}}

    assert reported_quantity(meta, "yandex.search.web") == 1


def test_a_report_for_another_resource_or_none_counts_nothing():
    meta = {"agentarea.ai/usage": {"resource_ref": "yandex.wordstat.top", "quantity": 3}}

    assert reported_quantity(meta, "yandex.search.web") is None
    assert reported_quantity(None, "yandex.search.web") is None
    assert reported_quantity({"agentarea.ai/usage": {"quantity": "x"}}, "r") is None
