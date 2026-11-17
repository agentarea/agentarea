-- The sources the pollers act on, in every workspace: poll sources and webhook sources whose type registers.
-- name: PollingSources :many
SELECT id, workspace_id, created_by, kind, webhook_type, webhook_id, credential_key, webhook_config,
    poll_cursor, registered_url, subscription_id, refresh_before, poll_error, polled_at
FROM stream_sources
WHERE kind IN ('poll', 'webhook') AND webhook_type IS NOT NULL
ORDER BY created_at;

-- name: SourcePolled :exec
UPDATE stream_sources
SET poll_cursor = COALESCE(NULLIF(@cursor::text, ''), poll_cursor), polled_at = @now, poll_error = NULL
WHERE id = @id;

-- name: SourceFailed :exec
UPDATE stream_sources SET polled_at = @now, poll_error = @reason WHERE id = @id;

-- name: SourceSubscribeFailed :exec
UPDATE stream_sources SET poll_error = @reason, polled_at = @now, refresh_before = @retry_at WHERE id = @id;

-- name: SourceSubscribed :exec
UPDATE stream_sources
SET registered_url = @url, subscription_id = @subscription_id, refresh_before = sqlc.narg(refresh_before),
    poll_cursor = COALESCE(NULLIF(@cursor::text, ''), poll_cursor), poll_error = NULL
WHERE id = @id;

-- name: SourceRegistered :exec
UPDATE stream_sources SET registered_url = NULLIF(@url::text, ''), poll_error = NULL WHERE id = @id;
