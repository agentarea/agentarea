-- name: ExternalSubscriptionByKey :one
SELECT * FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND kind = 'external' AND external_id = @external_id;

-- name: CountExternalSubscriptions :one
SELECT count(*) FROM stream_subscriptions WHERE workspace_id = @workspace_id AND kind = 'external';

-- name: ExternalEndpointVerified :one
SELECT EXISTS (
    SELECT 1 FROM stream_subscriptions
    WHERE workspace_id = @workspace_id AND kind = 'external' AND subscriber = @subscriber
        AND callback_url = @callback_url AND verified_at IS NOT NULL
);

-- name: InsertExternalSubscription :one
INSERT INTO stream_subscriptions (id, workspace_id, created_by, created_at, updated_at, stream_id, kind, filter,
    output_stream_ids, status, started_at, external_id, subscriber, callback_url, secret_name, expires_at, verified_at)
VALUES (@id, @workspace_id, @created_by, @now, @now, @stream_id, 'external', @filter, '[]', 'active', @started_at,
    @external_id, @subscriber, @callback_url, @secret_name, @expires_at, @verified_at)
RETURNING *;

-- name: RefreshExternalSubscription :one
UPDATE stream_subscriptions SET expires_at = @expires_at, status = 'active',
    verified_at = COALESCE(verified_at, @verified_at), updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id
RETURNING *;
