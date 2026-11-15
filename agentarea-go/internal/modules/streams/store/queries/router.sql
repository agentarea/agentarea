-- name: StampTriggerExecuted :exec
UPDATE triggers SET last_execution_at = @at, updated_at = @at
WHERE id = @id AND workspace_id = @workspace_id;

-- name: CountTriggerFailure :one
UPDATE triggers SET consecutive_failures = consecutive_failures + 1, updated_at = @at
WHERE id = @id AND workspace_id = @workspace_id
RETURNING consecutive_failures, failure_threshold, is_active;

-- name: MarkTriggerNeedsNewOwner :execrows
UPDATE triggers SET is_active = false, needs_new_owner_at = @at, updated_at = @at
WHERE id = @id AND workspace_id = @workspace_id;

-- name: TriggerNamesTask :one
SELECT EXISTS (SELECT 1 FROM trigger_executions
    WHERE trigger_id = @trigger_id AND task_id = @task_id AND workspace_id = @workspace_id);

-- name: InsertFiring :one
INSERT INTO trigger_executions (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workspace_id, created_by, created_at, updated_at, fired_by)
VALUES (@id, @trigger_id, @at, @status, sqlc.narg(task_id), @execution_time_ms, sqlc.narg(error_message),
    @trigger_data, @workspace_id, @created_by, @at, @at, sqlc.narg(fired_by))
RETURNING id, executed_at;

-- name: InsertCausedFiring :exec
INSERT INTO trigger_executions (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workspace_id, created_by, created_at, updated_at, fired_by, subscription_id, stream_id, event_id,
    verdict, reason, correlation_id, causation_id)
VALUES (@id, sqlc.narg(trigger_id), @at, @status, sqlc.narg(task_id), @execution_time_ms, sqlc.narg(error_message),
    @trigger_data, @workspace_id, @created_by, @at, @at, sqlc.narg(fired_by), @subscription_id, @stream_id, @event_id,
    @verdict, sqlc.narg(error_message), @correlation_id, @causation_id)
ON CONFLICT ON CONSTRAINT uq_trigger_executions_subscription_event DO NOTHING;

-- name: ReactionOfEvent :one
SELECT id, executed_at, verdict, task_id FROM trigger_executions
WHERE subscription_id = @subscription_id AND event_id = @event_id AND workspace_id = @workspace_id;

-- name: DeleteReactionOfEvent :exec
DELETE FROM trigger_executions
WHERE subscription_id = @subscription_id AND event_id = @event_id AND workspace_id = @workspace_id;

-- name: RecordedSubscriptions :many
SELECT subscription_id::uuid AS subscription_id FROM trigger_executions
WHERE event_id = @event_id AND subscription_id IS NOT NULL AND workspace_id = @workspace_id
    AND NOT (verdict IS NOT DISTINCT FROM 'error' AND reason IS NOT DISTINCT FROM @gave_up::text);

-- name: ForgetGivenUp :exec
DELETE FROM trigger_executions
WHERE subscription_id = @subscription_id AND event_id = @event_id AND workspace_id = @workspace_id
    AND verdict = 'error' AND reason = @gave_up::text;

-- name: UpsertReaction :exec
INSERT INTO trigger_executions AS te (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workflow_id, workspace_id, created_by, created_at, updated_at, subscription_id, stream_id, event_id,
    verdict, reason, score, derived_event_ids, correlation_id, causation_id)
VALUES (@id, sqlc.narg(trigger_id), @at, @status, sqlc.narg(task_id), 0, sqlc.narg(error_message),
    '{}'::json, sqlc.narg(workflow_id), @workspace_id, @created_by, @at, @at, @subscription_id, @stream_id, @event_id,
    @verdict, sqlc.narg(reason), sqlc.narg(score), @derived_event_ids, @correlation_id, @causation_id)
ON CONFLICT ON CONSTRAINT uq_trigger_executions_subscription_event DO UPDATE SET
    verdict = excluded.verdict,
    reason = COALESCE(excluded.reason, te.reason),
    score = COALESCE(excluded.score, te.score),
    task_id = COALESCE(te.task_id, excluded.task_id),
    derived_event_ids = excluded.derived_event_ids,
    workflow_id = COALESCE(excluded.workflow_id, te.workflow_id),
    updated_at = @at
WHERE excluded.verdict <> 'batched' OR te.verdict = 'batched';

-- name: RouterTally :one
SELECT count(*) FILTER (WHERE verdict IS DISTINCT FROM 'batched')::int AS reacted,
    count(*) FILTER (WHERE verdict = 'skipped')::int AS skipped,
    count(*) FILTER (WHERE verdict = 'error')::int AS errors
FROM trigger_executions
WHERE event_id = @event_id AND subscription_id IS NOT NULL AND workspace_id = @workspace_id;

-- name: SettledOfBatch :many
SELECT event_id::uuid AS event_id FROM trigger_executions
WHERE subscription_id = @subscription_id AND event_id = ANY(@event_ids::uuid[]) AND workspace_id = @workspace_id
    AND verdict IS DISTINCT FROM 'batched';

-- name: SettleReaction :exec
INSERT INTO trigger_executions AS te (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workflow_id, workspace_id, created_by, created_at, updated_at, subscription_id, stream_id, event_id,
    verdict, reason, correlation_id, causation_id)
VALUES (@id, sqlc.narg(trigger_id), @at, @status, sqlc.narg(task_id), 0, sqlc.narg(error_message),
    '{}'::json, @workflow_id, @workspace_id, @created_by, @at, @at, @subscription_id, @stream_id, @event_id,
    @verdict, sqlc.narg(reason), @correlation_id, @causation_id)
ON CONFLICT ON CONSTRAINT uq_trigger_executions_subscription_event DO UPDATE SET
    status = excluded.status, verdict = excluded.verdict, reason = excluded.reason,
    error_message = excluded.error_message, task_id = excluded.task_id, workflow_id = excluded.workflow_id,
    updated_at = @at
WHERE te.verdict = 'batched';

-- name: HeldByTrigger :many
SELECT event_id::uuid AS event_id, COALESCE(workflow_id, '')::text AS workflow_id FROM trigger_executions
WHERE trigger_id = @trigger_id AND verdict = 'batched' AND workspace_id = @workspace_id AND event_id IS NOT NULL;

-- name: SkipHeld :exec
UPDATE trigger_executions SET status = 'skipped', verdict = 'skipped', reason = @reason, updated_at = @at
WHERE trigger_id = @trigger_id AND verdict = 'batched' AND workspace_id = @workspace_id;

-- name: SubscriptionInWorkspace :one
SELECT EXISTS (SELECT 1 FROM stream_subscriptions WHERE id = @id AND workspace_id = @workspace_id);

-- name: EventsByIDs :many
SELECT * FROM stream_events WHERE workspace_id = @workspace_id AND event_id = ANY(@ids::uuid[]);

-- name: ClaimReaction :execrows
INSERT INTO trigger_executions (id, trigger_id, executed_at, status, task_id, execution_time_ms, trigger_data,
    workspace_id, created_by, created_at, updated_at, subscription_id, stream_id, event_id, verdict, reason,
    correlation_id, causation_id)
VALUES (@id, sqlc.narg(trigger_id), @at, 'success', @task_id, 0, '{}'::json, @workspace_id, @created_by, @at, @at,
    @subscription_id, @stream_id, @event_id, 'reacted', @reason, @correlation_id, @causation_id)
ON CONFLICT ON CONSTRAINT uq_trigger_executions_subscription_event DO NOTHING;
