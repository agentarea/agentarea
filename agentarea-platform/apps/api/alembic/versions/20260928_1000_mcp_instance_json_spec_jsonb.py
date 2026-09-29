r"""Store mcp_server_instances.json_spec as jsonb

The column was plain ``json`` while ``mcp_servers.json_spec`` is jsonb. Plain
json accepts ``\u0000`` and unpaired surrogates, then fails to render them in
every ``->>``: one fuzzed instance made the mcp-manager idle sweep, which reads
``json_spec->>'type'`` across all instances, fail on every tick. jsonb refuses
such text at write time.

Rows already holding it are cleaned first (NUL dropped, lone surrogates
replaced with U+FFFD), because the type change cannot convert them.

Revision ID: 20260928_1000_inst_spec_jsonb
Revises: 20260927_1200_catalog_cleanup
Create Date: 2026-09-28 10:00:00.000000
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_1000_inst_spec_jsonb"
down_revision: str | None = "20260927_1200_catalog_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNSTORABLE_ESCAPE = r"\\u(0000|[dD][89a-fA-F][0-9a-fA-F]{2})"


def _clean_text(text: str) -> str:
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text.replace("\x00", "")


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        return {_clean_text(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, json_spec::text FROM mcp_server_instances WHERE json_spec::text ~ :pattern"
        ),
        {"pattern": _UNSTORABLE_ESCAPE},
    ).all()
    for row_id, spec_text in rows:
        cleaned = json.dumps(_clean(json.loads(spec_text)))
        bind.execute(
            sa.text(
                "UPDATE mcp_server_instances SET json_spec = CAST(:spec AS json) WHERE id = :id"
            ),
            {"spec": cleaned, "id": row_id},
        )
    op.execute(
        "ALTER TABLE mcp_server_instances ALTER COLUMN json_spec TYPE jsonb USING json_spec::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE mcp_server_instances ALTER COLUMN json_spec TYPE json USING json_spec::json"
    )
