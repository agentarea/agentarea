"""Contract test: every tool schema a model receives is one Gemini accepts.

Gemini reads function declarations in its own subset of OpenAPI 3.0 and rejects
the whole request -- every tool, not only the offending one -- when one schema
breaks it. ``InboxToolset.list`` took ``InboxStatus | Literal[""]`` (#748):
pydantic renders the ``""`` as ``const`` beside the enum, Gemini has no
``const``, so a client folds both into one enum, and every Gemini request from a
harness connected to ``/mcp`` failed with ``enum[4]: cannot be empty``.

Two surfaces reach a model, so both are checked: the tools ``/mcp`` serves, as a
client lists them, and the toolsets the worker binds into agent runs.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any

import pytest
from agentarea_agents_sdk.tools.code_tools_loader import _ensure_all_toolsets_imported
from agentarea_agents_sdk.tools.tool_definition import build_method_schema, get_toolset_registry
from agentarea_api.platform_mcp import create_platform_mcp_server

HINT = 'Gemini cannot take "" as an allowed value; make the parameter optional (X | None = None)'


def _literals(schema: Any) -> Iterator[Any]:
    """Every value a schema pins: ``enum`` members and ``const``."""
    if isinstance(schema, dict):
        if isinstance(schema.get("enum"), list):
            yield from schema["enum"]
        if "const" in schema:
            yield schema["const"]
        for value in schema.values():
            yield from _literals(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _literals(item)


def _offers_empty_value(schema: dict) -> bool:
    return "" in _literals(schema)


@pytest.mark.asyncio
async def test_no_served_tool_offers_an_empty_string_value() -> None:
    tools = await create_platform_mcp_server(spanning=True).list_tools()

    offending = sorted(t.name for t in tools if _offers_empty_value(t.input_schema))

    assert not offending, f"{HINT}: {offending}"


def test_no_agent_tool_offers_an_empty_string_value() -> None:
    _ensure_all_toolsets_imported()

    offending = sorted(
        f"{cls.__module__}.{cls.__name__}.{name}"
        for cls in get_toolset_registry().values()
        for name, func in inspect.getmembers(cls, predicate=inspect.isfunction)
        if getattr(func, "_is_tool_method", False)
        and _offers_empty_value(build_method_schema(func))
    )

    assert not offending, f"{HINT}: {offending}"
