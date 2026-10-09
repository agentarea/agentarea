"""Drop configured query parameters from stored OpenAPI tool schemas

A query parameter the connection configures is sent with its configured value
whatever the agent passes, so offering it in the tool's input schema only
misleads the agent. New and rediscovered tools leave it out; this strips it from
the ``available_tools`` already stored. A name the spec also uses outside the
query string stays, since the flat schema cannot tell the two apart.

Downgrade is a no-op: rediscovering a connection's tools rebuilds the schema.

Revision ID: 20261009_1210_openapi_qp_tools
Revises: 20261009_1200_openapi_dispatch
Create Date: 2026-10-09 12:10:00.000000
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_1210_openapi_qp_tools"
down_revision: str | None = "20261009_1200_openapi_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _load(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _non_query_param_names(spec: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(spec, dict):
        return names
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        groups = [path_item.get("parameters")]
        groups += [op_.get("parameters") for op_ in path_item.values() if isinstance(op_, dict)]
        for params in groups:
            for param in params or []:
                if isinstance(param, dict) and param.get("in") not in (None, "query"):
                    names.add(param.get("name"))
    return names


def _strip(tools: Any, names: set[str]) -> tuple[Any, bool]:
    changed = False
    for tool in tools if isinstance(tools, list) else []:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name in names & set(properties):
                del properties[name]
                changed = True
        required = schema.get("required")
        if isinstance(required, list) and names & set(required):
            schema["required"] = [r for r in required if r not in names]
            changed = True
    return tools, changed


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, custom_query_params, available_tools, spec_content "
                "FROM openapi_connections WHERE custom_query_params IS NOT NULL"
            )
        )
        .mappings()
        .all()
    )
    update = sa.text(
        "UPDATE openapi_connections SET available_tools = CAST(:tools AS json) WHERE id = :id"
    )
    for row in rows:
        configured = {
            p["name"]
            for p in _load(row["custom_query_params"]) or []
            if isinstance(p, dict) and p.get("name")
        }
        names = configured - _non_query_param_names(_load(row["spec_content"]))
        if not names:
            continue
        tools, changed = _strip(_load(row["available_tools"]), names)
        if changed:
            bind.execute(update, {"id": row["id"], "tools": json.dumps(tools)})


def downgrade() -> None:
    pass
