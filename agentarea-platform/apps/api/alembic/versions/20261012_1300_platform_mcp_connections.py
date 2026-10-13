"""platform-managed MCP connections, and their calls in task totals

``mcp_server_instances.managed_by``: ``'platform'`` marks a connection the
deployment operator supplies to every workspace, on a credential only the platform
holds — the same column and the same meaning as ``provider_configs.managed_by``.
NULL is a workspace's own connection, which every existing row is.

``task_summary.cost_usd`` also sums the ``cost`` of a ``tool.result`` on such a
connection: a paid tool call, priced in the billing currency, which the run's total
cost already includes. Both view definitions are spelled out in full, as in
20260930_1200_model_kind_video.

Revision ID: 20261012_1300_platform_mcp
Revises: 20261008_1200_cost_entries
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_1300_platform_mcp"
down_revision: str | None = "20261008_1200_cost_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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

CREATE_VIEW_WITH_MODEL_COST = """
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


def upgrade() -> None:
    op.add_column(
        "mcp_server_instances", sa.Column("managed_by", sa.String(length=32), nullable=True)
    )
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_WITH_PAID_TOOLS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_WITH_MODEL_COST)
    op.drop_column("mcp_server_instances", "managed_by")
