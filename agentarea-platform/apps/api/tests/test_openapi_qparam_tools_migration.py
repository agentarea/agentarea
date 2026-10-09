"""Contract tests for stripping configured query parameters from stored tool schemas."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261009_1210_openapi_qparam_tools.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_openapi_qparam_tools", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool(name: str, *params: str) -> dict:
    return {
        "name": name,
        "description": "",
        "inputSchema": {
            "type": "object",
            "properties": {p: {"type": "string"} for p in params},
            "required": list(params),
        },
    }


def _spec(*params: tuple[str, str]) -> dict:
    return {
        "openapi": "3.0.0",
        "paths": {"/x": {"get": {"parameters": [{"name": n, "in": i} for n, i in params]}}},
    }


def _run(rows: list[dict]) -> list[dict]:
    module = _load_migration()
    bind = MagicMock()
    bind.execute.return_value.mappings.return_value.all.return_value = rows

    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()

    return [call.args[1] for call in bind.execute.call_args_list[1:]]


def test_a_configured_param_leaves_every_stored_tool_schema() -> None:
    row_id = uuid4()
    rows = [
        {
            "id": row_id,
            "custom_query_params": [{"name": "ms", "secret": True}],
            "available_tools": json.dumps([_tool("collect", "ms", "dl"), _tool("ping")]),
            "spec_content": _spec(("ms", "query"), ("dl", "query")),
        }
    ]

    [update] = _run(rows)

    assert update["id"] == row_id
    assert json.loads(update["tools"]) == [_tool("collect", "dl"), _tool("ping")]


def test_a_name_the_spec_also_uses_outside_the_query_stays() -> None:
    rows = [
        {
            "id": uuid4(),
            "custom_query_params": [{"name": "ms", "secret": True}],
            "available_tools": [_tool("collect", "ms")],
            "spec_content": _spec(("ms", "path")),
        }
    ]

    assert _run(rows) == []


def test_a_row_without_the_param_in_its_tools_is_left_alone() -> None:
    rows = [
        {
            "id": uuid4(),
            "custom_query_params": [{"name": "ms", "secret": True}],
            "available_tools": [_tool("collect", "dl")],
            "spec_content": _spec(("dl", "query")),
        }
    ]

    assert _run(rows) == []
