"""Backfill: every webhook trigger gets a stream, a webhook source, a subscription

The source keeps the trigger's webhook_id, so no public URL changes. Signing
secrets stay where they are: credential_key is the trigger id, the key the
existing channel_cred:{type}:{trigger_id} secrets are stored under. Ids are
derived from the trigger id so the downgrade can find exactly these rows.
retention_days is 30, the AGENTAREA_EVENT_RETENTION default at the time of
writing; a migration cannot read runtime settings.

A webhook_id some source already owns (the app created it after an earlier
upgrade) is left alone. JSON columns are read the way the trigger repository
reads them: a JSON null or an empty method list is the trigger's default. The
stream name shortens the trigger name so a long webhook_id still fits. The
downgrade removes these rows and, by cascade, their journal, outcomes and any
other subscription made on these streams since.

Revision ID: 20261006_0920_webhook_backfill
Revises: 20261006_0910_task_provenance
Create Date: 2026-10-06
"""

# Every interpolated value below is a module constant, never input.
# ruff: noqa: S608

from collections.abc import Sequence

from alembic import op

revision: str = "20261006_0920_webhook_backfill"
down_revision: str | None = "20261006_0910_task_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PENDING = """
    t.trigger_type = 'webhook' AND t.webhook_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM stream_sources s WHERE s.webhook_id = t.webhook_id)
"""
_WEBHOOK_TYPE = "coalesce(nullif(t.webhook_type, ''), 'generic')"
_NAME_SUFFIX = "' (' || t.webhook_id || ')'"
_STREAM_NAME = f"""
    left(left(t.name, least(200, greatest(0, 255 - length({_NAME_SUFFIX})))) || {_NAME_SUFFIX},
         255)
"""
_ALLOWED_METHODS = """
    CASE WHEN coalesce(t.allowed_methods::jsonb, 'null') IN ('null', '[]')
         THEN '["POST"]'::json ELSE t.allowed_methods END
"""
_VALIDATION_RULES = """
    CASE WHEN coalesce(t.validation_rules::jsonb, 'null') = 'null'
         THEN '{}'::json ELSE t.validation_rules END
"""
_EVENT_TYPES = """
    CASE WHEN coalesce(t.event_types::jsonb, 'null') = 'null'
         THEN '[]'::json ELSE t.event_types END
"""

UPGRADE_SQL: list[str] = [
    f"""
    DO $$
    DECLARE shared text;
    BEGIN
      SELECT string_agg(webhook_id, ', ' ORDER BY webhook_id) INTO shared FROM (
        SELECT t.webhook_id FROM triggers t WHERE {_PENDING}
        GROUP BY t.webhook_id HAVING count(*) > 1) d;
      IF shared IS NOT NULL THEN
        RAISE EXCEPTION 'webhook ids shared by more than one trigger cannot each own a source: %',
          shared;
      END IF;
    END $$
    """,
    f"""
    INSERT INTO streams (id, workspace_id, created_by, name, description, kind, retention_days,
                         created_at, updated_at)
    SELECT md5('stream:' || t.id::text)::uuid, t.workspace_id, t.created_by,
           {_STREAM_NAME}, 'Webhook ' || {_WEBHOOK_TYPE}, 'custom', 30, now(), now()
    FROM triggers t WHERE {_PENDING}
    ON CONFLICT (id) DO NOTHING
    """,
    f"""
    INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, webhook_id,
                                webhook_type, allowed_methods, validation_rules, webhook_config,
                                credential_key, created_at, updated_at)
    SELECT md5('source:' || t.id::text)::uuid, t.workspace_id, t.created_by,
           md5('stream:' || t.id::text)::uuid, 'webhook', t.webhook_id,
           {_WEBHOOK_TYPE}, {_ALLOWED_METHODS}, {_VALIDATION_RULES}, t.webhook_config, t.id,
           now(), now()
    FROM triggers t WHERE {_PENDING}
    """,
    f"""
    INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, trigger_id,
                                      filter, output_stream_ids, cursor_sequence, status, attempts,
                                      created_at, updated_at)
    SELECT md5('subscription:' || t.id::text)::uuid, t.workspace_id, t.created_by,
           md5('stream:' || t.id::text)::uuid, 'trigger', t.id,
           json_build_object('kinds', {_EVENT_TYPES}, 'fields', json_build_object()),
           '[]'::json, 0, 'active', 0, now(), now()
    FROM triggers t
    WHERE t.trigger_type = 'webhook'
      AND EXISTS (SELECT 1 FROM stream_sources s WHERE s.id = md5('source:' || t.id::text)::uuid)
      AND NOT EXISTS (SELECT 1 FROM stream_subscriptions s WHERE s.trigger_id = t.id)
    """,
]

DOWNGRADE_SQL: list[str] = [
    """
    DELETE FROM stream_subscriptions
    WHERE trigger_id IS NOT NULL AND id = md5('subscription:' || trigger_id::text)::uuid
    """,
    """
    DELETE FROM streams st USING stream_sources so
    WHERE so.stream_id = st.id AND so.credential_key IS NOT NULL
      AND so.id = md5('source:' || so.credential_key::text)::uuid
      AND st.id = md5('stream:' || so.credential_key::text)::uuid
    """,
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
