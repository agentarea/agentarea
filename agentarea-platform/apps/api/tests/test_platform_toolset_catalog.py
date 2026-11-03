"""The toolsets a client can carry are described by the classes that serve them."""

from agentarea_api.api.v1.clients import platform_toolset_catalog


def test_every_platform_toolset_a_client_can_carry_is_named_and_described():
    catalog = {toolset.name: toolset for toolset in platform_toolset_catalog()}

    undescribed = [
        name
        for name, toolset in catalog.items()
        if not toolset.description or toolset.display_name == name.rsplit("/", 1)[-1]
    ]
    assert undescribed == []


def test_workspace_files_is_described_by_the_toolset_clients_are_served():
    workspace_files = next(
        toolset
        for toolset in platform_toolset_catalog()
        if toolset.name == "agentarea/workspace_files"
    )

    assert workspace_files.display_name == "Workspace Files"
    assert {method.name for method in workspace_files.methods} >= {"upload_urls", "get_url"}
    assert all(method.description for method in workspace_files.methods)
