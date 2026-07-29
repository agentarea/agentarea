"""Rename historical task_events to the canonical vocabulary

The previous migration made task_summary canonical-only, which silently NULLed
ended_at, duration_ms and final_response for every task recorded before the
rename — on a dev database, 711 of 746 tasks lost their end time. Dropping the
legacy names from the READ side without moving the DATA does not retire legacy;
it just hides it, and the /summary endpoint serves the hole.

So the rows move instead. Only names with an exact canonical counterpart are
rewritten; IterationStarted/Completed, AgentDelegation*, WorkflowCommandReceived
and the rest keep their names because the emit side still produces them
verbatim — they are un-canonicalised, not legacy, and renaming them here would
desynchronise the view from the writer.

ToolCallFailed additionally gains ``success: false``, because the canonical
contract has no distinct failed-tool type: failure rides in the payload, and
that is what task_summary counts.

Revision ID: 20260717_0200_backfill_canon
Revises: 20260717_0100_task_summary_canon
Create Date: 2026-07-17 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0200_backfill_canon"
down_revision: str | None = "20260717_0100_task_summary_canon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Legacy name -> canonical name. Both the bare and the "workflow."-prefixed
# spellings occur in historical rows.
RENAMES: tuple[tuple[str, str], ...] = (
    ("WorkflowStarted", "task.started"),
    ("WorkflowCompleted", "task.completed"),
    ("WorkflowFailed", "task.failed"),
    ("WorkflowCancelled", "task.cancelled"),
    ("LLMCallStarted", "llm.call.started"),
    ("LLMCallCompleted", "llm.call.completed"),
    ("LLMCallFailed", "llm.call.failed"),
    ("LLMCallChunk", "llm.call.chunk"),
    ("ToolCallStarted", "tool.call"),
    ("ToolCallCompleted", "tool.result"),
    ("ToolCallFailed", "tool.result"),
    ("HumanInputRequested", "input.request"),
)


def upgrade() -> None:
    # A failed tool is a tool.result whose payload says so. Mark them before the
    # rename, while they are still identifiable.
    op.execute(
        """
        UPDATE task_events
        SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{success}', 'false'::jsonb)
        WHERE event_type IN ('ToolCallFailed', 'workflow.ToolCallFailed')
        """
    )
    statement = sa.text(
        """
        UPDATE task_events
        SET event_type = :canonical
        WHERE event_type IN (:legacy, :prefixed)
        """
    )
    connection = op.get_bind()
    for legacy, canonical in RENAMES:
        connection.execute(
            statement,
            {"canonical": canonical, "legacy": legacy, "prefixed": f"workflow.{legacy}"},
        )


def downgrade() -> None:
    # Not reversible: several legacy names collapse onto one canonical name
    # (ToolCallCompleted and ToolCallFailed both become tool.result), so the
    # original spelling cannot be recovered. The rows stay canonical, which the
    # previous revision's view understands.
    pass
