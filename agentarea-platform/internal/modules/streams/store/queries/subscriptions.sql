-- name: InsertSubscription :one
INSERT INTO stream_subscriptions (id, workspace_id, created_by, created_at, updated_at, stream_id, kind, trigger_id,
    filter, output_stream_ids, status, started_at, code)
VALUES (@id, @workspace_id, @created_by, @now, @now, @stream_id, @kind, sqlc.narg(trigger_id),
    @filter, @output_stream_ids, @status, @started_at, sqlc.narg(code))
RETURNING *;

-- name: ListSubscriptions :many
SELECT * FROM stream_subscriptions WHERE workspace_id = @workspace_id AND stream_id = @stream_id
ORDER BY created_at, id;

-- name: GetSubscriptionInStream :one
SELECT * FROM stream_subscriptions WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND id = @id;

-- name: GetActiveSubscription :one
SELECT * FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND id = @id AND status = 'active'
  AND (expires_at IS NULL OR expires_at > now());

-- name: UpdateProcessor :one
UPDATE stream_subscriptions SET code = @code, output_stream_ids = @output_stream_ids, filter = @filter, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id
RETURNING *;

-- name: DeleteSubscription :execrows
DELETE FROM stream_subscriptions WHERE workspace_id = @workspace_id AND id = @id;

-- name: TriggerIDsOnStream :many
SELECT trigger_id FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND kind = 'trigger' AND trigger_id IS NOT NULL
ORDER BY created_at, id;

-- name: WritersInto :many
SELECT * FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND kind IN ('forward', 'processor')
  AND output_stream_ids::jsonb @> jsonb_build_array(@stream_id::text)
ORDER BY created_at, id;

-- name: ExternalSubscriptionsOnStream :many
SELECT * FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND kind = 'external';

-- name: ListStreamSubscriptionsAnyWorkspace :many
SELECT * FROM stream_subscriptions WHERE stream_id = @stream_id ORDER BY created_at, id;
