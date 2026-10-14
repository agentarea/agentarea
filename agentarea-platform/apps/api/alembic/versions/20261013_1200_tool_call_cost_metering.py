"""cost_entries: one metered line per tool call, whoever pays (wiki ADR-0038)

A tool call's line now says who paid (``payer``: ``workspace`` on the customer's key,
``platform`` on ours, ``per_call`` from the agent's wallet), how much was used
(``quantity`` in ``unit``) and what the vendor charged (``vendor_cost`` in
``vendor_currency``). ``payer`` replaces ``managed_by``: ``'platform'`` stays
platform, an x402/MPP line is ``per_call``, every other existing row is
``workspace``. No amount, source or evidence of an existing row changes. The
partial index billing's reader uses moves to ``payer``; two more serve the spend
caps on a connection and on a client.

``openapi_connections.managed_by``: ``'platform'`` marks an OpenAPI connection the
deployment operator supplies, as on MCP instances.

``client_openapi_connections``: a Registered Client carries OpenAPI connections, as it
carries MCP instances, and calls them over ``/mcp/clients/{id}``.

``task_summary.cost_usd`` sums the ``cost`` of every ``tool.result``: the tool-call
layer now meters a declared cost on any connection, not only the platform's.

Revision ID: 20261013_1200_tool_cost_metering
Revises: 20261012_1400_cost_entry_client
Create Date: 2026-10-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_1200_tool_cost_metering"
down_revision: str | None = "20261012_1400_cost_entry_client"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_VIEW_WITH_METERED_TOOLS = """
CREATE VIEW task_summary AS
SELECT
    t.id                      AS task_id,
    t.agent_id                AS agent_id,
    t.workspace_id            AS workspace_id,
    t.created_by              AS created_by,
    t.status                  AS status,
    t.created_at              AS started_at,
    MAX(e.timestamp) FILTER (
        WHERE e.event_type IN ('task.completed', 'task.failed')
    )                         AS ended_at,
    EXTRACT(EPOCH FROM (
        MAX(e.timestamp) FILTER (
            WHERE e.event_type IN ('task.completed', 'task.failed')
        ) - t.created_at
    )) * 1000                 AS duration_ms,
    COUNT(*) FILTER (WHERE e.event_type = 'IterationCompleted')        AS iterations,
    COUNT(*) FILTER (WHERE e.event_type = 'llm.call.completed')        AS llm_calls,
    COUNT(*) FILTER (WHERE e.event_type = 'llm.call.failed')           AS llm_calls_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'tool.call')                 AS tools_called,
    COUNT(*) FILTER (
        WHERE e.event_type = 'tool.result'
          AND (e.data ->> 'success' = 'false' OR (e.data ->> 'exit_code') NOT IN ('0', ''))
    )                         AS tools_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationStarted')    AS delegations_started,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationCompleted')  AS delegations_completed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationFailed')     AS delegations_failed,
    COALESCE(SUM(
        CASE
            WHEN e.event_type = 'llm.call.completed' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            WHEN e.event_type = 'tool.result' AND e.data ? 'model_cost'
            THEN (e.data ->> 'model_cost')::numeric
            WHEN e.event_type = 'tool.result' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type = 'task.completed'
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
    (
        SELECT e3.data ->> 'error'
        FROM task_events e3
        WHERE e3.task_id = t.id
          AND (
              e3.event_type IN ('task.failed', 'llm.call.failed')
              OR (
                  e3.event_type = 'tool.result'
                  AND (
                      e3.data ->> 'success' = 'false'
                      OR (e3.data ->> 'exit_code') NOT IN ('0', '')
                  )
              )
          )
        ORDER BY e3.timestamp DESC
        LIMIT 1
    )                         AS last_error
FROM tasks t
LEFT JOIN task_events e ON e.task_id = t.id
GROUP BY t.id;
"""

CREATE_VIEW_WITH_PAID_TOOLS = """
CREATE VIEW task_summary AS
SELECT
    t.id                      AS task_id,
    t.agent_id                AS agent_id,
    t.workspace_id            AS workspace_id,
    t.created_by              AS created_by,
    t.status                  AS status,
    t.created_at              AS started_at,
    MAX(e.timestamp) FILTER (
        WHERE e.event_type IN ('task.completed', 'task.failed')
    )                         AS ended_at,
    EXTRACT(EPOCH FROM (
        MAX(e.timestamp) FILTER (
            WHERE e.event_type IN ('task.completed', 'task.failed')
        ) - t.created_at
    )) * 1000                 AS duration_ms,
    COUNT(*) FILTER (WHERE e.event_type = 'IterationCompleted')        AS iterations,
    COUNT(*) FILTER (WHERE e.event_type = 'llm.call.completed')        AS llm_calls,
    COUNT(*) FILTER (WHERE e.event_type = 'llm.call.failed')           AS llm_calls_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'tool.call')                 AS tools_called,
    COUNT(*) FILTER (
        WHERE e.event_type = 'tool.result'
          AND (e.data ->> 'success' = 'false' OR (e.data ->> 'exit_code') NOT IN ('0', ''))
    )                         AS tools_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationStarted')    AS delegations_started,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationCompleted')  AS delegations_completed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationFailed')     AS delegations_failed,
    COALESCE(SUM(
        CASE
            WHEN e.event_type = 'llm.call.completed' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            WHEN e.event_type = 'tool.result' AND e.data ? 'model_cost'
            THEN (e.data ->> 'model_cost')::numeric
            WHEN e.event_type = 'tool.result' AND e.data ->> 'managed_by' = 'platform'
                 AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type = 'task.completed'
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
    (
        SELECT e3.data ->> 'error'
        FROM task_events e3
        WHERE e3.task_id = t.id
          AND (
              e3.event_type IN ('task.failed', 'llm.call.failed')
              OR (
                  e3.event_type = 'tool.result'
                  AND (
                      e3.data ->> 'success' = 'false'
                      OR (e3.data ->> 'exit_code') NOT IN ('0', '')
                  )
              )
          )
        ORDER BY e3.timestamp DESC
        LIMIT 1
    )                         AS last_error
FROM tasks t
LEFT JOIN task_events e ON e.task_id = t.id
GROUP BY t.id;
"""

PAYER_BACKFILL_SQL = (
    "UPDATE cost_entries SET payer = CASE "
    "WHEN managed_by = 'platform' THEN 'platform' "
    "WHEN source IN ('x402', 'mpp') THEN 'per_call' "
    "ELSE 'workspace' END "
    "WHERE payer IS NULL"
)


def upgrade() -> None:
    op.add_column("cost_entries", sa.Column("payer", sa.String(length=16), nullable=True))
    op.execute(PAYER_BACKFILL_SQL)
    op.alter_column("cost_entries", "payer", nullable=False)
    op.add_column("cost_entries", sa.Column("quantity", sa.Numeric(20, 6), nullable=True))
    op.add_column("cost_entries", sa.Column("unit", sa.String(length=32), nullable=True))
    op.add_column("cost_entries", sa.Column("vendor_cost", sa.Numeric(20, 12), nullable=True))
    op.add_column("cost_entries", sa.Column("vendor_currency", sa.String(length=8), nullable=True))
    op.drop_index("ix_cost_entries_platform_occurred", table_name="cost_entries")
    op.drop_column("cost_entries", "managed_by")
    op.create_index(
        "ix_cost_entries_platform_occurred",
        "cost_entries",
        ["occurred_at", "id"],
        postgresql_where=sa.text("payer = 'platform'"),
    )
    op.create_index(
        "ix_cost_entries_subject_occurred",
        "cost_entries",
        ["workspace_id", "subject_id", "occurred_at"],
    )
    op.create_index(
        "ix_cost_entries_client_occurred",
        "cost_entries",
        ["workspace_id", "client_id", "occurred_at"],
        postgresql_where=sa.text("client_id IS NOT NULL"),
    )
    op.add_column(
        "openapi_connections", sa.Column("managed_by", sa.String(length=32), nullable=True)
    )
    op.create_table(
        "client_openapi_connections",
        sa.Column(
            "client_id",
            sa.UUID(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "openapi_connection_id",
            sa.UUID(),
            sa.ForeignKey("openapi_connections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("namespace_prefix", sa.String(length=64), nullable=True),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
    )
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_WITH_METERED_TOOLS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_WITH_PAID_TOOLS)
    op.drop_table("client_openapi_connections")
    op.drop_column("openapi_connections", "managed_by")
    op.drop_index("ix_cost_entries_client_occurred", table_name="cost_entries")
    op.drop_index("ix_cost_entries_subject_occurred", table_name="cost_entries")
    op.drop_index("ix_cost_entries_platform_occurred", table_name="cost_entries")
    op.add_column("cost_entries", sa.Column("managed_by", sa.String(length=32), nullable=True))
    op.execute("UPDATE cost_entries SET managed_by = 'platform' WHERE payer = 'platform'")
    op.create_index(
        "ix_cost_entries_platform_occurred",
        "cost_entries",
        ["occurred_at", "id"],
        postgresql_where=sa.text("managed_by = 'platform'"),
    )
    for column in ("vendor_currency", "vendor_cost", "unit", "quantity", "payer"):
        op.drop_column("cost_entries", column)
