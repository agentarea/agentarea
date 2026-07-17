"""task_summary counts canonical events only, and counts failed tools correctly

Two problems with the previous definition:

1. ``tools_failed`` matched only ``'ToolCallFailed'``. That name is never
   emitted: the contract has no distinct failed-tool type — ``TOOL_CALL_FAILED``
   and ``TOOL_CALL_COMPLETED`` are both ``tool.result``, and failure rides in the
   payload. The counter was therefore always 0. It now reads the command's own
   verdict: a non-zero ``exit_code``, or ``success=false`` for tools that have no
   exit code to report.
2. Every other FILTER accepted the pre-contract names alongside the canonical
   ones. The emit side speaks the canonical contract now and the legacy names
   are being retired, so the dual matching is dead weight that hides drift.

Historical rows keep their old names and simply stop being counted — there are
no clients depending on those rollups.

Revision ID: 20260717_0100_task_summary_canon
Revises: 20260716_1400_task_summary_evt
Create Date: 2026-07-17 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0100_task_summary_canon"
down_revision: str | None = "20260716_1400_task_summary_evt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Canonical vocabulary only. A failed tool is a tool.result whose payload says
# so — a non-zero exit_code, or success=false — not an event type of its own.
CREATE_VIEW_CANONICAL_ONLY = """
CREATE OR REPLACE VIEW task_summary AS
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
    -- Total cost rolled up from per-iteration LLM completion events.
    -- Cost can land as a string (e.g. "0.0014") or number; coerce both.
    COALESCE(SUM(
        CASE
            WHEN e.event_type = 'llm.call.completed' AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    -- The child's own narrative answer (set by completion tool).
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type = 'task.completed'
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
    -- Last error surfaced by the workflow, if any.
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

CREATE_VIEW_DUAL_VOCABULARY = """
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
    COALESCE(SUM(
        CASE
            WHEN e.event_type IN ('LLMCallCompleted', 'llm.call.completed')
                 AND e.data ? 'cost'
            THEN (e.data ->> 'cost')::numeric
            ELSE 0
        END
    ), 0)                     AS cost_usd,
    (
        SELECT e2.data ->> 'result'
        FROM task_events e2
        WHERE e2.task_id = t.id
          AND e2.event_type IN ('WorkflowCompleted', 'task.completed')
        ORDER BY e2.timestamp DESC
        LIMIT 1
    )                         AS final_response,
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


def upgrade() -> None:
    op.execute(CREATE_VIEW_CANONICAL_ONLY)


def downgrade() -> None:
    op.execute(CREATE_VIEW_DUAL_VOCABULARY)
