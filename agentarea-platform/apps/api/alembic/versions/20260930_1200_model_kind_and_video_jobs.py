"""model kind and video generation jobs

Every model spec gets a ``kind`` (chat, embedding, image, video, decision). Each
surface a model can be bound to accepts exactly one kind, so the column is not
null; every existing row is a chat model. ``context_window`` becomes nullable:
image and video models take no conversation, and providers publish none for them.

``video_generation_jobs`` maps the id an agent holds to the provider's job id,
which stays server-side: it is only valid under the credential that submitted
it, and that may be the platform's shared key.

``task_summary.cost_usd`` also sums the ``model_cost`` a tool result carries
(image, video and decision calls), which the run's total cost already includes.
Both view definitions are spelled out in full, as in 20260915_1200_drop_tasks_uid.

Revision ID: 20260930_1200_model_kind_video
Revises: 20260927_1200_catalog_cleanup
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260930_1200_model_kind_video"
down_revision: str | None = "20260927_1200_catalog_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ("chat", "embedding", "image", "video", "decision")

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

CREATE_VIEW_LLM_COST_ONLY = """
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


def upgrade() -> None:
    op.add_column(
        "model_specs",
        sa.Column("kind", sa.String(16), nullable=False, server_default="chat"),
    )
    op.create_check_constraint(
        "ck_model_specs_kind",
        "model_specs",
        "kind IN (" + ", ".join(f"'{k}'" for k in _KINDS) + ")",
    )
    op.alter_column("model_specs", "context_window", existing_type=sa.Integer(), nullable=True)

    op.create_table(
        "video_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column(
            "model_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(255), nullable=True),
        sa.Column("provider_job_id", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("cost_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("billed_cost", sa.Numeric(20, 12), nullable=True),
        sa.Column("billed_call_ref", sa.String(255), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_video_generation_jobs_workspace_id", "video_generation_jobs", ["workspace_id"]
    )
    op.create_index("ix_video_generation_jobs_created_by", "video_generation_jobs", ["created_by"])
    op.create_index("ix_video_generation_jobs_task_id", "video_generation_jobs", ["task_id"])

    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_WITH_MODEL_COST)


def downgrade() -> None:
    # Refuse rather than delete: dropping the specs would cascade to their model
    # instances and whatever agents and triggers name them. Remove them first.
    non_chat = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM model_specs WHERE kind <> 'chat' OR context_window IS NULL"
            )
        )
        .scalar_one()
    )
    if non_chat:
        raise RuntimeError(
            f"{non_chat} model spec(s) are not chat models or have no context window; "
            "the previous schema cannot hold them. Delete them (and their model "
            "instances) before downgrading."
        )

    op.execute("DROP VIEW IF EXISTS task_summary")
    op.execute(CREATE_VIEW_LLM_COST_ONLY)
    op.drop_index("ix_video_generation_jobs_task_id", table_name="video_generation_jobs")
    op.drop_index("ix_video_generation_jobs_created_by", table_name="video_generation_jobs")
    op.drop_index("ix_video_generation_jobs_workspace_id", table_name="video_generation_jobs")
    op.drop_table("video_generation_jobs")
    op.alter_column("model_specs", "context_window", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("ck_model_specs_kind", "model_specs", type_="check")
    op.drop_column("model_specs", "kind")
