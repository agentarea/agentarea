"""Drop tasks.user_id — created_by is the task's author

Two columns claimed to record who owns a task, and only one was ever wired up.
``TaskORM`` never declared ``user_id``, so SQLAlchemy could neither read nor
write it: the repository writes the author to ``created_by``
(``create_from_data``) and reads the domain model's ``user_id`` field back out
of ``created_by`` (``_orm_to_domain``). The physical column predates that
mapping and is NULL on every row.

The ``task_summary`` view selected the column, which is why the drop needs the
view rebuilt rather than a bare ``DROP COLUMN``. Its consumer is
``GET /agents/{id}/tasks/{id}/summary``, whose ``TaskSummary`` model never
declared ``user_id`` and so has been discarding that permanently-NULL field all
along. The rebuilt view exposes ``created_by`` in its place — the same fact,
actually populated.

Both definitions are spelled out in full, as in 20260717_0100_task_summary_canon:
CREATE OR REPLACE cannot rename or remove a column, so each direction drops and
recreates the view around the ALTER, and the SQL it runs is worth reading
literally.

Reversible, and losslessly so: the column carried no data to lose.

Revision ID: 20260915_1200_drop_tasks_uid
Revises: 20260915_1000_platform_providers
Create Date: 2026-09-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_1200_drop_tasks_uid"
down_revision: str | None = "20260915_1000_platform_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CREATE_VIEW_WITH_CREATED_BY = """
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

CREATE_VIEW_WITH_USER_ID = """
CREATE VIEW task_summary AS
SELECT
    t.id                      AS task_id,
    t.agent_id                AS agent_id,
    t.workspace_id            AS workspace_id,
    t.user_id                 AS user_id,
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
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.drop_column("tasks", "user_id")
    op.execute(CREATE_VIEW_WITH_CREATED_BY)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS task_summary")
    op.add_column("tasks", sa.Column("user_id", sa.String(length=255), nullable=True))
    op.execute(CREATE_VIEW_WITH_USER_ID)
