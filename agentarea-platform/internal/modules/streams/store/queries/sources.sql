-- name: InsertSource :one
INSERT INTO stream_sources (id, workspace_id, created_by, created_at, updated_at, stream_id, kind, webhook_id,
    webhook_type, webhook_config, credential_key, event_templates, senders)
VALUES (@id, @workspace_id, @created_by, @now, @now, @stream_id, @kind, sqlc.narg(webhook_id), sqlc.narg(webhook_type),
    @webhook_config, sqlc.narg(credential_key), @event_templates, @senders)
RETURNING *;

-- name: ListSources :many
SELECT * FROM stream_sources WHERE workspace_id = @workspace_id AND stream_id = @stream_id
ORDER BY created_at, id;

-- name: GetSourceInStream :one
SELECT * FROM stream_sources WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND id = @id;

-- name: SetSourceSenders :one
UPDATE stream_sources SET senders = @senders, updated_at = @now
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND id = @id
RETURNING *;

-- name: DeleteSource :execrows
DELETE FROM stream_sources WHERE workspace_id = @workspace_id AND id = @id;

-- FindWebhookSource runs before any workspace is known: the source names its workspace.
-- name: FindWebhookSource :one
SELECT * FROM stream_sources WHERE webhook_id = @webhook_id AND kind = 'webhook';

-- name: EndSourceSubscription :execrows
UPDATE stream_sources SET registered_url = NULL, subscription_id = NULL, refresh_before = NULL,
    poll_error = @poll_error, updated_at = @now
WHERE id = @id;
