"""task_summary read-side view derived from task_events.

The platform is event-sourced — every fact about a task lives in
``task_events``. Read paths shouldn't reconstruct that timeline by hand;
they should query a denormalized projection. This first projection is a
plain Postgres view because the read pattern is per-task point lookup
(GET /tasks/{id}/summary, get_task_summary agent tool, delegation
tool-message synthesis). When read latency requires it later, swap the
view's body for a materialized view, then for a write-time projection
table — callers go through a repository method, so the view's
implementation is replaceable without breaking clients.

Columns are intentionally a small, stable contract. Per-tool breakdowns
and per-artifact lists belong in their own views (added later) so the
headline summary stays small and additive evolution doesn't break
existing consumers.

Revision ID: nn1_task_summary_view
Revises: mm1_drop_project_minio_prefix
"""

from alembic import op


revision = "nn1_task_summary_view"
down_revision = "mm1_drop_project_minio_prefix"
branch_labels = None
depends_on = None


CREATE_VIEW = """
CREATE OR REPLACE VIEW task_summary AS
SELECT
    t.id                      AS task_id,
    t.agent_id                AS agent_id,
    t.workspace_id            AS workspace_id,
    t.user_id                 AS user_id,
    t.status                  AS status,
    t.created_at              AS started_at,
    MAX(e.timestamp) FILTER (
        WHERE e.event_type IN ('WorkflowCompleted', 'WorkflowFailed')
    )                         AS ended_at,
    EXTRACT(EPOCH FROM (
        MAX(e.timestamp) FILTER (
            WHERE e.event_type IN ('WorkflowCompleted', 'WorkflowFailed')
        ) - t.created_at
    )) * 1000                 AS duration_ms,
    COUNT(*) FILTER (WHERE e.event_type = 'IterationCompleted')        AS iterations,
    COUNT(*) FILTER (WHERE e.event_type = 'LLMCallCompleted')          AS llm_calls,
    COUNT(*) FILTER (WHERE e.event_type = 'LLMCallFailed')             AS llm_calls_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'ToolCallStarted')           AS tools_called,
    COUNT(*) FILTER (WHERE e.event_type = 'ToolCallFailed')            AS tools_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationStarted')    AS delegations_started,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationCompleted')  AS delegations_completed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationFailed')     AS delegations_failed,
    -- Total cost rolled up from per-iteration LLMCallCompleted events.
    -- Cost can land as a string (e.g. "0.0014") or number; coerce both.
    COALESCE(SUM(
        CASE
            WHEN e.event_type = 'LLMCallCompleted' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    -- The child's own narrative answer (set by completion tool).
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type = 'WorkflowCompleted'
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
    -- Last error surfaced by the workflow, if any.
    (
        SELECT e3.data ->> 'error'
        FROM task_events e3
        WHERE e3.task_id = t.id
          AND e3.event_type IN ('WorkflowFailed', 'LLMCallFailed', 'ToolCallFailed')
        ORDER BY e3.timestamp DESC
        LIMIT 1
    )                         AS last_error
FROM tasks t
LEFT JOIN task_events e ON e.task_id = t.id
GROUP BY t.id;
"""


def upgrade() -> None:
    op.execute(CREATE_VIEW)
    # Read paths filter by task_id and workspace_id; the underlying tasks
    # primary key already covers the former. Add an index on task_events
    # for (task_id, event_type) so the FILTER aggregates stay fast as
    # the event log grows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_events_task_id_event_type "
        "ON task_events (task_id, event_type);"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS task_summary;")
    op.execute("DROP INDEX IF EXISTS ix_task_events_task_id_event_type;")
