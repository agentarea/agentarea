-- name: ActiveExternalSubscription :one
SELECT * FROM stream_subscriptions
WHERE workspace_id = @workspace_id AND id = @id AND kind = 'external' AND status = 'active'
    AND (expires_at IS NULL OR expires_at > now());

-- name: RecordDeliverySuccess :exec
UPDATE stream_subscriptions SET last_delivery_at = @at, last_error = NULL, failed_since = NULL
WHERE workspace_id = @workspace_id AND id = @id;

-- name: RecordDeliveryFailure :exec
UPDATE stream_subscriptions SET last_error = @error, failed_since = COALESCE(failed_since, @at)
WHERE workspace_id = @workspace_id AND id = @id;

-- name: MarkSubscriptionFailed :exec
UPDATE stream_subscriptions SET status = 'failed' WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteExternalSubscription :execrows
DELETE FROM stream_subscriptions WHERE workspace_id = @workspace_id AND id = @id AND kind = 'external';

-- Expired subscribers are reclaimed in every workspace by one sweeper.
-- name: ExpiredExternalSubscriptions :many
SELECT * FROM stream_subscriptions WHERE kind = 'external' AND expires_at <= now();
