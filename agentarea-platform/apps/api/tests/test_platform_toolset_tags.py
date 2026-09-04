"""Contract test: every platform toolset and tool method carries its grouping tags.

The MCP surface is grouped along two orthogonal axes so it can be re-sliced
without rewriting registration:

- ``plane``  — which surface this is (build / operate / observe / govern / federate),
  the axis a future split into separate MCP servers would cut along.
- ``effect`` — read / write / destructive / privileged, per tool method.

Tags are declared, never inferred: a toolset that forgets one fails here rather
than silently landing in a default bucket.
"""

from __future__ import annotations

from typing import get_args

import pytest
from agentarea_agents_sdk.tools.tool_definition import ToolEffect, ToolPlane
from agentarea_api.tools import get_platform_tools

PLANES = set(get_args(ToolPlane))
EFFECTS = set(get_args(ToolEffect))

TOOLSETS = get_platform_tools()


def _ids(toolset) -> str:
    return toolset.name


@pytest.mark.parametrize("toolset", TOOLSETS, ids=_ids)
def test_toolset_declares_plane(toolset) -> None:
    meta = toolset.metadata
    assert meta is not None, f"{toolset.name}: missing @toolset(...) metadata"
    assert meta.plane in PLANES, (
        f"{toolset.name}: plane={meta.plane!r} is not one of {sorted(PLANES)}. "
        "Declare it on @toolset(...)."
    )


@pytest.mark.parametrize("toolset", TOOLSETS, ids=_ids)
def test_every_tool_method_declares_effect(toolset) -> None:
    missing = []
    for method_name, method in toolset._tool_methods.items():
        meta = getattr(method, "_tool_meta", None)
        if meta is None or meta.effect not in EFFECTS:
            missing.append(f"{method_name}={getattr(meta, 'effect', None)!r}")
    assert not missing, (
        f"{toolset.name}: tool methods without a valid effect: {sorted(missing)}. "
        f"Pass effect=... to @tool_method (one of {sorted(EFFECTS)})."
    )


def test_tags_are_surfaced_in_the_code_tools_catalog() -> None:
    """Tags must reach the catalog, otherwise nothing can filter on them."""
    from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

    catalog = get_code_tools_metadata()
    entry = catalog.get("agentarea/agents")
    assert entry is not None, "agentarea/agents missing from the code tools catalog"
    assert entry["plane"] == "build"
