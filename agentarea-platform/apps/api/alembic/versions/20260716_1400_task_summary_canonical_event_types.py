"""task_summary view recognizes canonical event-type names

The workflow emit-side now canonicalizes every task event to the dotted contract
vocabulary (``WorkflowCompleted`` -> ``task.completed``, ``LLMCallCompleted`` ->
``llm.call.completed``, ``ToolCallStarted`` -> ``tool.call``, …), so NEW rows in
``task_events`` carry the canonical names. OLD rows keep their legacy names — no
data migration. This redefines the ``task_summary`` view so its FILTER clauses
match BOTH vocabularies, keeping the per-task rollup correct across the rename.

Revision ID: 20260716_1400_task_summary_evt
Revises: 20260716_1251_add_event_outbox
Create Date: 2026-07-16 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_1400_task_summary_evt"
down_revision: str | None = "20260716_1251_add_event_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Legacy names are still present in historical rows; canonical names land on every
# new row. Both are accepted so the rollup is correct across the vocabulary rename.
CREATE_VIEW_CANONICAL = """
CREATE OR REPLACE VIEW task_summary AS
SELECT
    t.id                      AS task_id,
    t.agent_id                AS agent_id,
    t.workspace_id            AS workspace_id,
    t.user_id                 AS user_id,
    t.status                  AS status,
    t.created_at              AS started_at,
    MAX(e.timestamp) FILTER (
        WHERE e.event_type IN ('WorkflowCompleted', 'WorkflowFailed',
                               'task.completed', 'task.failed')
    )                         AS ended_at,
    EXTRACT(EPOCH FROM (
        MAX(e.timestamp) FILTER (
            WHERE e.event_type IN ('WorkflowCompleted', 'WorkflowFailed',
                                   'task.completed', 'task.failed')
        ) - t.created_at
    )) * 1000                 AS duration_ms,
    COUNT(*) FILTER (WHERE e.event_type IN ('IterationCompleted'))     AS iterations,
    COUNT(*) FILTER (WHERE e.event_type IN ('LLMCallCompleted',
                                            'llm.call.completed'))      AS llm_calls,
    COUNT(*) FILTER (WHERE e.event_type IN ('LLMCallFailed',
                                            'llm.call.failed'))         AS llm_calls_failed,
    COUNT(*) FILTER (WHERE e.event_type IN ('ToolCallStarted',
                                            'tool.call'))               AS tools_called,
    COUNT(*) FILTER (WHERE e.event_type IN ('ToolCallFailed'))         AS tools_failed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationStarted')    AS delegations_started,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationCompleted')  AS delegations_completed,
    COUNT(*) FILTER (WHERE e.event_type = 'AgentDelegationFailed')     AS delegations_failed,
    -- Total cost rolled up from per-iteration LLM completion events.
    -- Cost can land as a string (e.g. "0.0014") or number; coerce both.
    COALESCE(SUM(
        CASE
            WHEN e.event_type IN ('LLMCallCompleted', 'llm.call.completed')
                 AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    -- The child's own narrative answer (set by completion tool).
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type IN ('WorkflowCompleted', 'task.completed')
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
    -- Last error surfaced by the workflow, if any.
    (
        SELECT e3.data ->> 'error'
        FROM task_events e3
        WHERE e3.task_id = t.id
          AND e3.event_type IN ('WorkflowFailed', 'LLMCallFailed', 'ToolCallFailed',
                                'task.failed', 'llm.call.failed')
        ORDER BY e3.timestamp DESC
        LIMIT 1
    )                         AS last_error
FROM tasks t
LEFT JOIN task_events e ON e.task_id = t.id
GROUP BY t.id;
"""


CREATE_VIEW_LEGACY = """
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
    COALESCE(SUM(
        CASE
            WHEN e.event_type = 'LLMCallCompleted' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type = 'WorkflowCompleted'
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
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
    op.execute(CREATE_VIEW_CANONICAL)


def downgrade() -> None:
    op.execute(CREATE_VIEW_LEGACY)
