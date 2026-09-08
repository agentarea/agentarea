"""Index task_events for reading one event type in time order.

``task_events`` is append-only and unbounded — it grows with every LLM call, tool call and
status change of every task, forever. Its indexes today cover the columns the ORM mixins
declare (``workspace_id``, ``created_by``) and the per-task reads. Nothing covers "give me
events of type X, oldest first", which is the shape of every consumer that tails the log
rather than opening one task: ``TaskEventRepository.get_events_by_type`` does exactly this
and is a sequential scan on a table that only gets longer.

The trailing ``id`` is what makes keyset pagination exact. A tailing consumer resumes from
``(timestamp, id) > (last_timestamp, last_id)``, and without the tiebreaker in the index
Postgres has to fetch and re-filter every row sharing the boundary timestamp — and a
consumer paginating on ``timestamp`` alone cannot make progress at all once one batch is
filled by rows that share a timestamp.

Built CONCURRENTLY. A plain CREATE INDEX takes a lock that blocks writes for the duration,
and writes to this table are on the path of every running agent — a few seconds of index
build would stall live executions.

Revision ID: 20260908_1000_task_events_idx
Revises: 20260907_1300_openapi_registry
Create Date: 2026-09-08 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_1000_task_events_idx"
down_revision: str | None = "20260907_1300_openapi_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_task_events_type_timestamp_id"


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction, and Alembic wraps migrations in one.
    #
    # The trade-off it buys is worth stating: a concurrent build that fails leaves an
    # INVALID index behind, and `IF NOT EXISTS` will then skip rebuilding it — so a
    # failure here needs a manual DROP before a retry, rather than being self-healing.
    # That is the better failure: an invalid index is inert and visible in pg_index, while
    # a blocking build is an outage of every running agent.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            "ON task_events (event_type, timestamp, id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
