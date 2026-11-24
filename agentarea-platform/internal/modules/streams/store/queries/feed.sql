-- name: ReactionsForEventIDs :many
SELECT id, trigger_id, subscription_id, stream_id, event_id, status, verdict, reason, score, task_id,
    derived_event_ids, created_at
FROM trigger_executions
WHERE workspace_id = @workspace_id AND event_id = ANY(@event_ids::uuid[]) AND subscription_id IS NOT NULL
ORDER BY created_at, id;
