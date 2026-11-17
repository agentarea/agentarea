-- name: ReactionsForEvents :many
SELECT id, trigger_id, subscription_id, stream_id, event_id, status, verdict, reason, score, task_id,
    derived_event_ids, created_at
FROM trigger_executions
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND event_id = ANY(@event_ids::uuid[])
ORDER BY created_at, id;

-- name: ReactionsForSubscription :many
SELECT id, trigger_id, subscription_id, stream_id, event_id, status, verdict, reason, score, task_id,
    derived_event_ids, created_at
FROM trigger_executions
WHERE workspace_id = @workspace_id AND subscription_id = @subscription_id
ORDER BY created_at DESC, id DESC
LIMIT @lim;

-- name: ReactionExists :one
SELECT EXISTS (SELECT 1 FROM trigger_executions WHERE subscription_id = @subscription_id AND event_id = @event_id);

-- name: InsertReaction :one
INSERT INTO trigger_executions (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workflow_id, workspace_id, created_by, created_at, updated_at, fired_by, subscription_id,
    stream_id, event_id, verdict, reason, score, derived_event_ids, correlation_id, causation_id)
VALUES (@id, sqlc.narg(trigger_id), @now, @status, sqlc.narg(task_id), @execution_time_ms, sqlc.narg(error_message),
    @trigger_data, sqlc.narg(workflow_id), @workspace_id, @created_by, @now, @now, sqlc.narg(fired_by),
    @subscription_id, @stream_id, @event_id, @verdict, sqlc.narg(reason), sqlc.narg(score), @derived_event_ids,
    sqlc.narg(correlation_id), sqlc.narg(causation_id))
ON CONFLICT ON CONSTRAINT uq_trigger_executions_subscription_event DO NOTHING
RETURNING id;

-- name: ReactionTally :one
SELECT count(*)::int AS reacted,
    count(*) FILTER (WHERE COALESCE(verdict, '') = 'skipped' OR (verdict IS NULL AND status = 'skipped'))::int AS skipped,
    count(*) FILTER (WHERE verdict = 'error')::int AS errors
FROM trigger_executions WHERE workspace_id = @workspace_id AND event_id = @event_id AND subscription_id IS NOT NULL;

-- name: TriggerNames :many
SELECT id, name FROM triggers WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);
